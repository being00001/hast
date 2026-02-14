"""Utilities for parsing LLM output."""

from __future__ import annotations

import re
import os
from dataclasses import dataclass
from pathlib import Path

from devf.core.errors import DevfError


@dataclass(frozen=True)
class FileChange:
    path: str
    content: str


def parse_file_changes(text: str) -> list[FileChange]:
    """Parse file changes from LLM output.
    
    Expects markdown code blocks. Supports loosely formatted headers.
    
    Allowed formats:
    1. ```lang:path/to/file
    2. ```lang path/to/file
    3. ## File: path/to/file ... ```code```
    """
    changes: list[FileChange] = []
    
    # Relaxed Pattern 1: ```[lang][: ]path/to/file
    # Matches:
    # ```python:src/main.py
    # ```python src/main.py
    # ``` src/main.py
    pattern1 = re.compile(r"```(?:\w+)?(?:[:\s]+)([^\n]+)\n(.*?)```", re.DOTALL)
    
    # Pattern 2: Explicit header style
    # ## File: path/to/file
    pattern2 = re.compile(r"##\s*File:\s*([^\n]+)\n\s*```.*?\n(.*?)```", re.DOTALL | re.IGNORECASE)

    # Collect matches from both strategies
    seen_paths = set()

    for pat in [pattern1, pattern2]:
        for match in pat.finditer(text):
            raw_path = match.group(1).strip()
            content = match.group(2)
            
            # Clean path (remove quotes if model hallucinated them)
            path = raw_path.strip("'\"")
            
            if path not in seen_paths:
                changes.append(FileChange(path, content))
                seen_paths.add(path)

    return changes


def apply_file_changes(root: Path, changes: list[FileChange]) -> list[str]:
    """Apply parsed changes to the filesystem safely.
    
    Raises:
        DevfError: If a path traversal attempt is detected.
    """
    applied: list[str] = []
    root_abs = root.resolve()

    for change in changes:
        # 1. Block absolute paths immediately
        if os.path.isabs(change.path):
             raise DevfError(f"Security Alert: Absolute paths not allowed: {change.path}")

        # 2. Resolve target path
        try:
            target_path = (root / change.path).resolve()
        except Exception as e:
            # Could happen if path is malformed
            raise DevfError(f"Invalid path format: {change.path}") from e

        # 3. Jail check: Must start with root_abs
        # Note: We convert to string for robust prefix check
        if not str(target_path).startswith(str(root_abs)):
            raise DevfError(
                f"Security Alert: Path traversal detected! "
                f"Attempted to write outside root: {change.path} -> {target_path}"
            )

        # 4. Safe to write
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(change.content, encoding="utf-8")
        applied.append(str(target_path.relative_to(root_abs)))

    return applied
