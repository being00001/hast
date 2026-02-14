"""CLI tests for feedback commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from devf.cli import main


def _write_evidence(root: Path, run_id: str) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-02-14T12:00:00+00:00",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 1,
            "success": False,
            "classification": "failed-impl",
            "failure_classification": "impl-defect",
            "action_taken": "retry",
            "model_used": "worker-model",
        },
        {
            "timestamp": "2026-02-14T12:01:00+00:00",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 2,
            "success": False,
            "classification": "failed-impl",
            "failure_classification": "impl-defect",
            "action_taken": "retry",
            "model_used": "worker-model",
        },
        {
            "timestamp": "2026-02-14T12:02:00+00:00",
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 3,
            "success": False,
            "classification": "failed-impl",
            "failure_classification": "impl-defect",
            "action_taken": "retry",
            "model_used": "worker-model",
        },
    ]
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_feedback_note_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "feedback",
            "note",
            "--category",
            "workflow_friction",
            "--impact",
            "medium",
            "--expected",
            "A",
            "--actual",
            "B",
        ],
    )
    assert result.exit_code == 0
    assert "Feedback note recorded:" in result.output


def test_feedback_analyze_and_backlog_commands(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    _write_evidence(tmp_path, "20260214T120000+0000")
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    analyze = runner.invoke(main, ["feedback", "analyze", "--run-id", "20260214T120000+0000"])
    assert analyze.exit_code == 0
    assert "Inferred notes created:" in analyze.output

    backlog = runner.invoke(main, ["feedback", "backlog", "--window", "30", "--promote"])
    assert backlog.exit_code == 0
    assert "Backlog updated:" in backlog.output
    assert "Backlog items:" in backlog.output


def test_feedback_publish_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "feedback").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "feedback" / "backlog.yaml").write_text(
        """
items:
  - feedback_key: k1
    title: "[workflow_friction] retries are too high"
    summary: "Repeated retries needed."
    first_seen: "2026-02-14T10:00:00+00:00"
    last_seen: "2026-02-14T12:00:00+00:00"
    count: 4
    max_impact: high
    avg_confidence: 0.8
    sample_note_ids: [n1, n2]
    status: accepted
    decision_reason: "meets gate"
    recommended_change: "Improve retry context"
    owner: manager
""",
        encoding="utf-8",
    )
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").write_text(
        """
publish:
  enabled: true
  backend: codeberg
  repository: owner/repo
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["feedback", "publish", "--dry-run"])
    assert result.exit_code == 0
    assert "Attempted: 1" in result.output
    assert "Published: 1" in result.output
