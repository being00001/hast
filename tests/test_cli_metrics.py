"""CLI tests for metrics command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _write_evidence(root: Path) -> None:
    run_dir = root / ".ai" / "runs" / "20260214T120000+0000"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-02-14T12:00:00+00:00",
            "goal_id": "G1",
            "attempt": 1,
            "classification": "complete",
            "success": True,
            "action_taken": "advance",
            "risk_score": 20,
        },
        {
            "timestamp": "2026-02-14T12:01:00+00:00",
            "goal_id": "G1",
            "attempt": 2,
            "classification": "failed-impl",
            "success": False,
            "action_taken": "retry",
            "failure_classification": "impl-defect",
            "risk_score": 40,
        },
    ]
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
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
                        "timestamp": "2026-02-14T12:01:00+00:00",
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
""",
        encoding="utf-8",
    )


def test_metrics_command(monkeypatch, tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    _write_proposals(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["metrics", "--window", "30"])
    assert result.exit_code == 0
    assert "Window: last 30 day(s)" in result.output
    assert "Evidence rows: 2" in result.output
    assert "Feedback backlog published:" in result.output
    assert "Proposal notes: 2" in result.output
    assert "Proposal backlog accepted: 1" in result.output
    assert "Proposal promoted goals: 1" in result.output
    assert "Failure classifications:" in result.output


def test_triage_command(monkeypatch, tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["triage", "--run-id", "20260214T120000+0000"])
    assert result.exit_code == 0
    assert "G1 phase=None attempt=1" in result.output
    assert "action=retry" in result.output


def test_metrics_command_json(monkeypatch, tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    _write_proposals(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["metrics", "--window", "30", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["window_days"] == 30
    assert payload["report"]["total_rows"] == 2


def test_triage_command_json(monkeypatch, tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["triage", "--run-id", "20260214T120000+0000", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run_id"] == "20260214T120000+0000"
    assert len(payload["rows"]) == 2
