"""Feedback note capture and backlog building."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from hast.core.errors import DevfError
from hast.core.feedback_policy import FeedbackPolicy

VALID_CATEGORIES = {
    "ux_gap",
    "missing_feature",
    "waste",
    "error_clarity",
    "workflow_friction",
}
VALID_IMPACTS = {"low", "medium", "high"}
VALID_LANES = {"project", "tool"}
IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


def create_feedback_note(
    *,
    run_id: str | None,
    goal_id: str | None,
    phase: str | None,
    source: str,
    category: str,
    impact: str,
    expected: str,
    actual: str,
    workaround: str,
    confidence: float,
    evidence_ids: list[str] | None = None,
    tool_name: str | None = None,
    lane: str = "project",
) -> dict[str, Any]:
    if category not in VALID_CATEGORIES:
        raise DevfError(f"invalid feedback category: {category}")
    if impact not in VALID_IMPACTS:
        raise DevfError(f"invalid feedback impact: {impact}")
    if not (0.0 <= confidence <= 1.0):
        raise DevfError("feedback confidence must be between 0 and 1")
    if lane not in VALID_LANES:
        raise DevfError(f"invalid feedback lane: {lane}")

    expected_clean = expected.strip()
    actual_clean = actual.strip()
    workaround_clean = workaround.strip()
    if not expected_clean or not actual_clean:
        raise DevfError("feedback expected/actual must be non-empty")

    fingerprint = build_feedback_fingerprint(
        category=category,
        expected=expected_clean,
        actual=actual_clean,
        tool_name=tool_name,
        phase=phase,
        lane=lane,
    )
    ts = datetime.now().astimezone().isoformat()
    note_id = f"note-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%f%z')}-{fingerprint[:8]}"

    return {
        "note_id": note_id,
        "timestamp": ts,
        "run_id": run_id,
        "goal_id": goal_id,
        "phase": phase,
        "source": source,
        "category": category,
        "impact": impact,
        "expected": expected_clean,
        "actual": actual_clean,
        "workaround": workaround_clean,
        "confidence": round(float(confidence), 3),
        "evidence_ids": list(evidence_ids or []),
        "tool_name": tool_name,
        "lane": lane,
        "fingerprint": fingerprint,
    }


def write_feedback_note(root: Path, note: dict[str, Any]) -> None:
    feedback_dir = root / ".ai" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    fp = feedback_dir / "notes.jsonl"
    with fp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False, sort_keys=True) + "\n")


def load_feedback_notes(root: Path, window_days: int | None = None) -> list[dict[str, Any]]:
    fp = root / ".ai" / "feedback" / "notes.jsonl"
    if not fp.exists():
        return []

    threshold: datetime | None = None
    if window_days is not None:
        threshold = datetime.now().astimezone() - timedelta(days=window_days)

    rows: list[dict[str, Any]] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if threshold is not None:
            ts_raw = row.get("timestamp")
            if not isinstance(ts_raw, str):
                continue
            parsed = _parse_iso(ts_raw)
            if parsed is None or parsed < threshold:
                continue
        rows.append(row)
    return rows


def build_feedback_backlog(
    notes: list[dict[str, Any]],
    policy: FeedbackPolicy,
    promote: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        fingerprint = str(note.get("fingerprint") or "")
        if not fingerprint:
            continue
        grouped[fingerprint].append(note)

    items: list[dict[str, Any]] = []
    for fingerprint, bucket in grouped.items():
        count = len(bucket)
        impacts = [str(n.get("impact", "low")) for n in bucket]
        confidences = [float(n.get("confidence", 0.0)) for n in bucket if _is_number(n.get("confidence"))]
        max_impact = _max_impact(impacts)
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        category = str(bucket[0].get("category", "workflow_friction"))
        sample = bucket[0]

        should_promote = (
            count >= policy.promotion.min_frequency
            or max_impact == policy.promotion.auto_promote_impact
        )
        confidence_ok = avg_conf >= policy.promotion.min_confidence

        status = "candidate"
        decision_reason = "awaiting manager review"
        if promote:
            if should_promote and (confidence_ok or max_impact == policy.promotion.auto_promote_impact):
                status = "accepted"
                decision_reason = (
                    f"meets gate (count={count}, max_impact={max_impact}, avg_confidence={avg_conf})"
                )
            else:
                status = "deferred"
                decision_reason = (
                    f"below gate (count={count}, max_impact={max_impact}, avg_confidence={avg_conf})"
                )

        first_seen = _first_timestamp(bucket)
        last_seen = _last_timestamp(bucket)

        items.append(
            {
                "feedback_key": fingerprint,
                "title": f"[{category}] {sample.get('expected', '')[:72]}",
                "summary": sample.get("actual", ""),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "count": count,
                "max_impact": max_impact,
                "avg_confidence": avg_conf,
                "sample_note_ids": [str(n.get("note_id")) for n in bucket[:5] if n.get("note_id")],
                "status": status,
                "decision_reason": decision_reason,
                "recommended_change": _recommended_change(category),
                "owner": "manager",
                "lane": str(sample.get("lane") or "project"),
            }
        )

    items.sort(key=lambda item: (-int(item["count"]), str(item["last_seen"])), reverse=False)
    return items


def save_feedback_backlog(root: Path, items: list[dict[str, Any]]) -> Path:
    feedback_dir = root / ".ai" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    fp = feedback_dir / "backlog.yaml"
    fp.write_text(
        yaml.safe_dump({"items": items}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return fp


def load_feedback_backlog(root: Path) -> list[dict[str, Any]]:
    fp = root / ".ai" / "feedback" / "backlog.yaml"
    if not fp.exists():
        return []
    data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def build_feedback_fingerprint(
    *,
    category: str,
    expected: str,
    actual: str,
    tool_name: str | None,
    phase: str | None,
    lane: str = "project",
) -> str:
    expected_norm = " ".join(expected.lower().split())
    actual_norm = " ".join(actual.lower().split())
    basis = "|".join(
        [
            category,
            expected_norm[:180],
            actual_norm[:180],
            (tool_name or "").strip().lower(),
            (phase or "").strip().lower(),
            lane.strip().lower(),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float))


def _max_impact(impacts: list[str]) -> str:
    chosen = "low"
    for impact in impacts:
        if IMPACT_RANK.get(impact, 0) > IMPACT_RANK.get(chosen, 0):
            chosen = impact
    return chosen


def _first_timestamp(rows: list[dict[str, Any]]) -> str:
    ts_values = sorted(str(row.get("timestamp", "")) for row in rows)
    return ts_values[0] if ts_values else ""


def _last_timestamp(rows: list[dict[str, Any]]) -> str:
    ts_values = sorted(str(row.get("timestamp", "")) for row in rows)
    return ts_values[-1] if ts_values else ""


def _recommended_change(category: str) -> str:
    mapping = {
        "ux_gap": "Improve command UX or defaults.",
        "missing_feature": "Add capability and contract tests.",
        "waste": "Reduce retries/context waste and add guardrails.",
        "error_clarity": "Return structured actionable error messages.",
        "workflow_friction": "Add automation to remove manual workaround.",
    }
    return mapping.get(category, "Review and prioritize with manager triage.")
