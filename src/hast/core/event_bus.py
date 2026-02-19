"""Append-only event bus and shadow reducer for async control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


@dataclass(frozen=True)
class EventBusPolicy:
    version: str = "v1"
    enabled: bool = False
    shadow_mode: bool = True
    emit_from_evidence: bool = True
    emit_from_queue: bool = True
    emit_from_orchestrator: bool = True
    auto_reduce_on_emit: bool = False


@dataclass(frozen=True)
class ReplayResult:
    total_events: int
    unique_events: int
    duplicate_events: int
    goal_count: int
    inbox_items: int
    goal_views_path: Path | None
    operator_inbox_path: Path | None


def load_event_bus_policy(root: Path) -> EventBusPolicy:
    path = root / ".ai" / "policies" / "event_bus_policy.yaml"
    if not path.exists():
        return EventBusPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return EventBusPolicy()

    return EventBusPolicy(
        version=_as_str(data.get("version"), "v1"),
        enabled=_as_bool(data.get("enabled"), False),
        shadow_mode=_as_bool(data.get("shadow_mode"), True),
        emit_from_evidence=_as_bool(data.get("emit_from_evidence"), True),
        emit_from_queue=_as_bool(data.get("emit_from_queue"), True),
        emit_from_orchestrator=_as_bool(data.get("emit_from_orchestrator"), True),
        auto_reduce_on_emit=_as_bool(data.get("auto_reduce_on_emit"), False),
    )


def emit_shadow_event(
    root: Path,
    *,
    source: str,
    event_type: str,
    payload: dict[str, Any],
    timestamp: datetime | None = None,
    event_id: str | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    policy = load_event_bus_policy(root)
    if not _source_enabled(policy, source):
        return None

    ts = timestamp if timestamp is not None else datetime.now().astimezone()
    idem = idempotency_key.strip() if isinstance(idempotency_key, str) and idempotency_key.strip() else None
    resolved_event_id = event_id.strip() if isinstance(event_id, str) and event_id.strip() else None
    if resolved_event_id is None:
        if idem is not None:
            resolved_event_id = _stable_event_id(source, event_type, idem)
        else:
            resolved_event_id = f"evt_{uuid4().hex}"

    row = {
        "timestamp": ts.isoformat(),
        "event_id": resolved_event_id,
        "event_type": event_type,
        "source": source,
        "idempotency_key": idem,
        "schema_version": "event_bus.v1",
        "payload": payload,
    }
    path = _events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    if policy.auto_reduce_on_emit:
        replay_event_log(root, write_snapshots=True)
    return resolved_event_id


def replay_event_log(root: Path, *, write_snapshots: bool = True) -> ReplayResult:
    events = load_events(root)
    seen: set[str] = set()
    unique_events: list[dict[str, Any]] = []
    duplicate_count = 0

    for row in events:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            event_id = _stable_event_id(
                str(row.get("source") or "unknown"),
                str(row.get("event_type") or "unknown"),
                json.dumps(row.get("payload") or {}, ensure_ascii=False, sort_keys=True),
            )
            row = dict(row)
            row["event_id"] = event_id
        if event_id in seen:
            duplicate_count += 1
            continue
        seen.add(event_id)
        unique_events.append(row)

    goal_views, inbox = _reduce_events(unique_events)

    goal_views_path: Path | None = None
    operator_inbox_path: Path | None = None
    if write_snapshots:
        goal_views_path = _goal_views_path(root)
        operator_inbox_path = _operator_inbox_path(root)
        goal_views_path.parent.mkdir(parents=True, exist_ok=True)
        operator_inbox_path.parent.mkdir(parents=True, exist_ok=True)

        goal_doc = {
            "version": "v1",
            "event_count": len(unique_events),
            "duplicate_events_ignored": duplicate_count,
            "goals": [goal_views[goal_id] for goal_id in sorted(goal_views)],
        }
        inbox_doc = {
            "version": "v1",
            "event_count": len(unique_events),
            "duplicate_events_ignored": duplicate_count,
            "items": inbox,
        }
        goal_views_path.write_text(
            yaml.safe_dump(goal_doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        operator_inbox_path.write_text(
            yaml.safe_dump(inbox_doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    return ReplayResult(
        total_events=len(events),
        unique_events=len(unique_events),
        duplicate_events=duplicate_count,
        goal_count=len(goal_views),
        inbox_items=len(inbox),
        goal_views_path=goal_views_path,
        operator_inbox_path=operator_inbox_path,
    )


def load_events(root: Path) -> list[dict[str, Any]]:
    path = _events_path(root)
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _reduce_events(events: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    goal_views: dict[str, dict[str, Any]] = {}
    inbox: list[dict[str, Any]] = []

    for row in events:
        event_id = str(row.get("event_id") or "")
        event_type = str(row.get("event_type") or "")
        source = str(row.get("source") or "")
        timestamp = str(row.get("timestamp") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        goal_id = payload.get("goal_id")
        if isinstance(goal_id, str) and goal_id.strip():
            goal_key = goal_id.strip()
            view = goal_views.get(goal_key)
            if view is None:
                view = {
                    "goal_id": goal_key,
                    "event_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "retry_count": 0,
                    "block_count": 0,
                    "escalate_count": 0,
                    "security_incidents": 0,
                    "claim_collision_count": 0,
                    "last_event_type": None,
                    "last_timestamp": None,
                    "last_action_taken": None,
                    "claimed_by": None,
                    "claim_id": None,
                    "claim_expires_at": None,
                }
                goal_views[goal_key] = view
            view["event_count"] = int(view["event_count"]) + 1
            view["last_event_type"] = event_type
            view["last_timestamp"] = timestamp

            action_taken = payload.get("action_taken")
            if isinstance(action_taken, str) and action_taken.strip():
                action = action_taken.strip()
                view["last_action_taken"] = action
                if action == "retry":
                    view["retry_count"] = int(view["retry_count"]) + 1
                elif action == "block":
                    view["block_count"] = int(view["block_count"]) + 1
                elif action == "escalate":
                    view["escalate_count"] = int(view["escalate_count"]) + 1

            success = payload.get("success")
            if isinstance(success, bool):
                if success:
                    view["success_count"] = int(view["success_count"]) + 1
                else:
                    view["failure_count"] = int(view["failure_count"]) + 1

            if str(payload.get("failure_classification") or "") == "security":
                view["security_incidents"] = int(view["security_incidents"]) + 1

            if event_type == "queue_claim_created":
                if isinstance(payload.get("worker_id"), str):
                    view["claimed_by"] = payload.get("worker_id")
                if isinstance(payload.get("claim_id"), str):
                    view["claim_id"] = payload.get("claim_id")
                if isinstance(payload.get("expires_at"), str):
                    view["claim_expires_at"] = payload.get("expires_at")
            elif event_type in {"queue_claim_released", "queue_claim_expired"}:
                view["claimed_by"] = None
                view["claim_id"] = None
                view["claim_expires_at"] = None
            elif event_type == "queue_claim_rejected":
                if str(payload.get("reason_code") or "") == "goal_already_claimed":
                    view["claim_collision_count"] = int(view["claim_collision_count"]) + 1

        inbox_item = _event_to_inbox_item(
            event_id=event_id,
            event_type=event_type,
            source=source,
            timestamp=timestamp,
            payload=payload,
        )
        if inbox_item is not None:
            inbox.append(inbox_item)

    inbox.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "low")),
            str(item.get("timestamp") or ""),
            str(item.get("event_id") or ""),
        )
    )
    return goal_views, inbox


def _event_to_inbox_item(
    *,
    event_id: str,
    event_type: str,
    source: str,
    timestamp: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    goal_id = payload.get("goal_id")
    goal_text = goal_id if isinstance(goal_id, str) and goal_id.strip() else None

    if event_type == "auto_attempt":
        action = str(payload.get("action_taken") or "")
        failure = str(payload.get("failure_classification") or "")
        if action in {"block", "escalate"} or failure == "security":
            reason_code = "security_failure" if failure == "security" else f"action_{action}"
            summary = (
                f"{goal_text or '(none)'} requires operator attention "
                f"(action={action or 'n/a'}, failure={failure or 'n/a'})"
            )
            return {
                "inbox_id": f"inbox-{event_id}",
                "event_id": event_id,
                "event_type": event_type,
                "source": source,
                "goal_id": goal_text,
                "priority": "high" if failure == "security" or action == "block" else "medium",
                "reason_code": reason_code,
                "summary": summary,
                "timestamp": timestamp,
            }

    if event_type == "queue_claim_rejected" and str(payload.get("reason_code") or "") == "goal_already_claimed":
        return {
            "inbox_id": f"inbox-{event_id}",
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "goal_id": goal_text,
            "priority": "medium",
            "reason_code": "claim_collision",
            "summary": f"claim collision on {goal_text or '(none)'}",
            "timestamp": timestamp,
        }

    if event_type == "orchestrate_cycle_blocked":
        return {
            "inbox_id": f"inbox-{event_id}",
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "goal_id": goal_text,
            "priority": "high",
            "reason_code": "baseline_blocked",
            "summary": str(payload.get("reason") or "orchestrate blocked by baseline guard"),
            "timestamp": timestamp,
        }
    return None


def _source_enabled(policy: EventBusPolicy, source: str) -> bool:
    if not policy.enabled or not policy.shadow_mode:
        return False
    if source == "evidence":
        return policy.emit_from_evidence
    if source == "queue":
        return policy.emit_from_queue
    if source == "orchestrator":
        return policy.emit_from_orchestrator
    return True


def _stable_event_id(source: str, event_type: str, token: str) -> str:
    digest = hashlib.sha1(f"{source}|{event_type}|{token}".encode("utf-8")).hexdigest()
    return f"evt_{digest[:24]}"


def _priority_rank(priority: str) -> int:
    if priority == "high":
        return 0
    if priority == "medium":
        return 1
    return 2


def _events_path(root: Path) -> Path:
    return root / ".ai" / "events" / "events.jsonl"


def _goal_views_path(root: Path) -> Path:
    return root / ".ai" / "state" / "goal_views.yaml"


def _operator_inbox_path(root: Path) -> Path:
    return root / ".ai" / "state" / "operator_inbox.yaml"


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
