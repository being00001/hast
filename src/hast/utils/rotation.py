"""JSONL file rotation utility."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_MAX_AGE_DAYS = 30

KNOWN_JSONL_GLOBS = [
    "runs/*/evidence.jsonl",
    "events/events.jsonl",
    "feedback/notes.jsonl",
    "proposals/notes.jsonl",
    "decisions/evidence.jsonl",
    "immune/audit.jsonl",
    "security/audit.jsonl",
    "queue/events.jsonl",
    "state/operator_actions.jsonl",
    "protocols/inbox/results.jsonl",
]


@dataclass(frozen=True)
class RotationResult:
    original_path: str
    archive_path: str
    size_bytes: int
    reason: str  # "size" | "age" | "size+age"


def _archive_name(relative_parts: tuple[str, ...], timestamp: str) -> str:
    stem = "__".join(relative_parts[:-1])
    original_name = relative_parts[-1]
    base, _, ext = original_name.rpartition(".")
    if not base:
        base = original_name
        ext = ""
    if ext:
        return f"{stem}__{base}.{timestamp}.{ext}"
    return f"{stem}__{base}.{timestamp}"


def _should_rotate(
    path: Path,
    max_size_bytes: int,
    max_age_days: int,
    now: datetime,
) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    stat = path.stat()
    size_exceeded = stat.st_size > max_size_bytes
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=now.tzinfo)
    age_exceeded = (now - mtime) > timedelta(days=max_age_days)
    if size_exceeded and age_exceeded:
        return "size+age"
    if size_exceeded:
        return "size"
    if age_exceeded:
        return "age"
    return None


def discover_jsonl_files(ai_dir: Path) -> list[Path]:
    found: list[Path] = []
    for glob_pattern in KNOWN_JSONL_GLOBS:
        found.extend(sorted(ai_dir.glob(glob_pattern)))
    return found


def rotate_files(
    root: Path,
    *,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> list[RotationResult]:
    """Rotate JSONL files exceeding size or age thresholds."""
    ai_dir = root / ".ai"
    if not ai_dir.is_dir():
        return []

    archive_dir = ai_dir / "archive"
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%dT%H%M%S")
    results: list[RotationResult] = []

    for path in discover_jsonl_files(ai_dir):
        reason = _should_rotate(path, max_size_bytes, max_age_days, now)
        if reason is None:
            continue

        size_bytes = path.stat().st_size
        relative_to_ai = path.relative_to(ai_dir)
        archive_filename = _archive_name(relative_to_ai.parts, ts)
        dest = archive_dir / archive_filename

        if not dry_run:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))

        results.append(
            RotationResult(
                original_path=str(path.relative_to(root)),
                archive_path=str(dest.relative_to(root)),
                size_bytes=size_bytes,
                reason=reason,
            )
        )

    return results
