"""Tests for protocol adapter bridge helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hast.core.errors import HastError
from hast.core.protocol_adapters import export_protocol_task_packet, ingest_protocol_result_packet


def _seed_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    phase: implement
    allowed_changes: ["src/app.py"]
    test_files: ["tests/test_app.py"]
""",
        encoding="utf-8",
    )


def _enable_event_bus(root: Path) -> None:
    policies_dir = root / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "event_bus_policy.yaml").write_text(
        """
version: v1
enabled: true
shadow_mode: true
emit_from_evidence: true
emit_from_queue: true
emit_from_orchestrator: true
auto_reduce_on_emit: false
""",
        encoding="utf-8",
    )


def test_export_protocol_task_packet_writes_outbox(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    result = export_protocol_task_packet(
        tmp_path,
        adapter="langgraph",
        goal_id="G1",
        role="implement",
        include_context=False,
        write_file=True,
    )
    assert result.packet["schema_version"] == "protocol_task.v1"
    assert result.packet["adapter"] == "langgraph"
    assert result.packet["goal"]["goal_id"] == "G1"
    assert result.packet["execution"]["role"] == "implement"
    assert result.packet["context"]["included"] is False
    assert result.packet_path is not None
    assert result.packet_path.exists()


def test_export_protocol_task_packet_rejects_disabled_adapter(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    policies_dir = tmp_path / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "protocol_adapter_policy.yaml").write_text(
        """
version: v1
enabled_adapters: [openhands]
default_export_context_format: pack
include_context_by_default: false
max_context_chars: 200000
require_goal_exists: true
""",
        encoding="utf-8",
    )

    with pytest.raises(HastError, match="adapter disabled by policy"):
        export_protocol_task_packet(
            tmp_path,
            adapter="langgraph",
            goal_id="G1",
            include_context=False,
            write_file=False,
        )


def test_ingest_protocol_result_packet_writes_evidence_and_inbox(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _enable_event_bus(tmp_path)
    result = ingest_protocol_result_packet(
        tmp_path,
        {
            "schema_version": "protocol_result.v1",
            "adapter": "openhands",
            "goal_id": "G1",
            "run_id": "20260215T220000+0000",
            "phase": "implement",
            "attempt": 1,
            "success": False,
            "classification": "failed-external",
            "action_taken": "retry",
            "failure_classification": "impl-defect",
            "summary": "needs another attempt",
        },
    )
    assert result.goal_id == "G1"
    assert result.adapter == "openhands"
    assert result.evidence_path.exists()
    evidence_rows = [
        json.loads(line)
        for line in result.evidence_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert evidence_rows[-1]["goal_id"] == "G1"
    assert evidence_rows[-1]["action_taken"] == "retry"
    assert result.inbox_path.exists()
    inbox_rows = [
        json.loads(line)
        for line in result.inbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert inbox_rows[-1]["adapter"] == "openhands"
    assert result.event_id is not None


def test_ingest_protocol_result_packet_rejects_unknown_goal(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    with pytest.raises(HastError, match="goal not found for result packet"):
        ingest_protocol_result_packet(
            tmp_path,
            {
                "schema_version": "protocol_result.v1",
                "adapter": "langgraph",
                "goal_id": "G_UNKNOWN",
                "success": True,
                "classification": "complete",
                "action_taken": "advance",
            },
        )

