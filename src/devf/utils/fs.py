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


def normalize_path(path_str: str, root: Path) -> str:
    """Normalize a path string to be relative to root.
    
    Handles:
    - ./prefix
    - Backslashes
    - Absolute paths (if within root)
    - Redundant slashes
    """
    # Replace backslashes
    p = path_str.replace("\\", "/")
    
    # Create Path object
    path_obj = Path(p)
    
    # If absolute, try to make it relative
    if path_obj.is_absolute():
        try:
            return str(path_obj.relative_to(root.resolve()))
        except ValueError:
            # Not under root, return as is (will likely fail exists check)
            return p
            
    # If it starts with root directory name, strip it
    # e.g. "my_project/src/main.py" -> "src/main.py"
    parts = list(path_obj.parts)
    if parts and parts[0] == root.name:
        return str(Path(*parts[1:]))
        
    # Clean up ./ and ../
    return str(Path(p))
