"""Tests for automation loop."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from devf.core.attempt import AttemptLog
from devf.core.auto import (
    Outcome,
    _changes_allowed,
    build_prompt,
    evaluate,
    run_auto,
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
        "notes": None,
        "acceptance": [],
        "test_files": [],
    }
    defaults.update(overrides)
    return Goal(**defaults)  # type: ignore[arg-type]


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
    assert "checklist" in prompt.lower()


def test_build_prompt_handoff_template(tmp_path: Path) -> None:
    """Prompt should include a task tag with goal_id pre-filled in XML."""
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
    assert '<task id="M1.2">' in prompt
    assert "Work completion checklist" in prompt
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

    # Create the allowed file so build_symbol_map picks it up
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass\n", encoding="utf-8")

    config = _make_config()
    goal = _make_goal(allowed_changes=["src/auth.py"])
    prompt = build_prompt(tmp_path, config, goal)
    assert "src/auth.py" in prompt
    assert "class" in prompt or "def" in prompt  # Map should contain the symbol


def test_build_prompt_includes_file_contents(tmp_path: Path) -> None:
    """Prompt should include actual source code of target files."""
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "handoffs").mkdir()
    (ai / "sessions").mkdir()
    (ai / "config.yaml").write_text(
        'test_command: "pytest"\nai_tool: "echo {prompt}"\n', encoding="utf-8",
    )
    (ai / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai / "rules.md").write_text("", encoding="utf-8")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "queue.py").write_text(
        "class TaskQueue:\n    def push(self, item): pass\n", encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_queue.py").write_text(
        "def test_push(): assert True\n", encoding="utf-8",
    )

    config = _make_config()
    goal = _make_goal(
        allowed_changes=["src/queue.py"],
        test_files=["tests/test_queue.py"],
    )
    prompt = build_prompt(tmp_path, config, goal)
    assert "<target_files>" in prompt
    assert "class TaskQueue:" in prompt
    assert "def test_push():" in prompt


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
    """Acceptance criteria should appear in the XML constraints section."""
    config = _make_config()
    goal = Goal(
        id="V1", title="Login", status="active",
        notes="Use JWT tokens",
        acceptance=["pytest tests/test_auth.py passes", "POST /login returns 200"],
    )
    prompt = build_prompt(tmp_project, config, goal)

    assert "<criteria>pytest tests/test_auth.py passes</criteria>" in prompt
    assert "<criteria>POST /login returns 200</criteria>" in prompt
    assert "<notes>Use JWT tokens</notes>" in prompt


def test_build_prompt_no_acceptance(tmp_project: "Path") -> None:
    """Without acceptance criteria, prompt should not have the section."""
    config = _make_config()
    goal = Goal(id="V1", title="Login", status="active")
    prompt = build_prompt(tmp_project, config, goal)

    assert "Acceptance criteria" not in prompt
    assert "Design notes" not in prompt


def test_build_prompt_retry_includes_diff(tmp_project: "Path") -> None:
    """Retry prompt should include the actual diff from previous attempt."""
    config = _make_config()
    goal = _make_goal()
    attempts = [
        AttemptLog(
            attempt=1,
            classification="failed",
            reason="tests failed",
            diff_stat="src/foo.py | 3 +++",
            test_output="FAILED test_foo - AssertionError\n1 failed, 2 passed",
            diff="--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old_code\n+new_code",
        ),
    ]
    prompt = build_prompt(tmp_project, config, goal, attempts)
    assert "DO NOT repeat the same approach" in prompt
    assert "-old_code" in prompt
    assert "+new_code" in prompt
    assert "FAILED test_foo" in prompt


def test_build_prompt_retry_without_diff(tmp_project: "Path") -> None:
    """Retry with no diff should fall back to diff_stat."""
    config = _make_config()
    goal = _make_goal()
    attempts = [
        AttemptLog(
            attempt=1,
            classification="no-progress",
            reason="no file changes",
            diff_stat="",
            test_output="",
        ),
    ]
    prompt = build_prompt(tmp_project, config, goal, attempts)
    assert "Attempt 1" in prompt
    assert "no-progress" in prompt


def _make_dirty_project_with_goal(tmp_project: Path) -> None:
    """Add an active goal and make the working tree dirty."""
    (tmp_project / ".ai" / "goals.yaml").write_text(
        "goals:\n  - id: G1\n    title: Test\n    status: active\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add goal"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    # Make tree dirty
    (tmp_project / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")


def test_dry_run_works_on_dirty_tree(tmp_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--dry-run should print prompt without error even on a dirty tree."""
    _make_dirty_project_with_goal(tmp_project)

    ret = run_auto(tmp_project, goal_id=None, recursive=False, dry_run=True, explain=False, tool_name=None)
    assert ret == 0
    captured = capsys.readouterr()
    assert "G1" in captured.out  # prompt should contain the goal


def test_non_dry_run_rejects_dirty_tree(tmp_project: Path) -> None:
    """Normal run should still reject a dirty working tree."""
    _make_dirty_project_with_goal(tmp_project)

    with pytest.raises(DevfError, match="dirty"):
        run_auto(tmp_project, goal_id=None, recursive=False, dry_run=False, explain=False, tool_name=None)