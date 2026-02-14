"""CLI tests for orchestrate command."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

from click.testing import CliRunner

from devf.cli import main


def _write_evidence(root: Path, run_id: str) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-02-14T23:00:00+00:00",
            "run_id": run_id,
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
            "timestamp": "2026-02-14T23:01:00+00:00",
            "run_id": run_id,
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
            "timestamp": "2026-02-14T23:02:00+00:00",
            "run_id": run_id,
            "goal_id": "G1",
            "phase": "implement",
            "attempt": 3,
            "success": False,
            "classification": "no-progress",
            "failure_classification": "impl-defect",
            "action_taken": "retry",
            "model_used": "worker-model",
        },
    ]
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_orchestrate_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v1
            enabled: true
            promotion:
              min_frequency: 1
              min_confidence: 0.5
              auto_promote_impact: high
            dedup:
              strategy: fingerprint_v1
            publish:
              enabled: false
              backend: codeberg
              repository: ""
              token_env: CODEBERG_TOKEN
              base_url: https://codeberg.org
              labels: [bot-reported, devf-feedback]
              min_status: accepted
            """
        ),
        encoding="utf-8",
    )
    _write_evidence(tmp_path, "20260214T230000+0000")

    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "orchestrate",
            "--run-id",
            "20260214T230000+0000",
            "--window",
            "30",
            "--max-goals",
            "2",
        ],
    )
    assert result.exit_code == 0
    assert "Orchestration complete" in result.output
    assert "Goals added:" in result.output

    goals_text = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "id: PX_2X" in goals_text
