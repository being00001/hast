"""Handoff parsing and selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml

from devf.core.errors import DevfError

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
        raise DevfError("handoff missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise DevfError("handoff frontmatter not terminated")
    _, yaml_block, rest = parts
    data = yaml.safe_load(yaml_block) or {}
    if not isinstance(data, dict):
        raise DevfError("handoff frontmatter must be a mapping")
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
            raise DevfError("handoff timestamp invalid") from exc
    else:
        raise DevfError("handoff timestamp missing")
    if timestamp.tzinfo is None:
        raise DevfError("handoff timestamp missing timezone offset")

    if not isinstance(status, str) or status not in HANDOFF_STATUSES:
        raise DevfError("handoff status invalid")
    # goal_id may be parsed as int/float by YAML (e.g. goal_id: 1).
    if isinstance(goal_id, (int, float)):
        goal_id = str(goal_id)
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise DevfError("handoff goal_id missing")

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
        except DevfError:
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
