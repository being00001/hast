"""CLI tests for protocol adapter commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


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


def test_protocol_export_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "protocol",
            "export",
            "--adapter",
            "langgraph",
            "--goal",
            "G1",
            "--role",
            "implement",
            "--no-include-context",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["packet"]["adapter"] == "langgraph"
    assert payload["packet"]["goal"]["goal_id"] == "G1"
    assert payload["packet"]["execution"]["role"] == "implement"
    assert payload["packet_path"].endswith(".json")


def test_protocol_ingest_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    result_packet = tmp_path / "result_packet.json"
    result_packet.write_text(
        json.dumps(
            {
                "schema_version": "protocol_result.v1",
                "adapter": "openhands",
                "goal_id": "G1",
                "run_id": "20260215T230000+0000",
                "success": True,
                "classification": "complete",
                "action_taken": "advance",
                "phase": "implement",
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(main, ["protocol", "ingest", str(result_packet), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["adapter"] == "openhands"
    assert payload["goal_id"] == "G1"
    assert payload["run_id"] == "20260215T230000+0000"
    assert payload["evidence_path"].endswith("/.ai/runs/20260215T230000+0000/evidence.jsonl")

