"""CLI tests for explore command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_explore_project(root: Path) -> None:
    (root / "core").mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "core" / "economy.py").write_text(
        """\
class EconomyPort:
    def evaluate(self, value: int) -> int:
        return value
""",
        encoding="utf-8",
    )
    (root / "app" / "vitals_loop.py").write_text(
        """\
from core.economy import EconomyPort


def tick(v: int) -> int:
    return EconomyPort().evaluate(v)
""",
        encoding="utf-8",
    )


def test_explore_command_plain(monkeypatch, tmp_path: Path) -> None:
    _seed_explore_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["explore", "EconomyPort", "evaluate", "parameter"])
    assert result.exit_code == 0
    assert "# Explore Report" in result.output
    assert "Potential touch points:" in result.output
    assert "Candidate approaches:" in result.output


def test_explore_command_json(monkeypatch, tmp_path: Path) -> None:
    _seed_explore_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["explore", "EconomyPort", "evaluate", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "report" in payload
    assert payload["report"]["question"] == "EconomyPort evaluate"
    assert payload["report"]["matches"]
