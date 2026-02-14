"""Tests for dependency-aware parallel execution in run_auto."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap
import time

from devf.core.auto import run_auto
from devf.core.goals import find_goal, load_goals
from devf.core.runner import GoalRunner, RunnerResult


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(root: Path) -> None:
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "config.yaml").write_text(
        'test_command: "true"\nai_tool: "echo {prompt}"\n',
        encoding="utf-8",
    )
    (root / ".ai" / "rules.md").write_text("# rules\n", encoding="utf-8")
    (root / ".ai" / "goals.yaml").write_text(
        textwrap.dedent(
            """\
            goals:
              - id: ROOT
                title: Root
                status: pending
                children:
                  - id: G1
                    title: one
                    status: active
                  - id: G2
                    title: two
                    status: active
            """
        ),
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


class _ParallelRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        time.sleep(0.05)
        (root / "src" / f"{goal.id.lower()}.py").write_text(f"value = '{goal.id}'\n", encoding="utf-8")
        return RunnerResult(success=True, output="ok")


def test_run_auto_parallel_recursive(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    code = run_auto(
        root=tmp_path,
        goal_id="ROOT",
        recursive=True,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_ParallelRunner(),
        parallelism=2,
    )
    assert code == 0

    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g1 = find_goal(goals, "G1")
    g2 = find_goal(goals, "G2")
    assert g1 is not None and g1.status == "done"
    assert g2 is not None and g2.status == "done"
