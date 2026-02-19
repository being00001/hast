"""CLI tests for sim command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main
from hast.core.sim import SimCheck, SimReport, SimTestProbe


def test_sim_command_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(
        "hast.core.sim.run_simulation",
        lambda _root, goal_id, run_tests: SimReport(
            root=tmp_path.as_posix(),
            goal_id=goal_id or "G1",
            status="risky",
            ready=False,
            risk_score=42,
            checks=[SimCheck(code="preflight", status="warn", message="doctor warnings=1")],
            recommended_actions=["run `hast doctor` and resolve blockers before `hast auto`"],
            recent_attempts=[],
            test_probe=SimTestProbe(
                ran=run_tests,
                passed=None,
                exit_code=None,
                command="pytest -q",
                summary="skipped",
            ),
        ),
    )

    runner = CliRunner()
    result = runner.invoke(main, ["sim", "G1", "--run-tests", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["goal_id"] == "G1"
    assert payload["status"] == "risky"
    assert payload["risk_score"] == 42
    assert payload["test_probe"]["ran"] is True


def test_sim_command_plain(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(
        "hast.core.sim.run_simulation",
        lambda _root, goal_id, run_tests: SimReport(
            root=tmp_path.as_posix(),
            goal_id=goal_id or "G1",
            status="blocked",
            ready=False,
            risk_score=91,
            checks=[SimCheck(code="preflight", status="fail", message="doctor preflight blockers=2")],
            recommended_actions=["run `hast doctor` and resolve blockers before `hast auto`"],
            recent_attempts=[],
            test_probe=SimTestProbe(
                ran=run_tests,
                passed=None,
                exit_code=None,
                command=None,
                summary=None,
            ),
        ),
    )

    runner = CliRunner()
    result = runner.invoke(main, ["sim", "G1"])
    assert result.exit_code == 0
    assert "hast sim" in result.output
    assert "status: blocked" in result.output
