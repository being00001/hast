"""Tests for ProtocolRunner auto roundtrip flow."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from hast.core.config import Config
from hast.core.goals import Goal
from hast.core.runners.protocol import ProtocolRunner


def _seed_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    phase: implement
""",
        encoding="utf-8",
    )


def _seed_policy(root: Path, *, max_wait_seconds: int = 30) -> None:
    policies_dir = root / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "protocol_adapter_policy.yaml").write_text(
        f"""
version: v1
enabled_adapters: [langgraph, openhands]
default_export_context_format: pack
include_context_by_default: false
include_prompt_by_default: true
max_context_chars: 200000
require_goal_exists: true
result_inbox_dir: ".ai/protocols/inbox"
processed_results_dir: ".ai/protocols/processed"
poll_interval_seconds: 1
max_wait_seconds: {max_wait_seconds}
require_packet_id_match: true
archive_consumed_packets: true
""",
        encoding="utf-8",
    )


def test_protocol_runner_success_roundtrip(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _seed_policy(tmp_path, max_wait_seconds=30)
    config = Config(test_command="true", ai_tool="echo {prompt}")
    goal = Goal(id="G1", title="Goal 1", status="active", phase="implement")

    def _external_worker() -> None:
        outbox_dir = tmp_path / ".ai" / "protocols" / "outbox"
        deadline = time.time() + 3
        task_path: Path | None = None
        while time.time() < deadline:
            files = sorted(outbox_dir.glob("*.json"))
            if files:
                task_path = files[0]
                break
            time.sleep(0.01)
        assert task_path is not None, "task packet was not exported"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        inbox_dir = tmp_path / ".ai" / "protocols" / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        result_packet = {
            "schema_version": "protocol_result.v1",
            "adapter": task["adapter"],
            "packet_id": task["packet_id"],
            "goal_id": task["goal"]["goal_id"],
            "run_id": task["run_id"],
            "phase": "implement",
            "attempt": 1,
            "success": True,
            "classification": "complete",
            "action_taken": "advance",
            "summary": "external execution done",
        }
        (inbox_dir / "result_packet.json").write_text(
            json.dumps(result_packet, ensure_ascii=False),
            encoding="utf-8",
        )

    thread = threading.Thread(target=_external_worker, daemon=True)
    thread.start()
    runner = ProtocolRunner()
    result = runner.run(tmp_path, config, goal, "implement goal", tool_name="langgraph")
    thread.join(timeout=2)

    assert result.success is True
    assert result.model_used == "external:langgraph"
    assert result.output
    out = json.loads(result.output)
    assert out["adapter"] == "langgraph"
    assert out["goal_id"] == "G1"
    assert out["ingested_run_id"]
    assert out["archived_result_packet_path"] is not None


def test_protocol_runner_timeout_returns_failure(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    _seed_policy(tmp_path, max_wait_seconds=1)
    config = Config(test_command="true", ai_tool="echo {prompt}")
    goal = Goal(id="G1", title="Goal 1", status="active", phase="implement")

    runner = ProtocolRunner()
    result = runner.run(tmp_path, config, goal, "implement goal", tool_name="langgraph")
    assert result.success is False
    assert result.error_message is not None
    assert "protocol result timeout" in result.error_message
