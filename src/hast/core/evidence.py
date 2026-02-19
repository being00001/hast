"""Evidence logging for auto runs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from hast.core.control_plane_contract import validate_evidence_row
from hast.core.event_bus import emit_shadow_event


def new_run_id() -> str:
    """Create a stable run identifier for evidence grouping."""
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_evidence_row(root: Path, run_id: str, row: dict[str, Any]) -> None:
    """Append one JSONL row to .ai/runs/<run_id>/evidence.jsonl."""
    result = validate_evidence_row(row)
    materialized = dict(result.normalized_row)
    if result.warnings:
        materialized["contract_warnings"] = list(result.warnings)

    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fp = run_dir / "evidence.jsonl"
    line = json.dumps(materialized, ensure_ascii=False, sort_keys=True)
    with fp.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    event_type = str(materialized.get("event_type") or "evidence_row")
    emit_shadow_event(
        root,
        source="evidence",
        event_type=event_type,
        payload=materialized,
        timestamp=_as_iso_datetime(materialized.get("timestamp")),
        idempotency_key=_event_idempotency_key(run_id, materialized),
    )


def _event_idempotency_key(run_id: str, row: dict[str, Any]) -> str:
    goal_id = str(row.get("goal_id") or "")
    event_type = str(row.get("event_type") or "")
    attempt = str(row.get("attempt") or "")
    action_taken = str(row.get("action_taken") or "")
    phase = str(row.get("phase") or "")
    return "|".join([run_id, goal_id, phase, attempt, event_type, action_taken])


def _as_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None
