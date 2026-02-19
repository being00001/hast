"""Post-run summary builder for hast auto --json output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_auto_summary(root: Path, run_id: str, exit_code: int) -> dict[str, Any]:
    """Build machine-readable summary from evidence rows of a completed run."""
    evidence_path = root / ".ai" / "runs" / run_id / "evidence.jsonl"
    rows = _load_evidence_rows(evidence_path)

    return {
        "exit_code": exit_code,
        "run_id": run_id,
        "goals_processed": _aggregate_goals(rows),
        "changed_files": sorted(_aggregate_changed_files(rows)),
        "evidence_summary": _aggregate_evidence(rows),
    }


def _load_evidence_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _aggregate_goals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    goal_last: dict[str, dict[str, Any]] = {}
    for row in rows:
        gid = row.get("goal_id")
        if not gid:
            continue
        goal_last[gid] = row

    result: list[dict[str, Any]] = []
    for gid, last in sorted(goal_last.items()):
        result.append({
            "id": gid,
            "success": last.get("success", False),
            "classification": last.get("classification"),
            "phase": last.get("phase"),
            "action_taken": last.get("action_taken"),
            "risk_score": last.get("risk_score"),
        })
    return result


def _aggregate_changed_files(rows: list[dict[str, Any]]) -> set[str]:
    files: set[str] = set()
    for row in rows:
        cf = row.get("changed_files")
        if isinstance(cf, list):
            files.update(str(f) for f in cf)
    return files


def _aggregate_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = sum(1 for r in rows if r.get("success"))
    classifications: dict[str, int] = {}
    for r in rows:
        cls = str(r.get("classification", "unknown"))
        classifications[cls] = classifications.get(cls, 0) + 1

    return {
        "total_rows": total,
        "successes": successes,
        "failures": total - successes,
        "classifications": classifications,
    }
