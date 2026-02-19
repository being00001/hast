"""Operator inbox policy-action loop (Wave 9C)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import yaml

from hast.core.errors import DevfError
from hast.core.event_bus import emit_shadow_event
from hast.core.goals import ALLOWED_STATUSES, update_goal_status

_RESOLVING_ACTIONS = {"approve", "reject"}
_ALLOWED_ACTIONS = _RESOLVING_ACTIONS | {"defer"}


@dataclass(frozen=True)
class OperatorInboxPolicy:
    version: str = "v1"
    default_top_k: int = 10
    transitions: dict[str, dict[str, list[str]]] | None = None


@dataclass(frozen=True)
class InboxSummary:
    total_items: int
    unresolved_items: int
    resolved_items: int
    high_priority_unresolved: int
    by_reason_code: dict[str, int]
    top_items: list[dict[str, Any]]


@dataclass(frozen=True)
class ActionResult:
    inbox_id: str
    action: str
    operator_id: str
    reason_code: str
    goal_id: str | None
    goal_status: str | None
    resolved: bool
    actions_path: Path


def load_operator_inbox_policy(root: Path) -> OperatorInboxPolicy:
    path = root / ".ai" / "policies" / "operator_inbox_policy.yaml"
    if not path.exists():
        return OperatorInboxPolicy(version="v1", default_top_k=10, transitions=_default_transitions())

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return OperatorInboxPolicy(version="v1", default_top_k=10, transitions=_default_transitions())

    transitions = data.get("transitions")
    normalized_transitions = _default_transitions()
    if isinstance(transitions, dict):
        normalized_transitions = _normalize_transition_rules(transitions, fallback=normalized_transitions)

    return OperatorInboxPolicy(
        version=_as_str(data.get("version"), "v1"),
        default_top_k=_bounded_int(data.get("default_top_k"), default=10, min_value=1, max_value=100),
        transitions=normalized_transitions,
    )


def list_inbox_items(root: Path, *, include_resolved: bool = False) -> list[dict[str, Any]]:
    items = _load_inbox_items(root)
    latest_actions = _latest_actions_by_inbox(root)
    enriched: list[dict[str, Any]] = []

    for item in items:
        inbox_id = str(item.get("inbox_id") or "").strip()
        action_row = latest_actions.get(inbox_id)
        resolved = False
        latest_action = None
        if action_row is not None:
            latest_action = str(action_row.get("action") or "").strip()
            resolved = latest_action in _RESOLVING_ACTIONS

        merged = dict(item)
        merged["latest_action"] = latest_action
        merged["resolved"] = resolved
        if action_row is not None:
            merged["resolved_at"] = action_row.get("timestamp")
            merged["resolved_by"] = action_row.get("operator_id")
            merged["resolution_reason"] = action_row.get("reason")
        if include_resolved or not resolved:
            enriched.append(merged)

    return sorted(
        enriched,
        key=lambda row: (
            _priority_rank(str(row.get("priority") or "low")),
            -_timestamp_key(str(row.get("timestamp") or "")),
            str(row.get("inbox_id") or ""),
        ),
    )


def summarize_inbox(root: Path, *, top_k: int | None = None) -> InboxSummary:
    policy = load_operator_inbox_policy(root)
    effective_top_k = top_k if top_k is not None else policy.default_top_k
    effective_top_k = _bounded_int(effective_top_k, default=policy.default_top_k, min_value=1, max_value=100)
    items_all = list_inbox_items(root, include_resolved=True)
    items_open = [item for item in items_all if not bool(item.get("resolved"))]
    by_reason: dict[str, int] = {}
    high_priority = 0
    for item in items_open:
        reason = str(item.get("reason_code") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if str(item.get("priority") or "") == "high":
            high_priority += 1

    return InboxSummary(
        total_items=len(items_all),
        unresolved_items=len(items_open),
        resolved_items=len(items_all) - len(items_open),
        high_priority_unresolved=high_priority,
        by_reason_code=by_reason,
        top_items=items_open[:effective_top_k],
    )


def apply_inbox_action(
    root: Path,
    *,
    inbox_id: str,
    action: str,
    operator_id: str,
    reason: str = "",
    goal_status: str | None = None,
) -> ActionResult:
    inbox_key = inbox_id.strip()
    if not inbox_key:
        raise DevfError("inbox_id is required")
    action_token = action.strip().lower()
    if action_token not in _ALLOWED_ACTIONS:
        raise DevfError(f"invalid action: {action}")
    operator_key = operator_id.strip()
    if not operator_key:
        raise DevfError("operator_id is required")
    if goal_status is not None and goal_status not in ALLOWED_STATUSES:
        raise DevfError(f"invalid goal_status: {goal_status}")

    items = _load_inbox_items(root)
    selected = next((item for item in items if str(item.get("inbox_id") or "") == inbox_key), None)
    if selected is None:
        raise DevfError(f"inbox item not found: {inbox_key}")

    latest = _latest_actions_by_inbox(root).get(inbox_key)
    if latest is not None and str(latest.get("action") or "") in _RESOLVING_ACTIONS:
        raise DevfError(f"inbox item already resolved: {inbox_key}")

    reason_code = str(selected.get("reason_code") or "unknown")
    goal_id = _nullable_str(selected.get("goal_id"))
    if goal_status is not None:
        _ensure_authorized_transition(
            root,
            reason_code=reason_code,
            action=action_token,
            target_status=goal_status,
        )
        if goal_id is None:
            raise DevfError("goal_status transition requested but inbox item has no goal_id")
        update_goal_status(root / ".ai" / "goals.yaml", goal_id, goal_status)

    row = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "inbox_id": inbox_key,
        "action": action_token,
        "operator_id": operator_key,
        "reason_code": reason_code,
        "goal_id": goal_id,
        "goal_status": goal_status,
        "reason": reason.strip() or None,
        "resolved": action_token in _RESOLVING_ACTIONS,
    }
    actions_path = _actions_path(root)
    actions_path.parent.mkdir(parents=True, exist_ok=True)
    with actions_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    emit_shadow_event(
        root,
        source="operator",
        event_type="operator_inbox_action",
        payload=row,
        idempotency_key=f"{inbox_key}|{action_token}|{operator_key}|{row['timestamp']}",
    )

    return ActionResult(
        inbox_id=inbox_key,
        action=action_token,
        operator_id=operator_key,
        reason_code=reason_code,
        goal_id=goal_id,
        goal_status=goal_status,
        resolved=action_token in _RESOLVING_ACTIONS,
        actions_path=actions_path,
    )


def _ensure_authorized_transition(
    root: Path,
    *,
    reason_code: str,
    action: str,
    target_status: str,
) -> None:
    policy = load_operator_inbox_policy(root)
    transitions = policy.transitions or _default_transitions()
    action_rules = transitions.get(reason_code)
    if not isinstance(action_rules, dict):
        raise DevfError(
            f"unauthorized transition: reason_code={reason_code} action={action} status={target_status}"
        )
    allowed_statuses = action_rules.get(action)
    if not isinstance(allowed_statuses, list) or target_status not in allowed_statuses:
        raise DevfError(
            f"unauthorized transition: reason_code={reason_code} action={action} status={target_status}"
        )


def _load_inbox_items(root: Path) -> list[dict[str, Any]]:
    path = root / ".ai" / "state" / "operator_inbox.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _latest_actions_by_inbox(root: Path) -> dict[str, dict[str, Any]]:
    path = _actions_path(root)
    if not path.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        inbox_id = str(row.get("inbox_id") or "").strip()
        if not inbox_id:
            continue
        latest[inbox_id] = row
    return latest


def _actions_path(root: Path) -> Path:
    return root / ".ai" / "state" / "operator_actions.jsonl"


def _default_transitions() -> dict[str, dict[str, list[str]]]:
    return {
        "security_failure": {
            "approve": ["active"],
            "reject": ["blocked"],
            "defer": [],
        },
        "action_block": {
            "approve": ["active"],
            "reject": ["blocked"],
            "defer": [],
        },
        "action_escalate": {
            "approve": ["active"],
            "reject": ["blocked"],
            "defer": [],
        },
        "baseline_blocked": {
            "approve": ["active"],
            "reject": ["blocked"],
            "defer": [],
        },
        "claim_collision": {
            "approve": ["active"],
            "reject": [],
            "defer": [],
        },
    }


def _normalize_transition_rules(
    transitions: dict[str, Any],
    *,
    fallback: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    normalized: dict[str, dict[str, list[str]]] = {}
    for reason_code, action_rules in transitions.items():
        if not isinstance(reason_code, str) or not reason_code.strip():
            continue
        if not isinstance(action_rules, dict):
            continue
        mapped: dict[str, list[str]] = {}
        for action, statuses in action_rules.items():
            if action not in _ALLOWED_ACTIONS:
                continue
            if not isinstance(statuses, list):
                continue
            allowed = [
                status
                for status in statuses
                if isinstance(status, str) and status in ALLOWED_STATUSES
            ]
            mapped[action] = allowed
        if mapped:
            normalized[reason_code.strip()] = mapped
    if not normalized:
        return fallback
    return normalized


def _priority_rank(priority: str) -> int:
    if priority == "high":
        return 0
    if priority == "medium":
        return 1
    return 2


def _timestamp_key(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _bounded_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    if not isinstance(value, int):
        return default
    if value < min_value or value > max_value:
        return default
    return value


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _nullable_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
