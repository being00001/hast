"""Tests for automation loop."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml

from hast.core.attempt import AttemptLog
from hast.core.auto import (
    _changes_allowed,
    build_prompt,
    build_phase_prompt,
    evaluate,
    evaluate_phase,
    run_auto,
)
from hast.core.config import Config
from hast.core.errors import DevfError
from hast.core.goals import Goal, find_goal, load_goals
from hast.core.immune_policy import write_repair_grant
from hast.core.runner import GoalRunner, RunnerResult
from hast.core.runners.local import LocalRunner


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
    """Changes to .ai/ should always be allowed (hast metadata)."""
    assert _changes_allowed(
        ["src/auth.py", ".ai/handoffs/2026-02-10_120000.md"],
        ["src/*.py"],
    )
    assert _changes_allowed([".ai/sessions/log.md"], ["src/*.py"])


def test_changes_allowed_with_always_allow_patterns() -> None:
    assert _changes_allowed(
        ["src/auth.py", "docs/ARCHITECTURE.md"],
        ["src/*.py"],
        always_allow=["docs/ARCHITECTURE.md"],
    )


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
    assert "outside.txt" in (outcome.reason or "")


def test_evaluate_changes_outside_allowed_with_always_allow(tmp_project: Path) -> None:
    config = _make_config(always_allow_changes=["docs/ARCHITECTURE.md"])
    goal = _make_goal(allowed_changes=["src/*.py"])

    src_file = tmp_project / "src" / "auth.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("x = 1\n", encoding="utf-8")
    (tmp_project / "docs" / "ARCHITECTURE.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_project / "docs" / "ARCHITECTURE.md").write_text("# generated\n", encoding="utf-8")

    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, _test_output = evaluate(tmp_project, config, goal, base_commit)
    assert outcome.success
    assert outcome.classification == "complete"


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
    assert ret.exit_code == 0
    captured = capsys.readouterr()
    assert "devfork auto dry-run summary" in captured.out
    assert "G1" in captured.out
    assert "<context_pack version=\"1\">" not in captured.out


def test_dry_run_full_prints_prompt(tmp_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_dirty_project_with_goal(tmp_project)

    ret = run_auto(
        tmp_project,
        goal_id=None,
        recursive=False,
        dry_run=True,
        dry_run_full=True,
        explain=False,
        tool_name=None,
    )
    assert ret.exit_code == 0
    captured = capsys.readouterr()
    assert "<context_pack version=\"1\">" in captured.out


def test_dry_run_skips_auto_preflight(tmp_project: Path) -> None:
    _make_dirty_project_with_goal(tmp_project)

    called = False

    def _fake_preflight(root: Path) -> None:
        nonlocal called
        called = True
        raise AssertionError("preflight should not run in dry-run mode")

    import hast.core.auto as auto_module

    original = auto_module.run_doctor
    try:
        auto_module.run_doctor = _fake_preflight  # type: ignore[assignment]
        ret = run_auto(tmp_project, goal_id=None, recursive=False, dry_run=True, explain=False, tool_name=None)
    finally:
        auto_module.run_doctor = original  # type: ignore[assignment]

    assert ret.exit_code == 0
    assert called is False


def test_non_dry_run_rejects_dirty_tree(tmp_project: Path) -> None:
    """Normal run should still reject a dirty working tree."""
    _make_dirty_project_with_goal(tmp_project)

    with pytest.raises(DevfError, match="dirty"):
        run_auto(tmp_project, goal_id=None, recursive=False, dry_run=False, explain=False, tool_name=None)


def test_non_dry_run_runs_auto_preflight(tmp_project: Path) -> None:
    (tmp_project / ".ai" / "goals.yaml").write_text(
        "goals:\n  - id: G1\n    title: Test\n    status: active\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add goal"], cwd=str(tmp_project), capture_output=True, check=True)

    called = False

    def _fake_preflight(root: Path) -> object:
        nonlocal called
        called = True
        from hast.core.doctor import DoctorReport

        return DoctorReport(
            root=root.as_posix(),
            checks=[],
            pass_count=0,
            warn_count=0,
            fail_count=0,
            ok=True,
        )

    import hast.core.auto as auto_module

    original = auto_module.run_doctor
    try:
        auto_module.run_doctor = _fake_preflight  # type: ignore[assignment]
        runner = MockRunner(filename="output.py", content="x = 1\n")
        ret = run_auto(
            tmp_project,
            goal_id=None,
            recursive=False,
            dry_run=False,
            explain=False,
            tool_name=None,
            runner=runner,
        )
    finally:
        auto_module.run_doctor = original  # type: ignore[assignment]

    assert ret.exit_code == 0
    assert called is True


def test_non_dry_run_allows_untracked_ai_operational_files(tmp_project: Path) -> None:
    """Untracked .ai operational artifacts should not block auto startup."""
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
    runs_dir = tmp_project / ".ai" / "runs" / "20260215T120000+0000"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "evidence.jsonl").write_text("{}", encoding="utf-8")

    runner = MockRunner(filename="output.py", content="x = 1\n")
    ret = run_auto(
        tmp_project,
        goal_id=None,
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0


def test_build_prompt_includes_non_interactive_contract(tmp_project: Path) -> None:
    config = _make_config()
    goal = _make_goal()
    prompt = build_prompt(tmp_project, config, goal)
    assert "NON-INTERACTIVE CONTRACT" in prompt
    assert "Do not ask clarification questions." in prompt


def test_build_phase_prompt_implement_fallback(tmp_project: Path) -> None:
    """implement phase without template falls back to existing build_prompt."""
    config = _make_config()
    goal = _make_goal(phase="implement")
    prompt = build_phase_prompt(tmp_project, config, goal, "implement", [])
    # Should contain the standard checklist from build_prompt
    assert "checklist" in prompt.lower()


def test_build_phase_prompt_with_template(tmp_project: Path) -> None:
    """Phase prompt uses Jinja2 template when available."""
    templates_dir = tmp_project / ".ai" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "implement.md.j2").write_text(
        "TEMPLATE: {{ goal.id }} - {{ goal.title }}", encoding="utf-8"
    )

    config = _make_config()
    goal = _make_goal(phase="implement")
    prompt = build_phase_prompt(tmp_project, config, goal, "implement", [])
    assert "TEMPLATE: G1 - Test Goal" in prompt


def test_evaluate_phase_gate(tmp_project: Path) -> None:
    """gate phase runs mechanical checks instead of AI evaluation."""
    config = _make_config()
    goal = _make_goal(phase="gate")

    (tmp_project / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_project), capture_output=True, text=True, check=True,
    ).stdout.strip()

    outcome, output = evaluate_phase(tmp_project, config, goal, "gate", base_commit)
    assert outcome.success
    assert "gate" in outcome.classification.lower()


# ---------------------------------------------------------------------------
# Phase-aware run_auto + circuit breaker tests
# ---------------------------------------------------------------------------


class MockRunner(GoalRunner):
    """Runner that writes a file and succeeds."""

    def __init__(self, filename: str = "output.py", content: str = "x = 1\n"):
        self.filename = filename
        self.content = content
        self.call_count = 0

    def run(self, root, config, goal, prompt, tool_name=None):
        self.call_count += 1
        (root / self.filename).write_text(self.content, encoding="utf-8")
        return RunnerResult(success=True, output="ok")


class NoopRunner(GoalRunner):
    """Runner that does nothing (no file changes)."""

    def __init__(self):
        self.call_count = 0

    def run(self, root, config, goal, prompt, tool_name=None):
        self.call_count += 1
        return RunnerResult(success=True, output="ok")


def test_run_auto_phase_implement_advances(tmp_project: Path) -> None:
    """run_auto with implement phase should advance phase on success."""
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Test"
                status: active
                phase: implement
        """),
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

    runner = MockRunner()
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    # After implement success, phase should advance to gate (not done via legacy)
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.phase == "gate", f"expected phase='gate' but got phase={g.phase!r}, status={g.status!r}"


