"""Integration checks for pre-apply hard file policy."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

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


def _init_repo(root: Path, goals_yaml: str) -> None:
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "config.yaml").write_text(
        'test_command: "true"\nai_tool: "echo {prompt}"\n',
        encoding="utf-8",
    )
    (root / ".ai" / "rules.md").write_text("# rules\n", encoding="utf-8")
    (root / ".ai" / "goals.yaml").write_text(textwrap.dedent(goals_yaml), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


class _BadTesterRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        output = """
```python src/should_not_change.py
x = 1
```
"""
        return RunnerResult(success=True, output=output)


def test_hard_policy_blocks_before_apply(tmp_path: Path) -> None:
    _init_repo(
        tmp_path,
        """
goals:
  - id: G1
    title: tester goal
    status: active
    owner_agent: tester
""",
    )

    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_BadTesterRunner(),
        parallelism=1,
    )
    assert code == 1
    assert not (tmp_path / "src" / "should_not_change.py").exists()

    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status in {"blocked", "active"}
