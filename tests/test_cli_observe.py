"""CLI tests for observability baseline command."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _ts(minutes_ago: int) -> str:
    base = datetime.now().astimezone()
    return (base - timedelta(minutes=minutes_ago)).isoformat()


def _seed_data(root: Path) -> None:
    (root / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "policies" / "observability_policy.yaml").write_text(
        """
version: v1
thresholds:
  min_goal_runs: 1
  first_pass_success_rate_min: 0.0
  block_rate_max: 1.0
  security_incident_rate_max: 1.0
  claim_collision_rate_max: 1.0
  mttr_minutes_max: 999
""",
        encoding="utf-8",
    )
    run_dir = root / ".ai" / "runs" / "RUN_1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        json.dumps(
            {
                "timestamp": _ts(10),
                "run_id": "RUN_1",
                "goal_id": "G1",
                "attempt": 1,
                "success": True,
                "action_taken": "advance",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_observe_baseline_json(monkeypatch, tmp_path: Path) -> None:
    _seed_data(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["observe", "baseline", "--window", "7", "--no-write", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["window_days"] == 7
    assert payload["baseline"]["goal_runs"] == 1
    assert payload["baseline"]["baseline_ready"] is True
    assert payload["report_path"] is None


def test_observe_baseline_writes_report(monkeypatch, tmp_path: Path) -> None:
    _seed_data(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["observe", "baseline"])
    assert result.exit_code == 0
    assert "Observability baseline" in result.output

    report_path = tmp_path / ".ai" / "reports" / "observability_baseline.json"
    assert report_path.exists()
