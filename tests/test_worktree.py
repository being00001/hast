"""Tests for git worktree isolation."""

from __future__ import annotations

from pathlib import Path
import subprocess

from hast.utils.git import (
    get_head_commit,
    worktree_create,
    worktree_list,
    worktree_merge,
    worktree_path,
    worktree_remove,
)


def test_worktree_path(tmp_project: Path) -> None:
    assert worktree_path(tmp_project, "V1.1") == tmp_project / ".worktrees" / "V1.1"


def test_worktree_path_sanitizes_slash(tmp_project: Path) -> None:
    assert worktree_path(tmp_project, "V1/sub") == tmp_project / ".worktrees" / "V1-sub"


def test_worktree_create_and_remove(tmp_project: Path) -> None:
    wt = worktree_create(tmp_project, "G1")
    assert wt.exists()
    assert (wt / ".ai" / "config.yaml").exists()  # has project files

    # Branch exists
    result = subprocess.run(
        ["git", "branch", "--list", "goal/G1"],
        cwd=str(tmp_project), capture_output=True, text=True,
    )
    assert "goal/G1" in result.stdout

    worktree_remove(tmp_project, "G1")
    assert not wt.exists()


def test_worktree_create_idempotent(tmp_project: Path) -> None:
    wt1 = worktree_create(tmp_project, "G2")
    wt2 = worktree_create(tmp_project, "G2")
    assert wt1 == wt2
    assert wt1.exists()
    worktree_remove(tmp_project, "G2")


def test_worktree_isolation(tmp_project: Path) -> None:
    """Changes in worktree should not affect main repo."""
    wt = worktree_create(tmp_project, "G3")

    # Make a change in worktree
    (wt / "new_file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "worktree change"],
        cwd=str(wt), capture_output=True, check=True,
    )

    # Main repo should NOT have the file
    assert not (tmp_project / "new_file.txt").exists()

    worktree_remove(tmp_project, "G3")


def test_worktree_merge(tmp_project: Path) -> None:
    """Merge should bring worktree changes into main."""
    wt = worktree_create(tmp_project, "G4")
    main_head = get_head_commit(tmp_project)

    # Commit a change in worktree
    (wt / "feature.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add feature"],
        cwd=str(wt), capture_output=True, check=True,
    )

    new_head = worktree_merge(tmp_project, "G4")
    assert new_head != main_head
    assert (tmp_project / "feature.py").exists()

    # Worktree and branch should be cleaned up
    assert not wt.exists()
    result = subprocess.run(
        ["git", "branch", "--list", "goal/G4"],
        cwd=str(tmp_project), capture_output=True, text=True,
    )
    assert "goal/G4" not in result.stdout


def test_worktree_list_empty(tmp_project: Path) -> None:
    entries = worktree_list(tmp_project)
    assert entries == []


def test_worktree_list_with_entries(tmp_project: Path) -> None:
    worktree_create(tmp_project, "A1")
    worktree_create(tmp_project, "A2")

    entries = worktree_list(tmp_project)
    goal_ids = [e["goal_id"] for e in entries]
    assert "A1" in goal_ids
    assert "A2" in goal_ids

    worktree_remove(tmp_project, "A1")
    worktree_remove(tmp_project, "A2")
