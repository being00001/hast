"""Tests for evidence metrics aggregation."""

from __future__ import annotations

import json
from pathlib import Path

from hast.core.metrics import build_metrics_report, build_triage_report


def _write_evidence(root: Path, run_id: str, rows: list[dict]) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fp = run_dir / "evidence.jsonl"
    fp.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_proposals(root: Path) -> None:
    proposals_dir = root / ".ai" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "notes.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "proposal_id": "p1",
                        "timestamp": "2026-02-14T12:00:00+00:00",
                        "status": "proposed",
                        "fingerprint": "fp1",
                    }
                ),
                json.dumps(
                    {
                        "proposal_id": "p2",
                        "timestamp": "2026-02-14T12:05:00+00:00",
                        "status": "proposed",
                        "fingerprint": "fp2",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (proposals_dir / "backlog.yaml").write_text(
        """
generated_at: "2026-02-14T12:10:00+00:00"
items:
  - proposal_id: p1
    status: accepted
    promoted_goal_id: PX_2X.1
  - proposal_id: p2
    status: deferred
  - proposal_id: p3
    status: rejected
""",
        encoding="utf-8",
    )


def test_metrics_report_aggregates_rows(tmp_path: Path) -> None:
    _write_evidence(
        tmp_path,
        "20260214T120000+0000",
        [
            {
                "timestamp": "2026-02-14T12:00:00+00:00",
                "goal_id": "G1",
                "success": True,
                "action_taken": "advance",
                "risk_score": 30,
            },
            {
                "timestamp": "2026-02-14T12:01:00+00:00",
                "goal_id": "G1",
                "success": False,
                "action_taken": "retry",
                "failure_classification": "impl-defect",
                "risk_score": 50,
            },
            {
                "timestamp": "2026-02-14T12:02:00+00:00",
                "goal_id": "G2",
                "success": False,
                "action_taken": "block",
                "failure_classification": "security",
                "risk_score": 90,
            },
        ],
    )
    _write_proposals(tmp_path)
    report = build_metrics_report(tmp_path, window_days=7)
    assert report.total_rows == 3
    assert report.goals_seen == 2
    assert report.success_rows == 1
    assert report.failure_rows == 2
    assert report.action_counts["advance"] == 1
    assert report.action_counts["retry"] == 1
    assert report.failure_class_counts["impl-defect"] == 1
    assert report.avg_risk_score == 56.67
    assert report.feedback_notes == 0
    assert report.feedback_accepted == 0
    assert report.feedback_candidates == 0
    assert report.feedback_published == 0
    assert report.proposal_notes == 2
    assert report.proposal_backlog_total == 3
    assert report.proposal_accepted == 1
    assert report.proposal_deferred == 1
    assert report.proposal_rejected == 1
    assert report.proposal_promoted == 1
    assert report.proposal_accept_ratio == 0.333


def test_build_triage_report(tmp_path: Path) -> None:
    _write_evidence(
        tmp_path,
        "20260214T130000+0000",
        [
            {
                "timestamp": "2026-02-14T13:00:00+00:00",
                "goal_id": "G3",
                "phase": "legacy",
                "attempt": 2,
                "classification": "failed-impl",
                "failure_classification": "impl-defect",
                "action_taken": "retry",
                "reason": "assert mismatch",
            },
        ],
    )
    rows = build_triage_report(tmp_path, "20260214T130000+0000")
    assert len(rows) == 1
    assert rows[0].goal_id == "G3"
    assert rows[0].action_taken == "retry"
