"""CLI tests for focus session pack command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "config.yaml").write_text(
        """
test_command: "pytest -q"
ai_tool: "claude -p {prompt_file}"
ai_tools:
  codex: "codex exec {prompt_file}"
  claude: "claude -p {prompt_file}"
""",
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G_FOCUS
    title: "Focus goal"
    status: active
    phase: implement
    uncertainty: high
    allowed_changes:
      - "src/**/*.py"
    test_files:
      - "tests/test_focus.py"
""",
        encoding="utf-8",
    )


def test_focus_command_json_writes_pack(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.build_context", lambda _root, _fmt: "<CTX/>")

    runner = CliRunner()
    result = runner.invoke(main, ["focus", "--tool", "codex", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["tool"] == "codex"
    assert payload["goal"]["id"] == "G_FOCUS"
    assert payload["launch_command"].startswith("codex exec ")

    prompt_path = tmp_path / payload["prompt_path"]
    brief_path = tmp_path / payload["brief_path"]
    assert prompt_path.exists()
    assert brief_path.exists()
    assert "<CTX/>" in prompt_path.read_text(encoding="utf-8")
    assert "G_FOCUS" in brief_path.read_text(encoding="utf-8")


def test_focus_command_goal_not_found(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.build_context", lambda _root, _fmt: "<CTX/>")

    runner = CliRunner()
    result = runner.invoke(main, ["focus", "--tool", "claude", "--goal", "NOPE"])
    assert result.exit_code == 1
    assert "goal not found: NOPE" in result.output


def test_focus_command_defaults_without_goal(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    monkeypatch.setattr("hast.cli.build_context", lambda _root, _fmt: "<CTX/>")

    runner = CliRunner()
    result = runner.invoke(main, ["focus", "--tool", "claude", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["goal"] is None
    assert payload["launch_command"].startswith("claude -p ")
