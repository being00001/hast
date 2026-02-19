"""CLI tests for doctor command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_minimal_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "config.yaml").write_text(
        """
test_command: "true"
ai_tool: "echo {prompt}"
""",
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
""",
        encoding="utf-8",
    )
    (root / ".ai" / "rules.md").write_text("- keep changes small\n", encoding="utf-8")


def test_doctor_json_fails_when_ai_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 1

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["fail_count"] >= 1
    assert any(check["code"] == "ai_layout" for check in payload["checks"])


def test_doctor_json_non_strict_allows_warnings(monkeypatch, tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["fail_count"] == 0
    assert any(check["code"] == "config" and check["status"] == "pass" for check in payload["checks"])


def test_doctor_json_strict_fails_on_warning(monkeypatch, tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--strict", "--json"])
    assert result.exit_code == 1

    payload = json.loads(result.output)
    assert payload["fail_count"] == 0
    assert payload["warn_count"] > 0
