"""CLI tests for immune guardrail commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "config.yaml").write_text(
        'test_command: "echo ok"\nai_tool: "echo {prompt}"\n',
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")


def test_immune_grant_command(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "immune",
            "grant",
            "--allow",
            "src/**/*.py",
            "--approved-by",
            "supervisor",
            "--ttl-minutes",
            "45",
        ],
    )
    assert result.exit_code == 0
    assert "Repair grant written:" in result.output
    assert (tmp_path / ".ai" / "immune" / "grant.yaml").exists()


def test_immune_grant_command_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "immune",
            "grant",
            "--allow",
            "src/**/*.py",
            "--approved-by",
            "supervisor",
            "--ttl-minutes",
            "45",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["approved_by"] == "supervisor"
    assert payload["ttl_minutes"] == 45