def test_run_auto_legacy_no_phase(tmp_project: Path) -> None:
    """run_auto without phase field should use legacy behavior."""
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Test"
                status: active
        """),
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

    runner = MockRunner()
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "done"


def test_run_auto_circuit_breaker_no_progress(tmp_project: Path) -> None:
    """Circuit breaker should stop after max consecutive no-progress."""
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Test1"
                status: active
              - id: G2
                title: "Test2"
                status: active
              - id: G3
                title: "Test3"
                status: active
              - id: G4
                title: "Test4"
                status: active
        """),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add goals"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )

    # Set circuit breaker to 2 consecutive no-progress
    config_path = tmp_project / ".ai" / "config.yaml"
    config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_data["circuit_breakers"] = {
        "max_cycles_per_session": 10,
        "max_consecutive_no_progress": 2,
    }
    config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "update config"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )

    # NoopRunner makes no changes -> always fails with no-progress
    runner = NoopRunner()
    ret = run_auto(
        tmp_project,
        goal_id=None,
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 1
    # Should have stopped after 2 consecutive failures, not running all 4
    assert runner.call_count <= 2 * 3  # max 2 goals * max_retries(3)


def test_run_auto_failure_assist_for_no_progress(
    tmp_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Ambiguous task"
                status: active
        """),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add no-progress goal"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )

    config_path = tmp_project / ".ai" / "config.yaml"
    config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_data["max_retries"] = 1
    config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "set max_retries 1"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )

    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=NoopRunner(),
    )
    assert ret.exit_code == 1
    captured = capsys.readouterr()
    assert "failure assist" in captured.err
    assert "devfork explore" in captured.err


def test_dry_run_phase_prompt(
    tmp_project: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """dry-run with phase goal should use build_phase_prompt."""
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Phased Goal"
                status: active
                phase: implement
        """),
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

    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=True,
        explain=False,
        tool_name=None,
    )
    assert ret.exit_code == 0
    captured = capsys.readouterr()
    assert "G1" in captured.out


