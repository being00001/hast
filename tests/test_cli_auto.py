"""CLI tests for auto command dry-run modes."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hast.cli import main
from hast.core.result import AutoResult


def test_auto_command_dry_run_full_requires_dry_run() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["auto", "--dry-run-full"])
    assert result.exit_code != 0
    assert "--dry-run-full requires --dry-run" in result.output


def test_auto_command_passes_dry_run_full(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    def _fake_run_auto(**kwargs: object) -> AutoResult:
        observed.update(kwargs)
        return AutoResult(exit_code=0, run_id="test-run-id")

    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.run_auto", _fake_run_auto)

    runner = CliRunner()
    result = runner.invoke(main, ["auto", "--dry-run", "--dry-run-full"])
    assert result.exit_code == 0
    assert observed["dry_run"] is True
    assert observed["dry_run_full"] is True
