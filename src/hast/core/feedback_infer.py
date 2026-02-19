"""Evidence-driven feedback note inference."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from hast.core.evidence import hash_text
from hast.core.feedback import create_feedback_note, load_feedback_notes, write_feedback_note
from hast.core.feedback_policy import FeedbackPolicy


def infer_and_store_feedback_notes(
    root: Path,
    run_id: str,
    policy: FeedbackPolicy,
    goal_id: str | None = None,
) -> list[dict[str, Any]]:
    if not policy.enabled:
        return []

    rows = _load_run_evidence_rows(root, run_id)
    if goal_id:
        rows = [row for row in rows if row.get("goal_id") == goal_id]
    if not rows:
        return []

    inferred = infer_feedback_notes_from_rows(rows, run_id)
    if not inferred:
        return []

    existing = load_feedback_notes(root)
    seen = {
        (
            str(note.get("run_id") or ""),
            str(note.get("goal_id") or ""),
            str(note.get("source") or ""),
            str(note.get("fingerprint") or ""),
        )
        for note in existing
    }

    created: list[dict[str, Any]] = []
    for note in inferred:
        key = (
            str(note.get("run_id") or ""),
            str(note.get("goal_id") or ""),
            str(note.get("source") or ""),
            str(note.get("fingerprint") or ""),
        )
        if key in seen:
            continue
        write_feedback_note(root, note)
        created.append(note)
        seen.add(key)

    return created


def infer_feedback_notes_from_rows(rows: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    notes.extend(_infer_repeated_failures(rows, run_id))
    notes.extend(_infer_no_progress_waste(rows, run_id))
    notes.extend(_infer_retry_then_success(rows, run_id))
    notes.extend(_infer_error_clarity(rows, run_id))
    return notes


def _infer_repeated_failures(rows: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("success"):
            continue
        failure_class = row.get("failure_classification")
        if not isinstance(failure_class, str) or not failure_class:
            continue
        key = (
            str(row.get("goal_id") or ""),
            failure_class,
            str(row.get("phase") or ""),
            str(row.get("model_used") or ""),
        )
        groups[key].append(row)

    notes: list[dict[str, Any]] = []
    for (goal, failure_class, phase, model), bucket in groups.items():
        if len(bucket) < 3:
            continue
        impact = "high" if failure_class in {"security", "dep-build"} else "medium"
        confidence = min(0.9, 0.5 + (len(bucket) * 0.08))
        notes.append(
            create_feedback_note(
                run_id=run_id,
                goal_id=goal or None,
                phase=phase or None,
                source="inferred",
                category="workflow_friction",
                impact=impact,
                expected="The loop should self-correct repeated failures within two retries.",
                actual=(
                    f"Failure class '{failure_class}' repeated {len(bucket)} times "
                    f"(phase={phase or 'n/a'}, model={model or 'n/a'})."
                ),
                workaround="Manual triage/prompt rewrite was needed to continue.",
                confidence=confidence,
                evidence_ids=[_row_id(row) for row in bucket[:10]],
                tool_name=model or None,
            )
        )
    return notes


def _infer_no_progress_waste(rows: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        goal = str(row.get("goal_id") or "")
        if goal:
            by_goal[goal].append(row)

    notes: list[dict[str, Any]] = []
    for goal, bucket in by_goal.items():
        if len(bucket) < 3:
            continue
        no_progress = sum(1 for row in bucket if row.get("classification") == "no-progress")
        ratio = no_progress / len(bucket)
        if ratio < 0.4:
            continue
        impact = "high" if ratio >= 0.7 else "medium"
        confidence = min(0.9, 0.6 + ratio * 0.3)
        notes.append(
            create_feedback_note(
                run_id=run_id,
                goal_id=goal,
                phase=None,
                source="inferred",
                category="waste",
                impact=impact,
                expected="Attempts should produce concrete code progress most of the time.",
                actual=(
                    f"No-progress ratio reached {ratio:.0%} "
                    f"({no_progress}/{len(bucket)} attempts) for goal {goal}."
                ),
                workaround="Operator intervention required to reset context and constraints.",
                confidence=confidence,
                evidence_ids=[_row_id(row) for row in bucket[:10]],
                tool_name=None,
            )
        )
    return notes


def _infer_retry_then_success(rows: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    by_goal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        goal = str(row.get("goal_id") or "")
        if goal:
            by_goal[goal].append(row)

    notes: list[dict[str, Any]] = []
    for goal, bucket in by_goal.items():
        had_retry = any(row.get("action_taken") == "retry" for row in bucket)
        had_success = any(bool(row.get("success")) for row in bucket)
        if not (had_retry and had_success):
            continue
        notes.append(
            create_feedback_note(
                run_id=run_id,
                goal_id=goal,
                phase=None,
                source="inferred",
                category="workflow_friction",
                impact="medium",
                expected="Successful completion should not require repeated retry cycles.",
                actual="Goal required retries before eventual success, implying recoverability friction.",
                workaround="Manual workaround or prompt adjustment likely required between retries.",
                confidence=0.65,
                evidence_ids=[_row_id(row) for row in bucket[:10]],
                tool_name=None,
            )
        )
    return notes


def _infer_error_clarity(rows: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    unclear: list[dict[str, Any]] = []
    for row in rows:
        if row.get("success"):
            continue
        reason = str(row.get("reason") or "")
        preview = str(row.get("test_output_preview") or "")
        failure_class = row.get("failure_classification")
        if len(reason.strip()) >= 28:
            continue
        if len(preview.strip()) >= 20:
            continue
        if failure_class:
            continue
        unclear.append(row)

    if len(unclear) < 2:
        return []

    return [
        create_feedback_note(
            run_id=run_id,
            goal_id=None,
            phase=None,
            source="inferred",
            category="error_clarity",
            impact="medium",
            expected="Failure outputs should include actionable root-cause hints.",
            actual=f"{len(unclear)} failures had short/ambiguous reasons without clear hints.",
            workaround="Manual log digging required to classify and recover.",
            confidence=0.7,
            evidence_ids=[_row_id(row) for row in unclear[:10]],
            tool_name=None,
        )
    ]


def _load_run_evidence_rows(root: Path, run_id: str) -> list[dict[str, Any]]:
    fp = root / ".ai" / "runs" / run_id / "evidence.jsonl"
    if not fp.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_id(row: dict[str, Any]) -> str:
    key = {
        "timestamp": row.get("timestamp"),
        "goal_id": row.get("goal_id"),
        "phase": row.get("phase"),
        "attempt": row.get("attempt"),
        "classification": row.get("classification"),
        "failure_classification": row.get("failure_classification"),
    }
    return hash_text(json.dumps(key, sort_keys=True, ensure_ascii=False))[:16]
