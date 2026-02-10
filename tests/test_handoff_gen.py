"""Tests for handoff generation from git data."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from devf.core.handoff import (
    _detect_goal_id,
    _extract_decisions,
    _find_next_task,
    generate_handoff,
)


def _commit(root: Path, message: str, files: dict[str, str] | None = None) -> str:
    """Create files, stage, and commit. Return short hash."""
    if files:
        for name, content in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=str(root), capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(root), capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# --- Unit tests for helpers ---


def test_detect_goal_id() -> None:
    commits = [
        ("abc", "feat(V1.1): add login"),
        ("def", "test(V1.1): add login tests"),
        ("ghi", "fix(V1.2): session bug"),
    ]
    assert _detect_goal_id(commits) == "V1.1"


def test_detect_goal_id_no_conventional() -> None:
    commits = [("abc", "initial commit")]
    assert _detect_goal_id(commits) is None


def test_extract_decisions() -> None:
    messages = [
        ("feat(V1): add auth", "Used JWT for stateless sessions\nChose bcrypt for hashing"),
        ("fix(V1): typo", ""),
    ]
    decisions = _extract_decisions(messages)
    assert len(decisions) == 2
    assert "JWT" in decisions[0]


def test_extract_decisions_skips_coauthor() -> None:
    messages = [
        ("feat(V1): add auth", "Used JWT\nCo-Authored-By: test"),
    ]
    decisions = _extract_decisions(messages)
    assert len(decisions) == 1


def test_find_next_task(tmp_path: Path) -> None:
    goals_yaml = tmp_path / ".ai" / "goals.yaml"
    goals_yaml.parent.mkdir(parents=True)
    goals_yaml.write_text(textwrap.dedent("""\
        goals:
          - id: V1
            title: "Polish"
            status: active
            children:
              - id: V1.1
                title: "Login"
                status: done
              - id: V1.2
                title: "Session"
                status: active
              - id: V1.3
                title: "Refactor"
                status: pending
    """), encoding="utf-8")

    assert _find_next_task(tmp_path, "V1.1") == "V1.2 \u2014 Session"
    assert _find_next_task(tmp_path, "V1.2") == "V1.3 \u2014 Refactor"
    assert _find_next_task(tmp_path, "V1.3") is None


def test_find_next_task_no_current(tmp_path: Path) -> None:
    goals_yaml = tmp_path / ".ai" / "goals.yaml"
    goals_yaml.parent.mkdir(parents=True)
    goals_yaml.write_text(textwrap.dedent("""\
        goals:
          - id: G1
            title: "First"
            status: active
    """), encoding="utf-8")
    assert _find_next_task(tmp_path, None) == "G1 \u2014 First"


def test_find_next_task_no_goals(tmp_path: Path) -> None:
    assert _find_next_task(tmp_path, "V1") is None


# --- Integration tests with git ---


def test_generate_handoff_basic(tmp_project: "Path") -> None:
    """Generate handoff in a repo with commits after a handoff."""
    handoff_dir = tmp_project / ".ai" / "handoffs"
    (handoff_dir / "2026-02-09_140000.md").write_text(textwrap.dedent("""\
        ---
        timestamp: "2026-02-09T14:00:00+09:00"
        status: complete
        goal_id: "V1.0"
        ---
        ## Done
        Initial setup
    """), encoding="utf-8")
    _commit(tmp_project, "chore(V1.0): add handoff")

    (tmp_project / ".ai" / "goals.yaml").write_text(textwrap.dedent("""\
        goals:
          - id: V1
            title: "Polish"
            status: active
            children:
              - id: V1.0
                title: "Setup"
                status: done
              - id: V1.1
                title: "Login"
                status: active
    """), encoding="utf-8")
    _commit(tmp_project, "feat(V1.1): implement login", {
        "src/auth.py": "class Auth:\n    pass\n",
    })

    content, filename = generate_handoff(tmp_project)

    assert "## Done" in content
    assert "implement login" in content
    assert "## Changed Files" in content
    assert "## Next" in content
    assert "## Context Files" in content
    assert "src/auth.py" in content
    assert 'goal_id: "V1.1"' in content
    assert filename.endswith(".md")


def test_generate_handoff_no_boundary(tmp_project: "Path") -> None:
    """Generate handoff when no previous session exists."""
    _commit(tmp_project, "feat(G1): first feature", {
        "src/app.py": "print('hello')\n",
    })

    content, _ = generate_handoff(tmp_project)

    assert "## Done" in content
    assert "first feature" in content
    assert 'goal_id: "G1"' in content


def test_generate_handoff_explicit_goal(tmp_project: "Path") -> None:
    """Explicit goal_id overrides auto-detection."""
    _commit(tmp_project, "feat(V1): something")

    content, _ = generate_handoff(tmp_project, goal_id="OVERRIDE")

    assert 'goal_id: "OVERRIDE"' in content


def test_generate_handoff_context_excludes_tests(tmp_project: "Path") -> None:
    """Context files should exclude tests/ and .ai/ files."""
    handoff_dir = tmp_project / ".ai" / "handoffs"
    (handoff_dir / "2026-02-09_140000.md").write_text(textwrap.dedent("""\
        ---
        timestamp: "2026-02-09T14:00:00+09:00"
        status: complete
        goal_id: "V1.0"
        ---
        ## Done
        Setup
    """), encoding="utf-8")
    _commit(tmp_project, "chore: add handoff")

    _commit(tmp_project, "feat(V1): add files", {
        "src/main.py": "main()\n",
        "tests/test_main.py": "test_main()\n",
    })

    content, _ = generate_handoff(tmp_project)

    context_section = content.split("## Context Files")[1]
    assert "src/main.py" in context_section
    assert "tests/test_main.py" not in context_section


def test_generate_handoff_no_commits(tmp_project: "Path") -> None:
    """Handoff with no commits since boundary."""
    handoff_dir = tmp_project / ".ai" / "handoffs"
    (handoff_dir / "2026-02-09_140000.md").write_text(textwrap.dedent("""\
        ---
        timestamp: "2026-02-09T14:00:00+09:00"
        status: complete
        goal_id: "V1.0"
        ---
        ## Done
        Setup
    """), encoding="utf-8")
    _commit(tmp_project, "chore: add handoff")

    content, _ = generate_handoff(tmp_project)

    assert "(no commits in this session)" in content


def test_handoff_command_stdout(tmp_project: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI: devf handoff --stdout prints to stdout."""
    from click.testing import CliRunner

    from devf.cli import main

    _commit(tmp_project, "feat(V1): add feature")

    monkeypatch.chdir(tmp_project)
    runner = CliRunner()
    result = runner.invoke(main, ["handoff", "--stdout"])

    assert result.exit_code == 0
    assert "## Done" in result.output


def test_handoff_command_writes_file(tmp_project: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI: devf handoff writes to .ai/handoffs/."""
    from click.testing import CliRunner

    from devf.cli import main

    _commit(tmp_project, "feat(V1): add feature")

    monkeypatch.chdir(tmp_project)
    runner = CliRunner()
    result = runner.invoke(main, ["handoff"])

    assert result.exit_code == 0
    assert "Handoff written to" in result.output

    handoff_dir = tmp_project / ".ai" / "handoffs"
    handoffs = list(handoff_dir.glob("*.md"))
    assert len(handoffs) == 1
    content = handoffs[0].read_text(encoding="utf-8")
    assert "## Done" in content
