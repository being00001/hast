"""Productivity orchestration for feedback-driven self-improvement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hast.core.errors import HastError
from hast.core.event_bus import emit_shadow_event
from hast.core.feedback import (
    build_feedback_backlog,
    load_feedback_notes,
    save_feedback_backlog,
)
from hast.core.feedback_infer import infer_and_store_feedback_notes
from hast.core.feedback_policy import load_feedback_policy
from hast.core.feedback_publish import PublishResult, publish_feedback_backlog
from hast.core.observability import build_observability_baseline


@dataclass(frozen=True)
class OrchestrateResult:
    run_id: str | None
    inferred_notes: int
    total_notes: int
    backlog_items: int
    accepted_items: int
    goals_added: int
    publish_result: PublishResult | None
    baseline_ready: bool | None = None
    baseline_failing_guards: tuple[str, ...] = ()
    baseline_window_days: int | None = None


def orchestrate_productivity_cycle(
    root: Path,
    *,
    run_id: str | None,
    window_days: int,
    max_goals: int,
    publish: bool,
    publish_dry_run: bool,
    baseline_window_days: int | None = None,
    enforce_baseline: bool = False,
) -> OrchestrateResult:
    emit_shadow_event(
        root,
        source="orchestrator",
        event_type="orchestrate_cycle_started",
        payload={
            "run_id": run_id,
            "window_days": window_days,
            "max_goals": max_goals,
            "publish": publish,
            "publish_dry_run": publish_dry_run,
            "enforce_baseline": enforce_baseline,
        },
    )

    baseline_window = baseline_window_days if baseline_window_days is not None else window_days
    baseline = build_observability_baseline(root, baseline_window)
    if enforce_baseline and not baseline.baseline_ready:
        reason = "; ".join(baseline.failing_guards[:5]) or "baseline guards failed"
        emit_shadow_event(
            root,
            source="orchestrator",
            event_type="orchestrate_cycle_blocked",
            payload={
                "run_id": run_id,
                "reason": reason,
                "baseline_window_days": baseline_window,
                "failing_guards": list(baseline.failing_guards),
            },
            idempotency_key=f"orchestrate_blocked|{run_id or 'latest'}|{baseline_window}|{reason}",
        )
        raise HastError(
            "observability baseline not ready; orchestrate blocked: "
            + reason
        )

    policy = load_feedback_policy(root)

    inferred_count = 0
    effective_run_id = run_id or find_latest_run_id(root)
    if effective_run_id:
        inferred = infer_and_store_feedback_notes(root, effective_run_id, policy)
        inferred_count = len(inferred)

    notes = [
        note
        for note in load_feedback_notes(root, window_days=window_days)
        if str(note.get("lane") or "project") == "project"
    ]
    backlog_items = build_feedback_backlog(notes, policy=policy, promote=True)
    save_feedback_backlog(root, backlog_items)

    accepted = [item for item in backlog_items if item.get("status") == "accepted"]
    goals_added = sync_productivity_goals(root, accepted, max_goals=max_goals)

    publish_result: PublishResult | None = None
    if publish:
        publish_result = publish_feedback_backlog(
            root,
            policy,
            limit=max_goals,
            dry_run=publish_dry_run,
        )

    emit_shadow_event(
        root,
        source="orchestrator",
        event_type="orchestrate_cycle_completed",
        payload={
            "run_id": effective_run_id,
            "window_days": window_days,
            "max_goals": max_goals,
            "publish": publish,
            "publish_dry_run": publish_dry_run,
            "inferred_notes": inferred_count,
            "total_notes": len(notes),
            "backlog_items": len(backlog_items),
            "accepted_items": len(accepted),
            "goals_added": goals_added,
            "baseline_ready": baseline.baseline_ready,
            "baseline_window_days": baseline_window,
            "failing_guards": list(baseline.failing_guards),
            "publish_attempted": publish_result.attempted if publish_result else 0,
            "publish_published": publish_result.published if publish_result else 0,
            "publish_failed": publish_result.failed if publish_result else 0,
        },
        idempotency_key=f"orchestrate_completed|{effective_run_id or 'latest'}|{baseline_window}",
    )

    return OrchestrateResult(
        run_id=effective_run_id,
        inferred_notes=inferred_count,
        total_notes=len(notes),
        backlog_items=len(backlog_items),
        accepted_items=len(accepted),
        goals_added=goals_added,
        publish_result=publish_result,
        baseline_ready=baseline.baseline_ready,
        baseline_failing_guards=tuple(baseline.failing_guards),
        baseline_window_days=baseline_window,
    )


def sync_productivity_goals(
    root: Path,
    accepted_items: list[dict[str, Any]],
    *,
    max_goals: int,
    root_goal_id: str = "PX_2X",
) -> int:
    goals_path = root / ".ai" / "goals.yaml"
    data = yaml.safe_load(goals_path.read_text(encoding="utf-8")) if goals_path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raw_goals = []

    program_goal = _find_goal_dict(raw_goals, root_goal_id)
    if program_goal is None:
        program_goal = {
            "id": root_goal_id,
            "title": "Productivity 2X Program",
            "status": "active",
            "notes": "Auto-generated by hast orchestrate.",
            "children": [],
        }
        raw_goals.append(program_goal)

    children = program_goal.get("children")
    if not isinstance(children, list):
        children = []
        program_goal["children"] = children

    existing_keys = _collect_feedback_keys(raw_goals)
    next_index = _next_child_index(children, prefix=f"{root_goal_id}.")
    added = 0

    for item in accepted_items:
        if added >= max_goals:
            break
        key = str(item.get("feedback_key") or "").strip()
        if not key or key in existing_keys:
            continue

        title = str(item.get("title") or "feedback improvement").strip()
        summary = str(item.get("summary") or "").strip()
        recommendation = str(item.get("recommended_change") or "").strip()
        issue_url = str(item.get("published_issue_url") or "").strip()

        notes_lines = [
            f"feedback_key: {key}",
            f"summary: {summary}",
            f"recommended_change: {recommendation}",
        ]
        if issue_url:
            notes_lines.append(f"issue: {issue_url}")

        child = {
            "id": f"{root_goal_id}.{next_index}",
            "title": f"Resolve {title[:80]}",
            "status": "active" if added == 0 else "pending",
            "phase": "plan",
            "owner_agent": "architect",
            "feedback_key": key,
            "notes": "\\n".join(notes_lines),
        }
        children.append(child)
        existing_keys.add(key)
        next_index += 1
        added += 1

    data["goals"] = raw_goals
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return added


def find_latest_run_id(root: Path) -> str | None:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return None
    run_ids = [p.name for p in runs_dir.iterdir() if p.is_dir()]
    if not run_ids:
        return None
    return sorted(run_ids)[-1]


def _find_goal_dict(raw_goals: list[dict[str, Any]], goal_id: str) -> dict[str, Any] | None:
    for goal in raw_goals:
        if not isinstance(goal, dict):
            continue
        if goal.get("id") == goal_id:
            return goal
        children = goal.get("children")
        if isinstance(children, list):
            found = _find_goal_dict(children, goal_id)
            if found is not None:
                return found
    return None


def _collect_feedback_keys(raw_goals: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for goal in raw_goals:
        if not isinstance(goal, dict):
            continue
        value = goal.get("feedback_key")
        if isinstance(value, str) and value.strip():
            keys.add(value.strip())
        children = goal.get("children")
        if isinstance(children, list):
            keys.update(_collect_feedback_keys(children))
    return keys


def _next_child_index(children: list[dict[str, Any]], prefix: str) -> int:
    mx = 0
    for child in children:
        if not isinstance(child, dict):
            continue
        goal_id = child.get("id")
        if not isinstance(goal_id, str) or not goal_id.startswith(prefix):
            continue
        suffix = goal_id[len(prefix):]
        if suffix.isdigit():
            mx = max(mx, int(suffix))
    return mx + 1
