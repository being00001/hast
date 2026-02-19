"""Evidence-based metrics aggregation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path

from hast.core.feedback import load_feedback_backlog, load_feedback_notes
from hast.core.proposals import load_proposal_backlog, load_proposal_notes


@dataclass(frozen=True)
class MetricsReport:
    total_rows: int
    goals_seen: int
    success_rows: int
    failure_rows: int
    action_counts: dict[str, int]
    failure_class_counts: dict[str, int]
    avg_risk_score: float
    feedback_notes: int
    feedback_candidates: int
    feedback_accepted: int
    feedback_published: int
    proposal_notes: int
    proposal_backlog_total: int
    proposal_accepted: int
    proposal_deferred: int
    proposal_rejected: int
    proposal_promoted: int
    proposal_accept_ratio: float


@dataclass(frozen=True)
class TriageRow:
    goal_id: str
    phase: str | None
    attempt: int
    classification: str
    failure_classification: str | None
    action_taken: str | None
    reason: str | None


def build_metrics_report(root: Path, window_days: int) -> MetricsReport:
    rows = _load_recent_rows(root, window_days)
    total_rows = len(rows)
    goals = {str(row.get("goal_id")) for row in rows if row.get("goal_id")}
    success_rows = sum(1 for row in rows if bool(row.get("success")))
    failure_rows = total_rows - success_rows

    action_counts = Counter(
        str(row.get("action_taken")) for row in rows if row.get("action_taken") is not None
    )
    failure_class_counts = Counter(
        str(row.get("failure_classification"))
        for row in rows
        if row.get("failure_classification") is not None
    )

    risk_values = [int(row["risk_score"]) for row in rows if isinstance(row.get("risk_score"), int)]
    avg_risk_score = (sum(risk_values) / len(risk_values)) if risk_values else 0.0
    feedback_notes = len(load_feedback_notes(root, window_days=window_days))
    backlog = load_feedback_backlog(root)
    feedback_candidates = sum(1 for item in backlog if item.get("status") == "candidate")
    feedback_accepted = sum(1 for item in backlog if item.get("status") == "accepted")
    feedback_published = sum(1 for item in backlog if item.get("published_issue_url"))
    proposal_notes = len(load_proposal_notes(root, window_days=window_days))
    proposal_backlog = load_proposal_backlog(root)
    proposal_backlog_total = len(proposal_backlog)
    proposal_accepted = sum(1 for item in proposal_backlog if item.get("status") == "accepted")
    proposal_deferred = sum(1 for item in proposal_backlog if item.get("status") == "deferred")
    proposal_rejected = sum(1 for item in proposal_backlog if item.get("status") == "rejected")
    proposal_promoted = sum(
        1
        for item in proposal_backlog
        if item.get("status") == "accepted" and item.get("promoted_goal_id")
    )
    proposal_accept_ratio = (
        proposal_accepted / proposal_backlog_total if proposal_backlog_total > 0 else 0.0
    )

    return MetricsReport(
        total_rows=total_rows,
        goals_seen=len(goals),
        success_rows=success_rows,
        failure_rows=failure_rows,
        action_counts=dict(action_counts),
        failure_class_counts=dict(failure_class_counts),
        avg_risk_score=round(avg_risk_score, 2),
        feedback_notes=feedback_notes,
        feedback_candidates=feedback_candidates,
        feedback_accepted=feedback_accepted,
        feedback_published=feedback_published,
        proposal_notes=proposal_notes,
        proposal_backlog_total=proposal_backlog_total,
        proposal_accepted=proposal_accepted,
        proposal_deferred=proposal_deferred,
        proposal_rejected=proposal_rejected,
        proposal_promoted=proposal_promoted,
        proposal_accept_ratio=round(proposal_accept_ratio, 3),
    )


def build_triage_report(root: Path, run_id: str) -> list[TriageRow]:
    fp = root / ".ai" / "runs" / run_id / "evidence.jsonl"
    if not fp.exists():
        return []
    rows: list[TriageRow] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(
            TriageRow(
                goal_id=str(data.get("goal_id", "")),
                phase=data.get("phase"),
                attempt=int(data.get("attempt", 0)),
                classification=str(data.get("classification", "")),
                failure_classification=data.get("failure_classification"),
                action_taken=data.get("action_taken"),
                reason=data.get("reason"),
            )
        )
    return rows


def _load_recent_rows(root: Path, window_days: int) -> list[dict]:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return []

    threshold = datetime.now().astimezone() - timedelta(days=window_days)
    rows: list[dict] = []
    for evidence_file in sorted(runs_dir.glob("*/evidence.jsonl")):
        for line in evidence_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = row.get("timestamp")
            if not isinstance(timestamp, str):
                continue
            parsed = _parse_iso(timestamp)
            if parsed is None or parsed < threshold:
                continue
            rows.append(row)
    return rows


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
