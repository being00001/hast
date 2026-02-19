"""CLI tests for retry recovery command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main
from hast.core.sim import SimCheck, SimReport, SimTestProbe


def _seed_project(root: Path) -> None:
    (root / ".ai" / "attempts" / "G1").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "attempts" / "G1" / "attempt_1.yaml").write_text(
        "attempt: 1\nclassification: failed\nreason: test\ndiff_stat: ''\ntest_output: ''\ndiff: ''\n",
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: "Goal 1"
    status: blocked
""",
        encoding="utf-8",
    )


def test_retry_command_no_run_reactivates_and_clears_attempts(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["retry", "G1", "--no-run"])
    assert result.exit_code == 0
    assert "Goal reactivated: G1" in result.output

    goals_yaml = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "status: active" in goals_yaml
    assert not (tmp_path / ".ai" / "attempts" / "G1").exists()


def test_retry_command_json_runs_auto(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.run_auto", lambda **_kwargs: 0)
    monkeypatch.setattr(
        "hast.core.sim.run_simulation",
        lambda _root, goal_id, run_tests: SimReport(
            root=tmp_path.as_posix(),
            goal_id=goal_id,
            status="risky",
            ready=False,
            risk_score=37,
            checks=[SimCheck(code="preflight", status="warn", message="doctor warnings=1")],
            recommended_actions=["run `hast doctor`"],
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
    result = runner.invoke(main, ["retry", "G1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["goal_id"] == "G1"
    assert payload["reactivated"] is True
    assert payload["attempts_cleared"] is True
    assert payload["ran_auto"] is True
    assert payload["preflight_enabled"] is True
    assert payload["simulation"]["status"] == "risky"
    assert payload["simulation"]["risk_score"] == 37
    assert payload["exit_code"] == 0


def test_retry_command_passes_default_preflight_true(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_auto(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("hast.cli.run_auto", _fake_run_auto)

    runner = CliRunner()
    result = runner.invoke(main, ["retry", "G1", "--json"])
    assert result.exit_code == 0
    assert captured.get("preflight") is True


def test_retry_command_no_sim_sets_null_simulation(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.run_auto", lambda **_kwargs: 0)

    runner = CliRunner()
    result = runner.invoke(main, ["retry", "G1", "--no-sim", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["simulation"] is None


def test_retry_command_no_preflight_bypass(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_auto(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("hast.cli.run_auto", _fake_run_auto)

    runner = CliRunner()
    result = runner.invoke(main, ["retry", "G1", "--no-preflight", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["preflight_enabled"] is False
    assert captured.get("preflight") is False
