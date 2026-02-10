"""Filesystem helpers."""

from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".ai").is_dir():
            return parent
    return None


def ensure_ai_dir(root: Path) -> Path:
    return root / ".ai"
