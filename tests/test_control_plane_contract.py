"""Tests for control-plane contract validation."""

from __future__ import annotations

import json

from hast.core.control_plane_contract import (
    CONTROL_PLANE_CONTRACT_VERSION,
    validate_evidence_row,
)
from hast.core.evidence import write_evidence_row


def test_validate_evidence_row_normalizes_defaults() -> None:
    result = validate_evidence_row(
        {
            "timestamp": "2026-02-15T00:00:00+00:00",
            "run_id": "20260215T000000+0000",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 1,
            "success": True,
            "should_retry": False,
            "classification": "complete",
            "action_taken": "advance",
            "failure_classification": None,
        }
    )
    assert result.warnings == []
    assert result.normalized_row["event_type"] == "auto_attempt"
    assert result.normalized_row["contract_version"] == CONTROL_PLANE_CONTRACT_VERSION


def test_validate_evidence_row_warns_on_invalid_action_semantics() -> None:
    result = validate_evidence_row(
        {
            "timestamp": "2026-02-15T00:00:00+00:00",
            "run_id": "20260215T000000+0000",
            "goal_id": "G1",
            "phase": "gate",
            "attempt": 1,
            "success": True,
            "should_retry": False,
            "classification": "gate-pass",
            "action_taken": "block",
            "failure_classification": None,
        }
    )
    assert any("success rows must use action_taken=advance" in w for w in result.warnings)


def test_validate_evidence_row_requires_failure_class_on_non_advance() -> None:
    result = validate_evidence_row(
        {
            "timestamp": "2026-02-15T00:00:00+00:00",
            "run_id": "20260215T000000+0000",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 1,
            "success": False,
            "should_retry": False,
            "classification": "failed",
            "action_taken": "block",
            "failure_classification": None,
        }
    )
    assert "non-advance action requires failure_classification" in result.warnings


def test_write_evidence_row_embeds_contract_metadata(tmp_path: Path) -> None:
    write_evidence_row(
        tmp_path,
        "20260215T000000+0000",
        {
            "timestamp": "2026-02-15T00:00:00+00:00",
            "run_id": "20260215T000000+0000",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 1,
            "success": False,
            "should_retry": False,
            "classification": "failed",
            "action_taken": "block",
            "failure_classification": None,
        },
    )
    fp = tmp_path / ".ai" / "runs" / "20260215T000000+0000" / "evidence.jsonl"
    row = json.loads(fp.read_text(encoding="utf-8").splitlines()[-1])
    assert row["contract_version"] == CONTROL_PLANE_CONTRACT_VERSION
    assert row["event_type"] == "auto_attempt"
    assert "contract_warnings" in row
