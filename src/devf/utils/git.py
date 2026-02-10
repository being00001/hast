"""Git utilities for devf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Iterable

from devf.core.errors import DevfError


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


def run_git(args: Iterable[str], root: Path, check: bool = True) -> GitResult:
    cmd = ["git", *args]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise DevfError(proc.stderr.strip() or "git command failed")
    return GitResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def get_head_commit(root: Path) -> str:
    result = run_git(["rev-parse", "HEAD"], root)
    return result.stdout.strip()


def get_commit_time(root: Path, commit: str) -> datetime:
    result = run_git(["show", "-s", "--format=%ct", commit], root)
    epoch = int(result.stdout.strip())
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()


def is_dirty(root: Path) -> bool:
    result = run_git(["status", "--porcelain"], root)
    return bool(result.stdout.strip())


def get_changed_files(root: Path, base_commit: str) -> list[str]:
    diff = run_git(["diff", "--name-only", base_commit], root)
    untracked = run_git(["ls-files", "--others", "--exclude-standard"], root)
    files = set()
    for line in diff.stdout.splitlines():
        if line.strip():
            files.add(line.strip())
    for line in untracked.stdout.splitlines():
        if line.strip():
            files.add(line.strip())
    return sorted(files)


def reset_hard(root: Path, commit: str) -> None:
    run_git(["reset", "--hard", commit], root, check=True)
    run_git(["clean", "-fd"], root, check=True)


def commit_all(root: Path, message: str) -> str:
    """Stage all changes and commit. Return new commit hash."""
    run_git(["add", "-A"], root)
    run_git(["commit", "-m", message], root)
    return get_head_commit(root)


def get_diff_stat(root: Path, base_commit: str) -> str:
    """Return ``git diff --stat base..HEAD``."""
    result = run_git(["diff", "--stat", f"{base_commit}..HEAD"], root)
    return result.stdout.strip()


def get_log_since(root: Path, base_commit: str) -> list[tuple[str, str]]:
    """Return list of (short_hash, message) from base_commit to HEAD."""
    result = run_git(
        ["log", "--oneline", "--reverse", f"{base_commit}..HEAD"], root
    )
    commits: list[tuple[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        short_hash = parts[0]
        msg = parts[1] if len(parts) > 1 else ""
        commits.append((short_hash, msg))
    return commits
