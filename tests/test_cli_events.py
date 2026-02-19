"""CLI tests for event bus replay command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_events(root: Path) -> None:
    path = root / ".ai" / "events" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-02-15T00:00:01+00:00",
            "event_id": "evt_a",
            "event_type": "auto_attempt",
            "source": "evidence",
            "payload": {"goal_id": "G1", "success": True, "action_taken": "advance"},
        },
        {
            "timestamp": "2026-02-15T00:00:02+00:00",
            "event_id": "evt_b",
            "event_type": "queue_claim_rejected",
            "source": "queue",
            "payload": {"goal_id": "G1", "reason_code": "goal_already_claimed"},
        },
        {
            "timestamp": "2026-02-15T00:00:03+00:00",
            "event_id": "evt_a",
            "event_type": "auto_attempt",
            "source": "evidence",
            "payload": {"goal_id": "G1", "success": True, "action_taken": "advance"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_events_replay_json(monkeypatch, tmp_path: Path) -> None:
    _seed_events(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["events", "replay", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_events"] == 3
    assert payload["unique_events"] == 2
    assert payload["duplicate_events"] == 1
    assert payload["goal_count"] == 1
    assert payload["inbox_items"] == 1
    assert payload["goal_views_path"].endswith(".ai/state/goal_views.yaml")
    assert payload["operator_inbox_path"].endswith(".ai/state/operator_inbox.yaml")


def test_events_replay_no_write(monkeypatch, tmp_path: Path) -> None:
    _seed_events(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["events", "replay", "--no-write"])
    assert result.exit_code == 0
    assert "Event replay complete" in result.output
    assert "Snapshots: skipped (--no-write)" in result.output
