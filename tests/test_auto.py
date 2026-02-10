"""Tests for automation loop."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from devf.core.auto import (
    Outcome,
    _changes_allowed,
    build_prompt,
    evaluate,
    resolve_tool_command,
)
from devf.core.config import Config
from devf.core.errors import DevfError
from devf.core.goals import Goal


def _make_config(**overrides: object) -> Config:
    defaults = {
        "test_command": "echo ok",
        "ai_tool": "echo {prompt}",
        "timeout_minutes": 30,
        "max_retries": 3,
        "max_context_bytes": 120_000,
        "ai_tools": {},
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def _make_goal(**overrides: object) -> Goal:
    defaults = {
        "id": "G1",
        "title": "Test Goal",
        "status": "active",
        "children": [],
        "expect_failure": False,
        "allowed_changes": [],
        "prompt_mode": None,
        "mode": None,
        "tool": None,
    }
    defaults.update(overrides)
    return Goal(**defaults)  # type: ignore[arg-type]


def test_resolve_tool_default() -> None:
    config = _make_config()
    goal = _make_goal()
    assert resolve_tool_command(config, goal, None) == "echo {prompt}"


def test_resolve_tool_override() -> None:
    config = _make_config(ai_tools={"codex": "codex exec {prompt}"})
    goal = _make_goal()
    assert resolve_tool_command(config, goal, "codex") == "codex exec {prompt}"


def test_resolve_tool_from_goal() -> None:
    config = _make_config(ai_tools={"codex": "codex exec {prompt}"})
    goal = _make_goal(tool="codex")
    assert resolve_tool_command(config, goal, None) == "codex exec {prompt}"


def test_resolve_tool_unknown() -> None:
    config = _make_config()
    goal = _make_goal()
    with pytest.raises(DevfError, match="tool not found"):
        resolve_tool_command(config, goal, "nope")


def test_changes_allowed() -> None:
    assert _changes_allowed(["src/auth.py"], ["src/*.py"])
    assert not _changes_allowed(["src/auth.py", "docs/readme.md"], ["src/*.py"])
    assert _changes_allowed([], ["src/*.py"])


def test_changes_allowed_ai_dir_always_ok() -> None:
    """Changes to .ai/ should always be allowed (devf metadata)."""
    assert _changes_allowed(
        ["src/auth.py", ".ai/handoffs/2026-02-10_120000.md"],
        ["src/*.py"],
    )
    assert _changes_allowed([".ai/sessions/log.md"], ["src/*.py"])


def test_build_prompt(tmp_path: Path) -> None:
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("# Rules\n- Run tests\n", encoding="utf-8")

    config = _make_config(test_command="pytest")
    goal = _make_goal()
    prompt = build_prompt(tmp_path, config, goal)
    assert "pytest" in prompt
    assert "commit" in prompt.lower()


def test_build_prompt_handoff_template(tmp_path: Path) -> None:
    """Prompt should include a handoff template with goal_id pre-filled."""
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("", encoding="utf-8")

    config = _make_config()
    goal = _make_goal(id="M1.2")
    prompt = build_prompt(tmp_path, config, goal)
    assert 'goal_id: "M1.2"' in prompt
    assert "## Done" in prompt
    assert "## Key Decisions" in prompt
    assert "## Changed Files" in prompt
    assert "## Next" in prompt
    assert ".ai/handoffs/" in prompt


def test_build_prompt_expect_failure(tmp_path: Path) -> None:
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("", encoding="utf-8")

    config = _make_config()
    goal = _make_goal(expect_failure=True)
    prompt = build_prompt(tmp_path, config, goal)
    assert "RED" in prompt


def test_build_prompt_allowed_changes(tmp_path: Path) -> None:
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("", encoding="utf-8")

    config = _make_config()
    goal = _make_goal(allowed_changes=["src/auth.py"])
    prompt = build_prompt(tmp_path, config, goal)
    assert "src/auth.py" in prompt


def test_build_prompt_adversarial(tmp_path: Path) -> None:
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("", encoding="utf-8")

    config = _make_config()
    goal = _make_goal(prompt_mode="adversarial")
    prompt = build_prompt(tmp_path, config, goal)
    assert "adversarial" in prompt.lower()


def test_evaluate_complete(tmp_project: Path) -> None:
    config = _make_config()
    goal = _make_goal()

    (tmp_project / "new_file.py").write_text("x = 1\n", encoding="utf-8")

    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, test_output = evaluate(tmp_project, config, goal, base_commit)
    assert outcome.success
    assert outcome.classification == "complete"
    assert isinstance(test_output, str)


def test_evaluate_no_changes(tmp_project: Path) -> None:
    config = _make_config()
    goal = _make_goal()
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, test_output = evaluate(tmp_project, config, goal, base_commit)
    assert not outcome.success
    assert outcome.classification == "no-progress"


def test_evaluate_expect_failure(tmp_project: Path) -> None:
    config = _make_config(test_command="false")  # always fail
    goal = _make_goal(expect_failure=True)

    (tmp_project / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, _test_output = evaluate(tmp_project, config, goal, base_commit)
    assert outcome.success
    assert "expected failure" in outcome.classification


def test_evaluate_changes_outside_allowed(tmp_project: Path) -> None:
    config = _make_config()
    goal = _make_goal(allowed_changes=["src/*.py"])

    (tmp_project / "outside.txt").write_text("x\n", encoding="utf-8")
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, _test_output = evaluate(tmp_project, config, goal, base_commit)
    assert not outcome.success
    assert outcome.should_retry
    assert "allowed scope" in (outcome.reason or "")


def test_evaluate_tests_failed(tmp_project: Path) -> None:
    config = _make_config(test_command="false")
    goal = _make_goal()

    (tmp_project / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, _test_output = evaluate(tmp_project, config, goal, base_commit)
    assert not outcome.success
    assert outcome.should_retry
    assert outcome.reason == "tests failed"


def test_evaluate_complexity_warning(tmp_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Complexity warnings should go to stderr but not fail the evaluation."""
    config = _make_config()
    goal = _make_goal()

    # Create a file that exceeds line limit
    lines = "\n".join(f"x{i} = {i}" for i in range(500))
    (tmp_project / "big.py").write_text(lines, encoding="utf-8")

    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, _test_output = evaluate(tmp_project, config, goal, base_commit)
    assert outcome.success  # complexity is a warning, not failure
    captured = capsys.readouterr()
    assert "[complexity]" in captured.err


