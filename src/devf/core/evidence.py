"""Evidence logging for auto runs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


def new_run_id() -> str:
    """Create a stable run identifier for evidence grouping."""
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_evidence_row(root: Path, run_id: str, row: dict[str, Any]) -> None:
    """Append one JSONL row to .ai/runs/<run_id>/evidence.jsonl."""
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fp = run_dir / "evidence.jsonl"
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with fp.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
