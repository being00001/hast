"""Tests for session log generation and parsing."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

import pytest

from hast.core.session import (
    _extract_test_summary,
    find_latest_session,
    generate_session_log,
    parse_session,
    write_session_log,
)
from hast.core.goals import Goal


SESSION_LOG = textwrap.dedent("""\
    ---
    goal_id: F1.3
    status: complete
    base_commit: abc1234
    ---

    ## Changes
    src/calc.py | 15 +++---

    ## Commits
    - abc1234 feat(F1.3): add error handling
    - def5678 fix(F1.3): handle edge case

    ## Test Results
    11 passed, 0 failed
""")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    (tmp_path / "init.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    return tmp_path


def test_parse_session(tmp_path: Path) -> None:
    path = tmp_path / "2026-02-10_120000.md"
    path.write_text(SESSION_LOG, encoding="utf-8")
    session = parse_session(path)
    assert session.goal_id == "F1.3"
    assert session.status == "complete"
    assert session.base_commit == "abc1234"
    assert "src/calc.py" in session.changes
    assert len(session.commits) == 2
    assert session.commits[0] == ("abc1234", "feat(F1.3): add error handling")
    assert session.test_summary == "11 passed, 0 failed"


def test_find_latest_session(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "2026-02-09_100000.md").write_text(SESSION_LOG, encoding="utf-8")
    later = SESSION_LOG.replace("F1.3", "F1.4")
    (sessions_dir / "2026-02-10_120000.md").write_text(later, encoding="utf-8")

    session = find_latest_session(sessions_dir)
    assert session is not None
    assert session.goal_id == "F1.4"


def test_find_latest_session_empty(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    assert find_latest_session(sessions_dir) is None


def test_find_latest_session_no_dir(tmp_path: Path) -> None:
    assert find_latest_session(tmp_path / "nonexistent") is None


def test_write_session_log(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    path = write_session_log(sessions_dir, "test content")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "test content"
    assert path.parent == sessions_dir
    assert path.name.endswith(".md")


def test_generate_session_log(git_repo: Path) -> None:
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(git_repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    (git_repo / "src").mkdir()
    (git_repo / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat(F1.3): add calc"],
        cwd=str(git_repo), capture_output=True, check=True,
    )

    goal = Goal(id="F1.3", title="Add calc", status="active")
    log = generate_session_log(git_repo, goal, base, "5 passed, 0 failed\n")
    assert "goal_id: F1.3" in log
    assert "status: complete" in log
    assert "calc.py" in log
    assert "feat(F1.3): add calc" in log
    assert "5 passed, 0 failed" in log


def test_extract_test_summary_pytest() -> None:
    output = "collected 11 items\n\n... lots of output ...\n\n11 passed, 0 failed in 1.2s\n"
    assert _extract_test_summary(output) == "11 passed, 0 failed in 1.2s"


def test_extract_test_summary_failures() -> None:
    output = "FAILURES\n\n...\n\n3 failed, 8 passed in 2.1s\n"
    assert "3 failed" in _extract_test_summary(output)


def test_extract_test_summary_empty() -> None:
    assert _extract_test_summary("") == ""


def test_extract_test_summary_fallback() -> None:
    output = "echo ok\nok\n"
    assert _extract_test_summary(output) == "ok"


def test_parse_session_no_frontmatter(tmp_path: Path) -> None:
    from hast.core.errors import DevfError
    path = tmp_path / "bad.md"
    path.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(DevfError, match="missing frontmatter"):
        parse_session(path)


def test_find_latest_session_ignores_non_matching(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "random_notes.md").write_text("not a session\n", encoding="utf-8")
    (sessions_dir / "2026-02-10_120000.md").write_text(SESSION_LOG, encoding="utf-8")
    session = find_latest_session(sessions_dir)
    assert session is not None
    assert session.goal_id == "F1.3"
