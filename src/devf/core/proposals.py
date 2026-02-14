"""Emergent goal proposal inbox helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

from devf.core.errors import DevfError
import yaml


VALID_CATEGORIES = {"risk", "opportunity", "tech_debt", "workflow_friction"}
VALID_LEVELS = {"low", "medium", "high"}
VALID_EFFORT_HINTS = {"xs", "s", "m", "l", "xl"}


def create_proposal_note(
    *,
    source: str,
    category: str,
    impact: str,
    risk: str,
    confidence: float,
    effort_hint: str,
    title: str,
    why_now: str,
    run_id: str | None = None,
    goal_id: str | None = None,
    evidence_refs: list[str] | None = None,
    affected_goals: list[str] | None = None,
) -> dict[str, Any]:
    source_clean = source.strip()
    if not source_clean:
        raise DevfError("proposal source must be non-empty")
    if category not in VALID_CATEGORIES:
        raise DevfError(f"invalid proposal category: {category}")
    if impact not in VALID_LEVELS:
        raise DevfError(f"invalid proposal impact: {impact}")
    if risk not in VALID_LEVELS:
        raise DevfError(f"invalid proposal risk: {risk}")
    if not (0.0 <= confidence <= 1.0):
        raise DevfError("proposal confidence must be between 0 and 1")

    effort = effort_hint.strip().lower()
    if effort not in VALID_EFFORT_HINTS:
        raise DevfError(
            "proposal effort_hint must be one of: xs, s, m, l, xl"
        )

    title_clean = " ".join(title.split())
    why_now_clean = " ".join(why_now.split())
    if not title_clean:
        raise DevfError("proposal title must be non-empty")
    if not why_now_clean:
        raise DevfError("proposal why_now must be non-empty")

    refs = _normalize_string_list(evidence_refs)
    goals = _normalize_string_list(affected_goals)
    fingerprint = build_proposal_fingerprint(
        category=category,
        title=title_clean,
        why_now=why_now_clean,
        affected_goals=goals,
    )
    ts = datetime.now().astimezone()
    proposal_id = f"prop-{ts.strftime('%Y%m%dT%H%M%S%f%z')}-{fingerprint[:8]}"

    return {
        "proposal_id": proposal_id,
        "timestamp": ts.isoformat(),
        "run_id": run_id,
        "goal_id": goal_id,
        "source": source_clean,
        "category": category,
        "impact": impact,
        "risk": risk,
        "confidence": round(float(confidence), 3),
        "effort_hint": effort,
        "title": title_clean,
        "why_now": why_now_clean,
        "evidence_refs": refs,
        "affected_goals": goals,
        "status": "proposed",
        "fingerprint": fingerprint,
    }


def write_proposal_note(root: Path, note: dict[str, Any]) -> Path:
    proposals_dir = root / ".ai" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / "notes.jsonl"
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(note, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_proposal_notes(
    root: Path,
    *,
    window_days: int | None = None,
    category: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    path = root / ".ai" / "proposals" / "notes.jsonl"
    if not path.exists():
        return []

    threshold: datetime | None = None
    if window_days is not None:
        threshold = datetime.now().astimezone() - timedelta(days=window_days)

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        if threshold is not None:
            ts_raw = row.get("timestamp")
            if not isinstance(ts_raw, str):
                continue
            parsed_ts = _parse_iso(ts_raw)
            if parsed_ts is None or parsed_ts < threshold:
                continue

        if category and str(row.get("category")) != category:
            continue
        if status and str(row.get("status")) != status:
            continue
        rows.append(row)

    rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return rows


def load_proposal_backlog(root: Path) -> list[dict[str, Any]]:
    path = root / ".ai" / "proposals" / "backlog.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def build_proposal_fingerprint(
    *,
    category: str,
    title: str,
    why_now: str,
    affected_goals: list[str],
) -> str:
    basis = "|".join(
        [
            category.strip().lower(),
            " ".join(title.lower().split())[:180],
            " ".join(why_now.lower().split())[:180],
            ",".join(sorted(set(affected_goals))),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
