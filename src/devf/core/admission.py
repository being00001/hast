"""Proposal admission and promotion engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from devf.core.admission_policy import load_admission_policy
from devf.core.proposals import load_proposal_notes

_LEVEL_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class AdmissionSummary:
    total: int
    accepted: int
    deferred: int
    rejected: int
    goals_added: int
    backlog_path: Path


def promote_proposals(
    root: Path,
    *,
    window_days: int,
    max_active: int,
) -> AdmissionSummary:
    policy = load_admission_policy(root)
    notes = load_proposal_notes(root, window_days=window_days)
    groups = _aggregate_notes(notes)

    if not policy.enabled:
        disabled_rows = [
            {
                "proposal_id": row["latest_proposal_id"],
                "fingerprint": row["fingerprint"],
                "title": row["title"],
                "category": row["category"],
                "max_impact": row["max_impact"],
                "max_risk": row["max_risk"],
                "count": row["count"],
                "avg_confidence": row["avg_confidence"],
                "status": "deferred",
                "reason_code": "admission_policy_disabled",
                "promoted_goal_id": None,
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "evaluated_at": datetime.now().astimezone().isoformat(),
                "evidence_refs": row["evidence_refs"],
                "note_ids": row["note_ids"],
            }
            for row in groups
        ]
        backlog_path = save_proposal_backlog(root, disabled_rows)
        return AdmissionSummary(
            total=len(disabled_rows),
            accepted=0,
            deferred=len(disabled_rows),
            rejected=0,
            goals_added=0,
            backlog_path=backlog_path,
        )

    goals_path = root / ".ai" / "goals.yaml"
    goals_data = yaml.safe_load(goals_path.read_text(encoding="utf-8")) if goals_path.exists() else {}
    if not isinstance(goals_data, dict):
        goals_data = {}
    raw_goals = goals_data.get("goals", [])
    if not isinstance(raw_goals, list):
        raw_goals = []

    root_goal = _ensure_root_goal(
        raw_goals,
        root_goal_id=policy.promotion.goal_root_id,
    )
    existing_keys = _collect_existing_proposal_fingerprints(raw_goals)
    active_slots = max(0, max_active - _count_active_proposal_goals(root_goal))
    fast_track_overflow = policy.promotion.max_fast_track_overflow

    outcomes: list[dict[str, Any]] = []
    goals_added = 0
    next_index = _next_child_index(root_goal.get("children"), prefix=f"{policy.promotion.goal_root_id}.")
    now = datetime.now().astimezone()

    for item in sorted(groups, key=_priority_key, reverse=True):
        reason_code = ""
        status = "deferred"
        promoted_goal_id: str | None = None

        fingerprint = str(item["fingerprint"])
        max_risk = str(item["max_risk"])
        high_risk = max_risk == "high"
        fast_track = high_risk and policy.promotion.high_risk_fast_track

        if fingerprint in existing_keys:
            status = "rejected"
            reason_code = "duplicate_existing_goal"
        elif item["age_days"] > policy.promotion.ttl_days:
            status = "rejected"
            reason_code = "expired_ttl"
        elif (
            not fast_track
            and int(item["count"]) < policy.promotion.min_frequency
        ):
            status = "deferred"
            reason_code = "below_min_frequency"
        elif (
            not fast_track
            and float(item["avg_confidence"]) < policy.promotion.min_confidence
        ):
            status = "deferred"
            reason_code = "below_min_confidence"
        elif active_slots <= 0:
            if fast_track and fast_track_overflow > 0:
                status = "accepted"
                reason_code = "accepted_fast_track_overflow"
                fast_track_overflow -= 1
            else:
                status = "deferred"
                reason_code = "active_goal_budget_exceeded"
        else:
            status = "accepted"
            reason_code = "accepted_standard"

        if (
            status == "accepted"
            and goals_added < policy.promotion.max_promote_per_run
        ):
            promoted_goal_id = f"{policy.promotion.goal_root_id}.{next_index}"
            next_index += 1
            active_slots = max(0, active_slots - 1)
            goal = {
                "id": promoted_goal_id,
                "title": f"Resolve proposal: {str(item['title'])[:80]}",
                "status": "active",
                "phase": "plan",
                "owner_agent": policy.promotion.owner_agent,
                "proposal_id": item["latest_proposal_id"],
                "proposal_fingerprint": fingerprint,
                "proposal_category": item["category"],
                "proposal_impact": item["max_impact"],
                "proposal_risk": item["max_risk"],
                "notes": (
                    f"reason_code: {reason_code}\n"
                    f"why_now: {item['why_now']}\n"
                    f"evidence_refs: {', '.join(item['evidence_refs'])}"
                ),
            }
            _append_child_goal(root_goal, goal)
            existing_keys.add(fingerprint)
            goals_added += 1
        elif status == "accepted":
            status = "deferred"
            reason_code = "max_promote_per_run_exceeded"

        outcomes.append(
            {
                "proposal_id": item["latest_proposal_id"],
                "fingerprint": fingerprint,
                "title": item["title"],
                "category": item["category"],
                "max_impact": item["max_impact"],
                "max_risk": item["max_risk"],
                "count": item["count"],
                "avg_confidence": item["avg_confidence"],
                "status": status,
                "reason_code": reason_code,
                "promoted_goal_id": promoted_goal_id,
                "first_seen": item["first_seen"],
                "last_seen": item["last_seen"],
                "evaluated_at": now.isoformat(),
                "evidence_refs": item["evidence_refs"],
                "note_ids": item["note_ids"],
            }
        )

    goals_data["goals"] = raw_goals
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text(yaml.safe_dump(goals_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    backlog_path = save_proposal_backlog(root, outcomes)
    accepted = sum(1 for row in outcomes if row["status"] == "accepted")
    deferred = sum(1 for row in outcomes if row["status"] == "deferred")
    rejected = sum(1 for row in outcomes if row["status"] == "rejected")
    return AdmissionSummary(
        total=len(outcomes),
        accepted=accepted,
        deferred=deferred,
        rejected=rejected,
        goals_added=goals_added,
        backlog_path=backlog_path,
    )


def save_proposal_backlog(root: Path, rows: list[dict[str, Any]]) -> Path:
    proposals_dir = root / ".ai" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / "backlog.yaml"
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "items": rows,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _aggregate_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        fingerprint = str(note.get("fingerprint") or "").strip()
        if not fingerprint:
            continue
        grouped.setdefault(fingerprint, []).append(note)

    now = datetime.now().astimezone()
    out: list[dict[str, Any]] = []
    for fingerprint, rows in grouped.items():
        sorted_rows = sorted(rows, key=lambda row: str(row.get("timestamp") or ""))
        latest = sorted_rows[-1]
        confidences = [float(row.get("confidence", 0.0)) for row in rows if _is_number(row.get("confidence"))]
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        max_impact = _max_level([str(row.get("impact") or "low") for row in rows])
        max_risk = _max_level([str(row.get("risk") or "low") for row in rows])
        first_seen = str(sorted_rows[0].get("timestamp") or "")
        last_seen = str(sorted_rows[-1].get("timestamp") or "")
        age_days = _age_days(now, last_seen)

        evidence_refs: list[str] = []
        seen_ref: set[str] = set()
        for row in rows:
            refs = row.get("evidence_refs", [])
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                cleaned = ref.strip()
                if not cleaned or cleaned in seen_ref:
                    continue
                seen_ref.add(cleaned)
                evidence_refs.append(cleaned)

        out.append(
            {
                "fingerprint": fingerprint,
                "latest_proposal_id": str(latest.get("proposal_id") or ""),
                "title": str(latest.get("title") or ""),
                "why_now": str(latest.get("why_now") or ""),
                "category": str(latest.get("category") or "workflow_friction"),
                "count": len(rows),
                "avg_confidence": avg_conf,
                "max_impact": max_impact,
                "max_risk": max_risk,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "age_days": age_days,
                "evidence_refs": evidence_refs,
                "note_ids": [
                    str(row.get("proposal_id"))
                    for row in sorted_rows
                    if row.get("proposal_id")
                ],
            }
        )
    return out


def _priority_key(row: dict[str, Any]) -> tuple[int, int, int, float, int, str]:
    return (
        _LEVEL_RANK.get(str(row.get("max_risk") or "low"), 0),
        _LEVEL_RANK.get(str(row.get("max_impact") or "low"), 0),
        int(row.get("count") or 0),
        float(row.get("avg_confidence") or 0.0),
        -int(row.get("age_days") or 0),
        str(row.get("latest_proposal_id") or ""),
    )


def _ensure_root_goal(raw_goals: list[dict[str, Any]], root_goal_id: str) -> dict[str, Any]:
    found = _find_goal_dict(raw_goals, root_goal_id)
    if found is not None:
        if not isinstance(found.get("children"), list):
            found["children"] = []
        return found

    created = {
        "id": root_goal_id,
        "title": "Proposal Admission Program",
        "status": "active",
        "notes": "Auto-generated by devfork propose promote.",
        "children": [],
    }
    raw_goals.append(created)
    return created


def _find_goal_dict(raw_goals: list[dict[str, Any]], goal_id: str) -> dict[str, Any] | None:
    for goal in raw_goals:
        if not isinstance(goal, dict):
            continue
        if goal.get("id") == goal_id:
            return goal
        children = goal.get("children")
        if isinstance(children, list):
            found = _find_goal_dict(children, goal_id)
            if found is not None:
                return found
    return None


def _collect_existing_proposal_fingerprints(raw_goals: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for goal in raw_goals:
        if not isinstance(goal, dict):
            continue
        value = goal.get("proposal_fingerprint")
        if isinstance(value, str) and value.strip():
            keys.add(value.strip())
        children = goal.get("children")
        if isinstance(children, list):
            keys.update(_collect_existing_proposal_fingerprints(children))
    return keys


def _count_active_proposal_goals(root_goal: dict[str, Any]) -> int:
    children = root_goal.get("children")
    if not isinstance(children, list):
        return 0
    count = 0
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("status") == "active" and child.get("proposal_fingerprint"):
            count += 1
    return count


def _append_child_goal(root_goal: dict[str, Any], goal: dict[str, Any]) -> None:
    children = root_goal.get("children")
    if not isinstance(children, list):
        children = []
        root_goal["children"] = children
    children.append(goal)


def _next_child_index(children: Any, prefix: str) -> int:
    if not isinstance(children, list):
        return 1
    mx = 0
    for child in children:
        if not isinstance(child, dict):
            continue
        goal_id = child.get("id")
        if not isinstance(goal_id, str) or not goal_id.startswith(prefix):
            continue
        suffix = goal_id[len(prefix):]
        if suffix.isdigit():
            mx = max(mx, int(suffix))
    return mx + 1


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float))


def _max_level(values: list[str]) -> str:
    selected = "low"
    for value in values:
        level = value if value in _LEVEL_RANK else "low"
        if _LEVEL_RANK[level] > _LEVEL_RANK[selected]:
            selected = level
    return selected


def _age_days(now: datetime, last_seen: str) -> int:
    try:
        parsed = datetime.fromisoformat(last_seen)
    except ValueError:
        return 10_000
    delta = now - parsed
    return max(0, int(delta.total_seconds() // 86400))
