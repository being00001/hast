"""Git utilities for hast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Iterable

from hast.core.errors import HastError


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
        raise HastError(proc.stderr.strip() or "git command failed")
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


def get_recent_log(root: Path, n: int = 10) -> list[tuple[str, str]]:
    """Return the last *n* commits as (short_hash, message)."""
    result = run_git(
        ["log", f"-{n}", "--oneline", "--no-decorate"], root, check=False,
    )
    if result.returncode != 0:
        return []
    commits: list[tuple[str, str]] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        commits.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return commits


def git_change_summary(root: Path, since_commit: str | None = None) -> str:
    """Build a formatted change summary string.

    If *since_commit* is provided, shows commits and diff-stat since that commit.
    Otherwise shows the most recent commits.  Always appends working-tree status.
    """
    lines: list[str] = []

    if since_commit:
        commits = get_log_since(root, since_commit)
        if commits:
            lines.append(f"{len(commits)} commits since last session:")
            for short_hash, msg in commits:
                lines.append(f"  {short_hash} {msg}")
        stat = get_diff_stat(root, since_commit)
        if stat:
            # last line of diff stat is the summary ("N files changed, ...")
            stat_lines = stat.splitlines()
            if stat_lines:
                lines.append(stat_lines[-1].strip())
    else:
        commits = get_recent_log(root, n=10)
        if commits:
            lines.append(f"Recent {len(commits)} commits:")
            for short_hash, msg in commits:
                lines.append(f"  {short_hash} {msg}")

    if is_dirty(root):
        lines.append("Working tree: dirty (uncommitted changes)")
    elif lines:
        lines.append("Working tree: clean")

    return "\n".join(lines)


def find_session_boundary(root: Path) -> str | None:
    """Find the commit that marks the end of the previous session.

    Returns the most recent commit that touched ``.ai/handoffs/`` or
    ``.ai/sessions/``, or *None* if no such commit exists.
    """
    result = run_git(
        ["log", "-1", "--format=%H", "--", ".ai/handoffs/", ".ai/sessions/"],
        root, check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def get_full_messages(root: Path, base_commit: str) -> list[tuple[str, str]]:
    """Return ``(subject, body)`` for each commit from *base_commit* to HEAD."""
    result = run_git(
        ["log", "--reverse", "--format=%x00%s%x01%b", f"{base_commit}..HEAD"],
        root, check=False,
    )
    if result.returncode != 0:
        return []
    messages: list[tuple[str, str]] = []
    for block in result.stdout.split("\x00"):
        block = block.strip()
        if not block:
            continue
        parts = block.split("\x01", 1)
        subject = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        if subject:
            messages.append((subject, body))
    return messages


def get_committed_files(root: Path, base_commit: str) -> list[str]:
    """Return files changed in commits between *base_commit* and HEAD."""
    result = run_git(
        ["diff", "--name-only", f"{base_commit}..HEAD"], root, check=False,
    )
    if result.returncode != 0:
        return []
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


# --- Worktree isolation ---


_WORKTREE_DIR = ".worktrees"


def worktree_path(root: Path, goal_id: str) -> Path:
    """Return the worktree path for a goal."""
    safe_id = goal_id.replace("/", "-").replace("\\", "-")
    return root / _WORKTREE_DIR / safe_id


def worktree_create(root: Path, goal_id: str) -> Path:
    """Create an isolated worktree + branch for a goal.

    Returns the worktree directory path.
    """
    wt = worktree_path(root, goal_id)
    branch = f"goal/{goal_id}"

    if wt.exists():
        # Already exists — just return it
        return wt

    wt.parent.mkdir(parents=True, exist_ok=True)
    run_git(["worktree", "add", str(wt), "-b", branch, "HEAD"], root)
    return wt


def worktree_remove(root: Path, goal_id: str) -> None:
    """Remove a goal's worktree and its branch."""
    wt = worktree_path(root, goal_id)
    branch = f"goal/{goal_id}"

    if wt.exists():
        run_git(["worktree", "remove", str(wt), "--force"], root, check=False)

    # Clean up branch
    run_git(["branch", "-D", branch], root, check=False)


def worktree_merge(root: Path, goal_id: str) -> str:
    """Merge a goal branch into the current branch and clean up.

    Returns the new HEAD commit hash.
    """
    branch = f"goal/{goal_id}"
    run_git(["merge", branch, "--no-ff", "-m", f"merge: {goal_id}"], root)
    worktree_remove(root, goal_id)
    return get_head_commit(root)


def worktree_list(root: Path) -> list[dict[str, str]]:
    """List active worktrees with goal info.

    Returns list of dicts with keys: goal_id, path, branch, head.
    """
    result = run_git(["worktree", "list", "--porcelain"], root, check=False)
    if result.returncode != 0:
        return []

    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line[9:]}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]

    if current:
        entries.append(current)

    # Filter to only goal/* branches
    goals: list[dict[str, str]] = []
    prefix = "refs/heads/goal/"
    for entry in entries:
        branch = entry.get("branch", "")
        if branch.startswith(prefix):
            goals.append({
                "goal_id": branch[len(prefix):],
                "path": entry.get("path", ""),
                "branch": branch,
                "head": entry.get("head", "")[:8],
            })
    return goals
