"""Tests for git utility functions."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from hast.utils.git import commit_all, get_diff_stat, get_log_since


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit."""
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


def _get_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_commit_all(git_repo: Path) -> None:
    (git_repo / "new.txt").write_text("hello\n", encoding="utf-8")
    new_hash = commit_all(git_repo, "add new file")
    assert new_hash == _get_head(git_repo)
    # Verify the commit message
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=str(git_repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert msg == "add new file"


def test_commit_all_no_changes(git_repo: Path) -> None:
    from hast.core.errors import HastError
    with pytest.raises(HastError):
        commit_all(git_repo, "nothing to commit")


def test_get_diff_stat(git_repo: Path) -> None:
    base = _get_head(git_repo)
    (git_repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add a"],
        cwd=str(git_repo), capture_output=True, check=True,
    )
    stat = get_diff_stat(git_repo, base)
    assert "a.py" in stat


def test_get_diff_stat_no_changes(git_repo: Path) -> None:
    head = _get_head(git_repo)
    stat = get_diff_stat(git_repo, head)
    assert stat == ""


def test_get_log_since(git_repo: Path) -> None:
    base = _get_head(git_repo)
    (git_repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "first commit"],
        cwd=str(git_repo), capture_output=True, check=True,
    )
    (git_repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "second commit"],
        cwd=str(git_repo), capture_output=True, check=True,
    )
    commits = get_log_since(git_repo, base)
    assert len(commits) == 2
    assert commits[0][1] == "first commit"
    assert commits[1][1] == "second commit"


def test_get_log_since_no_commits(git_repo: Path) -> None:
    head = _get_head(git_repo)
    commits = get_log_since(git_repo, head)
    assert commits == []
