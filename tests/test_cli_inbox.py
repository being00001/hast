"""CLI tests for operator inbox commands."""

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
""",
        encoding="utf-8",
    )
    state_dir = root / ".ai" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "operator_inbox.yaml").write_text(
        """
version: v1
items:
  - inbox_id: inbox-1
    event_id: evt-1
    event_type: auto_attempt
    source: evidence
    goal_id: G1
    priority: high
    reason_code: security_failure
    summary: "security escalation"
    timestamp: "2026-02-15T00:00:02+00:00"
""",
        encoding="utf-8",
    )


def test_inbox_list_and_summary_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    listed = runner.invoke(main, ["inbox", "list", "--json"])
    assert listed.exit_code == 0
    listed_payload = json.loads(listed.output)
    assert listed_payload["count"] == 1
    assert listed_payload["items"][0]["inbox_id"] == "inbox-1"

    summary = runner.invoke(main, ["inbox", "summary", "--top-k", "1", "--json"])
    assert summary.exit_code == 0
    summary_payload = json.loads(summary.output)
    assert summary_payload["unresolved_items"] == 1
    assert summary_payload["high_priority_unresolved"] == 1
    assert len(summary_payload["top_items"]) == 1


def test_inbox_act_authorized_and_unauthorized(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    bad = runner.invoke(
        main,
        [
            "inbox",
            "act",
            "inbox-1",
            "--action",
            "reject",
            "--operator",
            "operator-a",
            "--goal-status",
            "done",
        ],
    )
    assert bad.exit_code != 0
    assert "unauthorized transition" in bad.output

    ok = runner.invoke(
        main,
        [
            "inbox",
            "act",
            "inbox-1",
            "--action",
            "reject",
            "--operator",
            "operator-a",
            "--goal-status",
            "blocked",
            "--json",
        ],
    )
    assert ok.exit_code == 0
    payload = json.loads(ok.output)
    assert payload["inbox_id"] == "inbox-1"
    assert payload["action"] == "reject"
    assert payload["goal_status"] == "blocked"
    assert payload["resolved"] is True

