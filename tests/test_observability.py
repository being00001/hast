"""Tests for observability baseline aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from hast.core.observability import build_observability_baseline

BASE_NOW = datetime.now().astimezone()


def _write_evidence(root: Path, run_id: str, rows: list[dict]) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_queue_events(root: Path, rows: list[dict]) -> None:
    queue_dir = root / ".ai" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _ts(minutes_ago: int) -> str:
    return (BASE_NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_build_observability_baseline_ready(tmp_path: Path) -> None:
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "observability_policy.yaml").write_text(
        """
version: v1
thresholds:
  min_goal_runs: 3
  first_pass_success_rate_min: 0.3
  block_rate_max: 0.5
  security_incident_rate_max: 0.5
  claim_collision_rate_max: 0.5
  mttr_minutes_max: 30
""",
        encoding="utf-8",
    )

    _write_evidence(
        tmp_path,
        "RUN_1",
        [
            {
                "timestamp": _ts(90),
                "run_id": "RUN_1",
                "goal_id": "G1",
                "attempt": 1,
                "success": True,
                "action_taken": "advance",
            }
        ],
    )
    _write_evidence(
        tmp_path,
        "RUN_2",
        [
            {
                "timestamp": _ts(70),
                "run_id": "RUN_2",
                "goal_id": "G2",
                "attempt": 1,
                "success": False,
                "action_taken": "retry",
                "failure_classification": "impl-defect",
            },
            {
                "timestamp": _ts(60),
                "run_id": "RUN_2",
                "goal_id": "G2",
                "attempt": 2,
                "success": True,
                "action_taken": "advance",
            },
        ],
    )
    _write_evidence(
        tmp_path,
        "RUN_3",
        [
            {
                "timestamp": _ts(50),
                "run_id": "RUN_3",
                "goal_id": "G3",
                "attempt": 1,
                "success": False,
                "action_taken": "block",
                "failure_classification": "security",
            }
        ],
    )
    _write_queue_events(
        tmp_path,
        [
            {"timestamp": _ts(40), "event_type": "claim_created", "claim_id": "c1"},
            {"timestamp": _ts(39), "event_type": "claim_created", "claim_id": "c2"},
            {"timestamp": _ts(38), "event_type": "claim_created", "claim_id": "c3"},
            {
                "timestamp": _ts(37),
                "event_type": "claim_rejected",
                "reason_code": "goal_already_claimed",
            },
            {"timestamp": _ts(36), "event_type": "idempotent_claim_reused", "claim_id": "c2"},
            {"timestamp": _ts(35), "event_type": "claim_expired", "claim_id": "c1"},
        ],
    )

    report = build_observability_baseline(tmp_path, window_days=7)
    assert report.goal_runs == 3
    assert report.success_rate == 0.667
    assert report.first_pass_success_rate == 0.333
    assert report.retry_rate == 0.333
    assert report.block_rate == 0.333
    assert report.security_incident_rate == 0.333
    assert report.mean_attempts_to_success == 1.5
    assert report.mttr_minutes is not None
    assert abs(report.mttr_minutes - 10.0) < 0.05
    assert report.claim_attempts == 4
    assert report.claim_collision_rate == 0.25
    assert report.idempotent_reuse_rate == 0.25
    assert report.stale_lease_recovery_count == 1
    assert report.baseline_ready is True
    assert report.failing_guards == []


def test_build_observability_baseline_failing_guards(tmp_path: Path) -> None:
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "observability_policy.yaml").write_text(
        """
version: v1
thresholds:
  min_goal_runs: 2
  first_pass_success_rate_min: 0.9
  block_rate_max: 0.1
  security_incident_rate_max: 0.0
  claim_collision_rate_max: 0.0
  mttr_minutes_max: 1
""",
        encoding="utf-8",
    )
    _write_evidence(
        tmp_path,
        "RUN_1",
        [
            {
                "timestamp": _ts(20),
                "run_id": "RUN_1",
                "goal_id": "G1",
                "attempt": 1,
                "success": False,
                "action_taken": "block",
                "failure_classification": "security",
            }
        ],
    )
    _write_evidence(
        tmp_path,
        "RUN_2",
        [
            {
                "timestamp": _ts(18),
                "run_id": "RUN_2",
                "goal_id": "G2",
                "attempt": 1,
                "success": False,
                "action_taken": "retry",
                "failure_classification": "impl-defect",
            },
            {
                "timestamp": _ts(10),
                "run_id": "RUN_2",
                "goal_id": "G2",
                "attempt": 2,
                "success": True,
                "action_taken": "advance",
            },
        ],
    )
    _write_queue_events(
        tmp_path,
        [
            {"timestamp": _ts(9), "event_type": "claim_created"},
            {"timestamp": _ts(8), "event_type": "claim_rejected", "reason_code": "goal_already_claimed"},
        ],
    )

    report = build_observability_baseline(tmp_path, window_days=7)
    assert report.baseline_ready is False
    assert report.failing_guards
    assert any("first_pass_success_rate" in item for item in report.failing_guards)
    assert any("block_rate" in item for item in report.failing_guards)
    assert any("security_incident_rate" in item for item in report.failing_guards)
    assert any("claim_collision_rate" in item for item in report.failing_guards)
    assert any("mttr_minutes" in item for item in report.failing_guards)