# --- Phase→Agent routing tests ---


def test_local_runner_phase_agent_routing() -> None:
    """LocalRunner should use PHASE_AGENT_MAP when goal has phase but no agent."""
    runner = LocalRunner()
    config = _make_config(ai_tools={"opus": "echo opus {prompt}", "codex": "echo codex {prompt}"})
    goal = _make_goal(phase="implement", agent=None, tool=None)
    cmd = runner._resolve_tool_command(config, goal, tool_name=None)
    assert cmd == "echo codex {prompt}"


def test_local_runner_phase_plan_routes_to_opus() -> None:
    """plan phase should default to opus agent."""
    runner = LocalRunner()
    config = _make_config(ai_tools={"opus": "echo opus {prompt}", "codex": "echo codex {prompt}"})
    goal = _make_goal(phase="plan", agent=None, tool=None)
    cmd = runner._resolve_tool_command(config, goal, tool_name=None)
    assert cmd == "echo opus {prompt}"


def test_local_runner_explicit_agent_overrides_phase() -> None:
    """Explicit goal.agent should override phase default."""
    runner = LocalRunner()
    config = _make_config(
        ai_tools={
            "opus": "echo opus {prompt}",
            "sonnet": "echo sonnet {prompt}",
            "codex": "echo codex {prompt}",
        },
    )
    goal = _make_goal(phase="implement", agent="sonnet", tool=None)
    cmd = runner._resolve_tool_command(config, goal, tool_name=None)
    assert cmd == "echo sonnet {prompt}"


def test_local_runner_no_phase_no_agent_uses_default() -> None:
    """Legacy goal (no phase, no agent) should use config.ai_tool default."""
    runner = LocalRunner()
    config = _make_config()
    goal = _make_goal(phase=None, agent=None, tool=None)
    cmd = runner._resolve_tool_command(config, goal, tool_name=None)
    assert cmd == "echo {prompt}"


