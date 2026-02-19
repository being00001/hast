"""Post-completion goal graph replan and invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


_ACTIVE_STATUSES = {"active", "pending"}


@dataclass(frozen=True)
class InvalidationEvent:
    goal_id: str
    from_status: str
    to_status: str
    reason_code: str
    invalidated_by: str
    state_from: str | None
    state_to: str | None


def apply_post_goal_replan(root: Path, completed_goal_id: str) -> list[InvalidationEvent]:
    """Apply invalidation transitions after a goal is completed."""
    goals_path = root / ".ai" / "goals.yaml"
    if not goals_path.exists():
        return []

    data = yaml.safe_load(goals_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        return []

    index: dict[str, dict[str, Any]] = {}
    _index_goals(raw_goals, index)
    completed = index.get(completed_goal_id)
    if completed is None:
        return []
    if str(completed.get("status") or "") != "done":
        return []

    now = datetime.now().astimezone().isoformat()
    events: list[InvalidationEvent] = []

    def mark(goal_id: str, to_status: str, reason_code: str) -> None:
        target = index.get(goal_id)
        if target is None:
            return
        if target is completed:
            return

        from_status = str(target.get("status") or "")
        if from_status not in _ACTIVE_STATUSES:
            return

        state_from = _as_optional_str(target.get("state"))
        target["status"] = to_status
        target["invalidated_by"] = completed_goal_id
        target["invalidation_reason_code"] = reason_code
        target["invalidation_at"] = now
        state_to = _as_optional_str(target.get("state"))
        events.append(
            InvalidationEvent(
                goal_id=goal_id,
                from_status=from_status,
                to_status=to_status,
                reason_code=reason_code,
                invalidated_by=completed_goal_id,
                state_from=state_from,
                state_to=state_to,
            )
        )

    for goal_id in _as_id_list(completed.get("obsoletes")):
        mark(goal_id, "obsolete", "explicit_obsoleted_by_completed_goal")
    for goal_id in _as_id_list(completed.get("supersedes")):
        mark(goal_id, "superseded", "explicit_superseded_by_completed_goal")
    for goal_id in _as_id_list(completed.get("merges")):
        mark(goal_id, "merged_into", "explicit_merged_into_by_completed_goal")

    # Heuristic: if this proposal-derived goal is done, retire same-fingerprint peers.
    fingerprint = str(completed.get("proposal_fingerprint") or "").strip()
    if fingerprint:
        for goal_id, target in sorted(index.items()):
            if goal_id == completed_goal_id:
                continue
            if str(target.get("proposal_fingerprint") or "").strip() != fingerprint:
                continue
            mark(goal_id, "merged_into", "duplicate_proposal_resolved")

    if events:
        goals_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return events


def _index_goals(raw_goals: list[dict[str, Any]], index: dict[str, dict[str, Any]]) -> None:
    for goal in raw_goals:
        if not isinstance(goal, dict):
            continue
        goal_id = goal.get("id")
        if isinstance(goal_id, str) and goal_id.strip():
            index[goal_id.strip()] = goal
        children = goal.get("children")
        if isinstance(children, list):
            _index_goals(children, index)


def _as_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out


def _as_optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