def test_build_prompt_acceptance_criteria(tmp_project: "Path") -> None:
    """Acceptance criteria should appear in the prompt instructions."""
    from devf.core.auto import build_prompt
    from devf.core.config import Config
    from devf.core.goals import Goal

    config = Config(test_command="pytest", ai_tool="echo {prompt}")
    goal = Goal(
        id="V1", title="Login", status="active",
        notes="Use JWT tokens",
        acceptance=["pytest tests/test_auth.py passes", "POST /login returns 200"],
    )
    prompt = build_prompt(tmp_project, config, goal)

    assert "Acceptance criteria (ALL must be met):" in prompt
    assert "pytest tests/test_auth.py passes" in prompt
    assert "POST /login returns 200" in prompt
    assert "Design notes: Use JWT tokens" in prompt


def test_build_prompt_no_acceptance(tmp_project: "Path") -> None:
    """Without acceptance criteria, prompt should not have the section."""
    from devf.core.auto import build_prompt
    from devf.core.config import Config
    from devf.core.goals import Goal

    config = Config(test_command="pytest", ai_tool="echo {prompt}")
    goal = Goal(id="V1", title="Login", status="active")
    prompt = build_prompt(tmp_project, config, goal)

    assert "Acceptance criteria" not in prompt
    assert "Design notes" not in prompt