def test_run_auto_custom_phases_skips_adversarial(tmp_project: Path) -> None:
    """Custom phases=['implement','gate','merge'] should skip adversarial and finish as done."""
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Custom Phases"
                status: active
                phase: implement
                phases:
                  - implement
                  - gate
                  - merge
        """),
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

    runner = MockRunner()

    # Phase 1: implement -> should advance to gate
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.phase == "gate", f"after implement: expected phase='gate', got {g.phase!r}"

    # Commit changes from phase advancement before next run
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "phase advance"],
        cwd=str(tmp_project), capture_output=True, check=True,
    )

    # Phase 2: gate -> with custom phases, next is merge (NOT adversarial),
    # and merge is handled inline, completing the goal in one step.
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    # With default phases, gate->adversarial (status stays active).
    # With custom phases ["implement","gate","merge"], gate->merge->done.
    assert g.status == "done", (
        f"after gate: expected status='done' (custom phases: gate->merge->done), "
        f"got status={g.status!r}, phase={g.phase!r}"
    )


def test_run_auto_blocks_high_uncertainty_without_decision(
    tmp_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Needs decision first"
                status: active
                phase: implement
                uncertainty: high
        """),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add high-uncertainty goal"],
        cwd=str(tmp_project),
        capture_output=True,
        check=True,
    )

    runner = MockRunner()
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 1
    assert runner.call_count == 0
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "blocked"
    captured = capsys.readouterr()
    assert "failure assist" in captured.err
    assert "decision new G1" in captured.err


def test_run_auto_allows_high_uncertainty_with_accepted_decision(tmp_project: Path) -> None:
    decisions_dir = tmp_project / ".ai" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "D_G1.yaml").write_text(
        textwrap.dedent("""\
            decision:
              version: 1
              decision_id: D_G1
              goal_id: G1
              question: Which approach?
              status: accepted
              alternatives:
                - id: A
                - id: B
              validation_matrix:
                - criterion: contract_fit
                  weight: 100
                  min_score: 3
              scores:
                A:
                  contract_fit: 4
                B:
                  contract_fit: 2
              selected_alternative: A
        """),
        encoding="utf-8",
    )
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Needs decision first"
                status: active
                phase: implement
                uncertainty: high
                decision_file: ".ai/decisions/D_G1.yaml"
        """),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add decision-backed goal"],
        cwd=str(tmp_project),
        capture_output=True,
        check=True,
    )

    runner = MockRunner()
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    assert runner.call_count >= 1


def test_run_auto_immune_blocks_without_grant(tmp_project: Path) -> None:
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Immune protected"
                status: active
        """),
        encoding="utf-8",
    )
    policies_dir = tmp_project / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "immune_policy.yaml").write_text(
        textwrap.dedent("""\
            version: v1
            enabled: true
            require_grant_for_writes: true
            grant_file: ".ai/immune/grant.yaml"
            audit_file: ".ai/immune/audit.jsonl"
            max_changed_files: 120
            protected_path_patterns:
              - ".ai/policies/**"
              - ".ai/protocols/**"
              - ".ai/immune/**"
        """),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "enable immune policy"],
        cwd=str(tmp_project),
        capture_output=True,
        check=True,
    )

    runner = MockRunner(filename="worker.py")
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 1
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "blocked"

    audit_file = tmp_project / ".ai" / "immune" / "audit.jsonl"
    assert audit_file.exists()
    assert "grant-missing" in audit_file.read_text(encoding="utf-8")


def test_run_auto_immune_allows_with_grant(tmp_project: Path) -> None:
    goals_yaml = tmp_project / ".ai" / "goals.yaml"
    goals_yaml.write_text(
        textwrap.dedent("""\
            goals:
              - id: G1
                title: "Immune protected"
                status: active
        """),
        encoding="utf-8",
    )
    policies_dir = tmp_project / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "immune_policy.yaml").write_text(
        textwrap.dedent("""\
            version: v1
            enabled: true
            require_grant_for_writes: true
            grant_file: ".ai/immune/grant.yaml"
            audit_file: ".ai/immune/audit.jsonl"
            max_changed_files: 120
            protected_path_patterns:
              - ".ai/policies/**"
              - ".ai/protocols/**"
              - ".ai/immune/**"
        """),
        encoding="utf-8",
    )
    write_repair_grant(
        tmp_project,
        allowed_changes=["worker.py"],
        approved_by="supervisor",
        ttl_minutes=60,
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "enable immune policy with grant"],
        cwd=str(tmp_project),
        capture_output=True,
        check=True,
    )

    runner = MockRunner(filename="worker.py")
    ret = run_auto(
        tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=runner,
    )
    assert ret.exit_code == 0
    goals = load_goals(goals_yaml)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "done"
