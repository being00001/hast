"""Session log generation from git data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from devf.core.errors import DevfError
from devf.core.goals import Goal
from devf.utils.git import get_diff_stat, get_log_since

FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}\.md$")


@dataclass(frozen=True)
class SessionLog:
    path: Path
    goal_id: str
    status: str
    base_commit: str
    changes: str
    commits: list[tuple[str, str]]
    test_summary: str


def generate_session_log(
    root: Path,
    goal: Goal,
    base_commit: str,
    test_output: str,
    status: str = "complete",
) -> str:
    """Build a session log markdown string from git data."""
    diff_stat = get_diff_stat(root, base_commit)
    commits = get_log_since(root, base_commit)
    test_summary = _extract_test_summary(test_output)

    lines = [
        "---",
        f"goal_id: {goal.id}",
        f"status: {status}",
        f"base_commit: {base_commit[:7]}",
        "---",
        "",
        "## Changes",
        diff_stat or "(no changes)",
        "",
        "## Commits",
    ]
    if commits:
        for short_hash, msg in commits:
            lines.append(f"- {short_hash} {msg}")
    else:
        lines.append("(no commits)")
    lines.append("")
    lines.append("## Test Results")
    lines.append(test_summary or "(no output)")
    lines.append("")
    return "\n".join(lines)


def write_session_log(session_dir: Path, content: str) -> Path:
    """Write session log to session_dir/YYYY-MM-DD_HHMMSS.md."""
    session_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).astimezone()
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    path = session_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def find_latest_session(session_dir: Path) -> SessionLog | None:
    """Find the most recent session log by filename sort order."""
    if not session_dir.exists():
        return None

    candidates: list[Path] = []
    for path in session_dir.iterdir():
        if path.is_file() and FILENAME_RE.match(path.name):
            candidates.append(path)

    if not candidates:
        return None

    candidates.sort(key=lambda p: p.name)
    return parse_session(candidates[-1])


def parse_session(path: Path) -> SessionLog:
    """Parse a session log file. Uses simple key: value parsing (no YAML)."""
    text = path.read_text(encoding="utf-8")

    frontmatter, body = _parse_frontmatter(text)
    goal_id = frontmatter.get("goal_id", "")
    status = frontmatter.get("status", "")
    base_commit = frontmatter.get("base_commit", "")

    changes = _extract_section(body, "Changes")
    commits_raw = _extract_section(body, "Commits")
    test_summary = _extract_section(body, "Test Results")

    commits: list[tuple[str, str]] = []
    for line in commits_raw.splitlines():
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]
            parts = line.split(None, 1)
            if parts:
                commits.append((parts[0], parts[1] if len(parts) > 1 else ""))

    return SessionLog(
        path=path,
        goal_id=goal_id,
        status=status,
        base_commit=base_commit,
        changes=changes,
        commits=commits,
        test_summary=test_summary,
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Simple key: value frontmatter parser (no yaml.safe_load)."""
    if not text.startswith("---"):
        raise DevfError("session log missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise DevfError("session log frontmatter not terminated")
    _, raw, body = parts
    data: dict[str, str] = {}
    for line in raw.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data, body.lstrip("\n")


def _extract_section(body: str, name: str) -> str:
    """Extract content under a ## heading."""
    lines: list[str] = []
    in_section = False
    for line in body.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            if line[3:].strip() == name:
                in_section = True
            continue
        if in_section:
            lines.append(line)
    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _extract_test_summary(test_output: str) -> str:
    """Extract pytest-style summary line from test output."""
    for line in reversed(test_output.splitlines()):
        stripped = line.strip()
        if re.search(r"\d+\s+passed", stripped) or re.search(
            r"\d+\s+failed", stripped
        ):
            return stripped
    # Fallback: last non-empty line
    for line in reversed(test_output.splitlines()):
        if line.strip():
            return line.strip()
    return ""
