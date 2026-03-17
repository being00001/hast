"""Handoff parsing and selection."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

from hast.core.errors import HastError

HANDOFF_STATUSES = {"complete", "failed", "blocked"}
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(?:_\d+)?\.md$")


@dataclass(frozen=True)
class Handoff:
    path: Path
    timestamp: datetime
    status: str
    goal_id: str
    sections: dict[str, list[str]]


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise HastError("handoff missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise HastError("handoff frontmatter not terminated")
    _, yaml_block, rest = parts
    data = yaml.safe_load(yaml_block) or {}
    if not isinstance(data, dict):
        raise HastError("handoff frontmatter must be a mapping")
    return data, rest.lstrip("\n")


def _parse_sections(body: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is None:
            continue
        stripped = line.rstrip()
        if stripped:
            if stripped.startswith("- "):
                stripped = stripped[2:].strip()
            sections[current].append(stripped)
    return sections


def parse_handoff(path: Path) -> Handoff:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(text)
    timestamp_raw = frontmatter.get("timestamp")
    status = frontmatter.get("status")
    goal_id = frontmatter.get("goal_id")

    # YAML auto-parses unquoted ISO timestamps as datetime objects.
    # Accept both str and datetime.
    if isinstance(timestamp_raw, datetime):
        timestamp = timestamp_raw
    elif isinstance(timestamp_raw, str):
        try:
            timestamp = datetime.fromisoformat(timestamp_raw)
        except ValueError as exc:
            raise HastError("handoff timestamp invalid") from exc
    else:
        raise HastError("handoff timestamp missing")
    if timestamp.tzinfo is None:
        raise HastError("handoff timestamp missing timezone offset")

    if not isinstance(status, str) or status not in HANDOFF_STATUSES:
        raise HastError("handoff status invalid")
    # goal_id may be parsed as int/float by YAML (e.g. goal_id: 1).
    if isinstance(goal_id, (int, float)):
        goal_id = str(goal_id)
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise HastError("handoff goal_id missing")

    sections = _parse_sections(body)
    return Handoff(
        path=path,
        timestamp=timestamp,
        status=status,
        goal_id=goal_id,
        sections=sections,
    )


def find_latest_handoff(
    handoff_dir: Path, since: datetime | None
) -> Handoff | None:
    if not handoff_dir.exists():
        return None

    candidates: list[Handoff] = []
    for path in handoff_dir.iterdir():
        if not path.is_file() or not FILENAME_RE.match(path.name):
            continue
        if since is not None:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=since.tzinfo)
            if mtime <= since:
                continue
        try:
            handoff = parse_handoff(path)
        except HastError:
            continue
        candidates.append(handoff)

    if not candidates:
        return None

    candidates.sort(key=lambda h: (h.path.name,))
    return candidates[-1]


def extract_section_lines(handoff: Handoff | None, name: str) -> list[str]:
    if handoff is None:
        return []
    return handoff.sections.get(name, [])


def parse_context_files(lines: list[str]) -> list[str]:
    files: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        elif stripped[0].isdigit():
            parts = stripped.split(".", 1)
            if len(parts) == 2:
                stripped = parts[1].strip()
        if stripped:
            files.append(stripped)
    return files


# --- Handoff generation from git data ---

_GOAL_RE = re.compile(r"^\w+\(([^)]+)\):")


def generate_handoff(root: Path, goal_id: str | None = None) -> tuple[str, str]:
    """Auto-generate a handoff document from git data.

    Returns ``(content, filename)`` where *filename* is ``YYYY-MM-DD_HHMMSS.md``.
    """
    from hast.utils.git import (
        find_session_boundary,
        get_committed_files,
        get_diff_stat,
        get_full_messages,
        get_log_since,
        get_recent_log,
    )

    base = find_session_boundary(root)

    if base is not None:
        commits = get_log_since(root, base)
        diff_stat = get_diff_stat(root, base)
        full_messages = get_full_messages(root, base)
        committed_files = get_committed_files(root, base)
    else:
        # First session — no previous handoff/session exists.
        commits = list(reversed(get_recent_log(root, n=50)))
        diff_stat = ""
        full_messages = []
        committed_files = []

    if goal_id is None:
        goal_id = _detect_goal_id(commits)

    now = datetime.now(tz=timezone.utc).astimezone()
    ts = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    ts = ts[:-2] + ":" + ts[-2:]  # +0900 → +09:00
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"

    lines: list[str] = [
        "---",
        f'timestamp: "{ts}"',
        "status: complete",
        f'goal_id: "{goal_id or "UNKNOWN"}"',
        "---",
        "",
        "## Done",
    ]
    if commits:
        for _, msg in commits:
            lines.append(f"- {msg}")
    else:
        lines.append("(no commits in this session)")
    lines.append("")

    lines.append("## Key Decisions")
    decisions = _extract_decisions(full_messages)
    if decisions:
        for d in decisions:
            lines.append(f"- {d}")
    else:
        lines.append("(none recorded in commit messages)")
    lines.append("")

    lines.append("## Changed Files")
    lines.append(diff_stat if diff_stat else "(no changes)")
    lines.append("")

    lines.append("## Next")
    next_task = _find_next_task(root, goal_id)
    lines.append(next_task if next_task else "(check goals.yaml)")
    lines.append("")

    lines.append("## Context Files")
    context = [
        f for f in committed_files
        if not f.startswith("tests/") and not f.startswith(".ai/")
    ]
    if context:
        for i, f in enumerate(context, 1):
            lines.append(f"{i}. {f}")
    else:
        lines.append("(none)")
    lines.append("")

    return "\n".join(lines), filename


def _detect_goal_id(commits: list[tuple[str, str]]) -> str | None:
    """Extract the most frequent goal_id from conventional commit messages."""
    ids: list[str] = []
    for _, msg in commits:
        m = _GOAL_RE.match(msg)
        if m:
            ids.append(m.group(1))
    if not ids:
        return None
    return Counter(ids).most_common(1)[0][0]


def _extract_decisions(full_messages: list[tuple[str, str]]) -> list[str]:
    """Extract decision-like lines from commit message bodies."""
    decisions: list[str] = []
    for _, body in full_messages:
        if not body:
            continue
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("Co-Authored"):
                decisions.append(line)
    return decisions


def _find_next_task(root: Path, current_goal_id: str | None) -> str | None:
    """Find the next active/pending goal after *current_goal_id* in goals.yaml."""
    from hast.core.goals import iter_goals, load_goals

    goals_path = root / ".ai" / "goals.yaml"
    if not goals_path.exists():
        return None
    goals = load_goals(goals_path)
    if not goals:
        return None

    if current_goal_id is None:
        for node in iter_goals(goals):
            if node.goal.status in ("active", "pending"):
                return f"{node.goal.id} — {node.goal.title}"
        return None

    found_current = False
    for node in iter_goals(goals):
        if node.goal.id == current_goal_id:
            found_current = True
            continue
        if found_current and node.goal.status in ("active", "pending"):
            return f"{node.goal.id} — {node.goal.title}"
    return None
