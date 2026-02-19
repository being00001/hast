"""Execution queue semantics: lease, TTL, and idempotent claims."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import yaml

from hast.core.consumer_roles import goal_is_claimable_for_role, normalize_consumer_role
from hast.core.errors import DevfError
from hast.core.event_bus import emit_shadow_event
from hast.core.goals import ALLOWED_STATUSES, load_goals, update_goal_fields, update_goal_status


@dataclass(frozen=True)
class ExecutionQueuePolicy:
    version: str = "v1"
    default_lease_ttl_minutes: int = 30
    max_lease_ttl_minutes: int = 240
    max_active_claims_per_worker: int = 1


@dataclass(frozen=True)
class ExecutionClaim:
    claim_id: str
    goal_id: str
    worker_id: str
    role: str | None
    status: str
    created_at: datetime
    expires_at: datetime
    idempotency_key: str | None = None
    released_at: datetime | None = None
    release_reason: str | None = None
    release_goal_status: str | None = None


@dataclass(frozen=True)
class ClaimResult:
    claim: ExecutionClaim
    created: bool
    idempotent_reused: bool
    expired_swept: int


@dataclass(frozen=True)
class QueueState:
    version: str
    claims: list[ExecutionClaim]


def load_execution_queue_policy(root: Path) -> ExecutionQueuePolicy:
    path = root / ".ai" / "policies" / "execution_queue_policy.yaml"
    if not path.exists():
        return ExecutionQueuePolicy()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ExecutionQueuePolicy()
    return ExecutionQueuePolicy(
        version=_as_str(data.get("version"), "v1"),
        default_lease_ttl_minutes=_bounded_int(
            data.get("default_lease_ttl_minutes"),
            default=30,
            min_value=1,
            max_value=1440,
        ),
        max_lease_ttl_minutes=_bounded_int(
            data.get("max_lease_ttl_minutes"),
            default=240,
            min_value=1,
            max_value=1440,
        ),
        max_active_claims_per_worker=_bounded_int(
            data.get("max_active_claims_per_worker"),
            default=1,
            min_value=1,
            max_value=100,
        ),
    )


def claim_goal(
    root: Path,
    *,
    worker_id: str,
    goal_id: str | None = None,
    role: str | None = None,
    ttl_minutes: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> ClaimResult:
    worker = worker_id.strip()
    if not worker:
        raise DevfError("worker_id is required")
    role_token = normalize_consumer_role(role)
    if role is not None and role_token is None:
        raise DevfError(f"invalid role: {role}")

    now_utc = _as_utc(now or datetime.now(timezone.utc))
    with _queue_lock(root):
        policy = load_execution_queue_policy(root)
        state = _load_state(root)

        expired = _expire_active_claims(root, state, now_utc)

        normalized_key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
        if normalized_key:
            existing = next(
                (
                    claim
                    for claim in state.claims
                    if claim.status == "active"
                    and claim.worker_id == worker
                    and claim.idempotency_key == normalized_key
                    and (role_token is None or claim.role == role_token)
                ),
                None,
            )
            if existing is not None:
                _append_event(
                    root,
                    "idempotent_claim_reused",
                    {
                        "claim_id": existing.claim_id,
                        "goal_id": existing.goal_id,
                        "worker_id": worker,
                        "role": existing.role,
                        "idempotency_key": normalized_key,
                    },
                    now_utc,
                )
                _save_state(root, state)
                return ClaimResult(
                    claim=existing,
                    created=False,
                    idempotent_reused=True,
                    expired_swept=expired,
                )

        active_for_worker = [
            claim
            for claim in state.claims
            if claim.status == "active" and claim.worker_id == worker
        ]
        if len(active_for_worker) >= policy.max_active_claims_per_worker:
            _append_event(
                root,
                "claim_rejected",
                {
                    "worker_id": worker,
                    "goal_id": goal_id,
                    "role": role_token,
                    "reason_code": "max_active_claims",
                },
                now_utc,
            )
            _save_state(root, state)
            raise DevfError(
                "worker reached max active claims "
                f"({len(active_for_worker)} >= {policy.max_active_claims_per_worker})"
            )

        try:
            chosen_goal = _select_claimable_goal(root, state, goal_id=goal_id, role=role_token)
        except DevfError as exc:
            _append_event(
                root,
                "claim_rejected",
                {
                    "worker_id": worker,
                    "goal_id": goal_id,
                    "role": role_token,
                    "reason_code": _claim_reason_code(str(exc)),
                },
                now_utc,
            )
            _save_state(root, state)
            raise
        ttl = _resolve_ttl_minutes(policy, ttl_minutes)
        claim = ExecutionClaim(
            claim_id=f"QCLM_{uuid4().hex[:12]}",
            goal_id=chosen_goal,
            worker_id=worker,
            role=role_token,
            status="active",
            created_at=now_utc,
            expires_at=now_utc + timedelta(minutes=ttl),
            idempotency_key=normalized_key,
        )
        state.claims.append(claim)
        _mark_goal_claimed(root, claim)
        _append_event(
            root,
            "claim_created",
            {
                "claim_id": claim.claim_id,
                "goal_id": claim.goal_id,
                "worker_id": claim.worker_id,
                "role": claim.role,
                "expires_at": claim.expires_at.isoformat(),
                "idempotency_key": claim.idempotency_key,
            },
            now_utc,
        )
        _save_state(root, state)
        return ClaimResult(
            claim=claim,
            created=True,
            idempotent_reused=False,
            expired_swept=expired,
        )


def renew_claim(
    root: Path,
    *,
    claim_id: str,
    worker_id: str,
    ttl_minutes: int | None = None,
    now: datetime | None = None,
) -> ExecutionClaim:
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    with _queue_lock(root):
        policy = load_execution_queue_policy(root)
        state = _load_state(root)
        _expire_active_claims(root, state, now_utc)

        idx, claim = _find_claim_index(state.claims, claim_id)
        if claim is None:
            raise DevfError(f"claim not found: {claim_id}")
        if claim.status != "active":
            raise DevfError(f"claim is not active: {claim_id}")
        if claim.worker_id != worker_id:
            raise DevfError("worker is not owner of the claim")

        ttl = _resolve_ttl_minutes(policy, ttl_minutes)
        updated = ExecutionClaim(
            claim_id=claim.claim_id,
            goal_id=claim.goal_id,
            worker_id=claim.worker_id,
            role=claim.role,
            status=claim.status,
            created_at=claim.created_at,
            expires_at=now_utc + timedelta(minutes=ttl),
            idempotency_key=claim.idempotency_key,
            released_at=claim.released_at,
            release_reason=claim.release_reason,
            release_goal_status=claim.release_goal_status,
        )
        assert idx is not None
        state.claims[idx] = updated
        _mark_goal_claimed(root, updated)
        _append_event(
            root,
            "claim_renewed",
            {
                "claim_id": updated.claim_id,
                "goal_id": updated.goal_id,
                "worker_id": updated.worker_id,
                "role": updated.role,
                "expires_at": updated.expires_at.isoformat(),
            },
            now_utc,
        )
        _save_state(root, state)
        return updated


def release_claim(
    root: Path,
    *,
    claim_id: str,
    worker_id: str,
    reason: str = "",
    goal_status: str | None = None,
    now: datetime | None = None,
) -> ExecutionClaim:
    if goal_status is not None and goal_status not in ALLOWED_STATUSES:
        raise DevfError(f"invalid goal_status: {goal_status}")

    now_utc = _as_utc(now or datetime.now(timezone.utc))
    with _queue_lock(root):
        state = _load_state(root)
        _expire_active_claims(root, state, now_utc)
        idx, claim = _find_claim_index(state.claims, claim_id)
        if claim is None:
            raise DevfError(f"claim not found: {claim_id}")
        if claim.worker_id != worker_id:
            raise DevfError("worker is not owner of the claim")
        if claim.status != "active":
            raise DevfError(f"claim is not active: {claim_id}")

        updated = ExecutionClaim(
            claim_id=claim.claim_id,
            goal_id=claim.goal_id,
            worker_id=claim.worker_id,
            role=claim.role,
            status="released",
            created_at=claim.created_at,
            expires_at=claim.expires_at,
            idempotency_key=claim.idempotency_key,
            released_at=now_utc,
            release_reason=reason.strip() or None,
            release_goal_status=goal_status,
        )
        assert idx is not None
        state.claims[idx] = updated
        _clear_goal_claim_metadata(root, claim.goal_id)
        if goal_status is not None:
            update_goal_status(root / ".ai" / "goals.yaml", claim.goal_id, goal_status)
        _append_event(
            root,
            "claim_released",
            {
                "claim_id": updated.claim_id,
                "goal_id": updated.goal_id,
                "worker_id": updated.worker_id,
                "role": updated.role,
                "reason": updated.release_reason,
                "goal_status": goal_status,
            },
            now_utc,
        )
        _save_state(root, state)
        return updated


def sweep_expired_claims(root: Path, *, now: datetime | None = None) -> int:
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    with _queue_lock(root):
        state = _load_state(root)
        expired = _expire_active_claims(root, state, now_utc)
        if expired:
            _save_state(root, state)
        return expired


def list_claims(
    root: Path,
    *,
    active_only: bool = False,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> list[ExecutionClaim]:
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    with _queue_lock(root):
        state = _load_state(root)
        expired = _expire_active_claims(root, state, now_utc)
        if expired:
            _save_state(root, state)

        claims = state.claims
        if active_only:
            claims = [claim for claim in claims if claim.status == "active"]
        if worker_id:
            claims = [claim for claim in claims if claim.worker_id == worker_id]
        return sorted(
            claims,
            key=lambda item: (
                0 if item.status == "active" else 1,
                item.created_at.isoformat(),
            ),
        )


def execution_queue_snapshot(root: Path) -> dict[str, Any]:
    claims = list_claims(root, active_only=False)
    active = [claim for claim in claims if claim.status == "active"]
    by_worker: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for claim in active:
        by_worker[claim.worker_id] = by_worker.get(claim.worker_id, 0) + 1
        role_key = claim.role or "unassigned"
        by_role[role_key] = by_role.get(role_key, 0) + 1
    return {
        "total_claims": len(claims),
        "active_claims": len(active),
        "active_claims_by_worker": by_worker,
        "active_claims_by_role": by_role,
    }


def _select_claimable_goal(
    root: Path,
    state: QueueState,
    *,
    goal_id: str | None,
    role: str | None = None,
) -> str:
    goals = load_goals(root / ".ai" / "goals.yaml")
    active_goals = [
        node.goal
        for node in _iter_goal_nodes(goals)
        if node.goal.status == "active" and node.goal.mode != "interactive"
    ]
    active_claimed_goal_ids = {
        claim.goal_id for claim in state.claims if claim.status == "active"
    }

    if goal_id:
        for goal in active_goals:
            if goal.id != goal_id:
                continue
            if role is not None and not goal_is_claimable_for_role(root, role=role, phase=goal.phase):
                raise DevfError(f"goal is not claimable for role '{role}': {goal_id}")
            if goal.id in active_claimed_goal_ids:
                raise DevfError(f"goal is already claimed: {goal_id}")
            return goal.id
        raise DevfError(f"goal is not claimable (must be active): {goal_id}")

    for goal in active_goals:
        if role is not None and not goal_is_claimable_for_role(root, role=role, phase=goal.phase):
            continue
        if goal.id in active_claimed_goal_ids:
            continue
        return goal.id
    if role is not None:
        raise DevfError(f"no claimable active goals for role: {role}")
    raise DevfError("no claimable active goals")


def _iter_goal_nodes(goals: list[Any]):
    from hast.core.goals import iter_goals

    return iter_goals(goals)


def _mark_goal_claimed(root: Path, claim: ExecutionClaim) -> None:
    update_goal_fields(
        root / ".ai" / "goals.yaml",
        claim.goal_id,
        {
            "claimed_by": claim.worker_id,
            "claim_id": claim.claim_id,
            "claim_role": claim.role,
            "claim_expires_at": claim.expires_at.isoformat(),
        },
    )


def _clear_goal_claim_metadata(root: Path, goal_id: str) -> None:
    update_goal_fields(
        root / ".ai" / "goals.yaml",
        goal_id,
        {
            "claimed_by": None,
            "claim_id": None,
            "claim_role": None,
            "claim_expires_at": None,
        },
    )


def _expire_active_claims(root: Path, state: QueueState, now_utc: datetime) -> int:
    expired_count = 0
    updated: list[ExecutionClaim] = []
    for claim in state.claims:
        if claim.status != "active" or claim.expires_at >= now_utc:
            updated.append(claim)
            continue
        expired = ExecutionClaim(
            claim_id=claim.claim_id,
            goal_id=claim.goal_id,
            worker_id=claim.worker_id,
            role=claim.role,
            status="expired",
            created_at=claim.created_at,
            expires_at=claim.expires_at,
            idempotency_key=claim.idempotency_key,
            released_at=now_utc,
            release_reason="lease-expired",
            release_goal_status=None,
        )
        updated.append(expired)
        _clear_goal_claim_metadata(root, claim.goal_id)
        _append_event(
            root,
            "claim_expired",
            {
                "claim_id": claim.claim_id,
                "goal_id": claim.goal_id,
                "worker_id": claim.worker_id,
                "role": claim.role,
            },
            now_utc,
        )
        expired_count += 1
    state.claims[:] = updated
    return expired_count


def _find_claim_index(
    claims: list[ExecutionClaim],
    claim_id: str,
) -> tuple[int | None, ExecutionClaim | None]:
    for idx, claim in enumerate(claims):
        if claim.claim_id == claim_id:
            return idx, claim
    return None, None


def _resolve_ttl_minutes(policy: ExecutionQueuePolicy, requested_ttl: int | None) -> int:
    if requested_ttl is None:
        return policy.default_lease_ttl_minutes
    if requested_ttl <= 0:
        raise DevfError("ttl_minutes must be positive")
    if requested_ttl > policy.max_lease_ttl_minutes:
        raise DevfError(
            f"ttl_minutes exceeds max_lease_ttl_minutes ({requested_ttl} > {policy.max_lease_ttl_minutes})"
        )
    return requested_ttl


def _state_path(root: Path) -> Path:
    return root / ".ai" / "queue" / "claims.yaml"


def _events_path(root: Path) -> Path:
    return root / ".ai" / "queue" / "events.jsonl"


def _lock_path(root: Path) -> Path:
    return root / ".ai" / "queue" / ".lock"


def _load_state(root: Path) -> QueueState:
    path = _state_path(root)
    if not path.exists():
        return QueueState(version="v1", claims=[])
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return QueueState(version="v1", claims=[])
    raw_claims = data.get("claims", [])
    claims: list[ExecutionClaim] = []
    if isinstance(raw_claims, list):
        for item in raw_claims:
            claim = _parse_claim(item)
            if claim is not None:
                claims.append(claim)
    return QueueState(version=_as_str(data.get("version"), "v1"), claims=claims)


def _save_state(root: Path, state: QueueState) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": state.version,
        "claims": [_claim_to_dict(claim) for claim in state.claims],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _claim_to_dict(claim: ExecutionClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "goal_id": claim.goal_id,
        "worker_id": claim.worker_id,
        "role": claim.role,
        "status": claim.status,
        "created_at": claim.created_at.isoformat(),
        "expires_at": claim.expires_at.isoformat(),
        "idempotency_key": claim.idempotency_key,
        "released_at": claim.released_at.isoformat() if claim.released_at else None,
        "release_reason": claim.release_reason,
        "release_goal_status": claim.release_goal_status,
    }


def _parse_claim(raw: Any) -> ExecutionClaim | None:
    if not isinstance(raw, dict):
        return None
    claim_id = _as_str(raw.get("claim_id"), "")
    goal_id = _as_str(raw.get("goal_id"), "")
    worker_id = _as_str(raw.get("worker_id"), "")
    role = _nullable_str(raw.get("role"))
    status = _as_str(raw.get("status"), "released")
    if not claim_id or not goal_id or not worker_id:
        return None
    created_at = _as_datetime(raw.get("created_at"))
    expires_at = _as_datetime(raw.get("expires_at"))
    if created_at is None or expires_at is None:
        return None
    released_at = _as_datetime(raw.get("released_at"))
    return ExecutionClaim(
        claim_id=claim_id,
        goal_id=goal_id,
        worker_id=worker_id,
        role=role,
        status=status,
        created_at=created_at,
        expires_at=expires_at,
        idempotency_key=_nullable_str(raw.get("idempotency_key")),
        released_at=released_at,
        release_reason=_nullable_str(raw.get("release_reason")),
        release_goal_status=_nullable_str(raw.get("release_goal_status")),
    )


def _append_event(
    root: Path,
    event_type: str,
    payload: dict[str, Any],
    timestamp: datetime,
) -> None:
    path = _events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": timestamp.isoformat(),
        "event_type": event_type,
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    emit_shadow_event(
        root,
        source="queue",
        event_type=f"queue_{event_type}",
        payload=row,
        timestamp=timestamp,
        idempotency_key=_queue_event_idempotency_key(event_type, payload, timestamp),
    )


@contextmanager
def _queue_lock(root: Path, timeout_seconds: float = 2.0):
    path = _lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    lock_fd: int | None = None
    while True:
        try:
            lock_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(
                lock_fd,
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "acquired_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).encode("utf-8"),
            )
            break
        except FileExistsError:
            if time.time() - started >= timeout_seconds:
                raise DevfError("execution queue is busy (lock timeout)")
            time.sleep(0.05)
    try:
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            path.unlink()
        except OSError:
            pass


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return _as_utc(dt)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _nullable_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bounded_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    if not isinstance(value, int):
        return default
    if value < min_value or value > max_value:
        return default
    return value


def _claim_reason_code(message: str) -> str:
    text = message.lower()
    if "not claimable for role" in text:
        return "role_phase_mismatch"
    if "no claimable active goals for role" in text:
        return "role_no_claimable_goals"
    if "already claimed" in text:
        return "goal_already_claimed"
    if "not claimable" in text:
        return "goal_not_claimable"
    if "no claimable active goals" in text:
        return "no_claimable_goals"
    return "claim_rejected"


def _queue_event_idempotency_key(
    event_type: str,
    payload: dict[str, Any],
    timestamp: datetime,
) -> str | None:
    claim_id = payload.get("claim_id")
    if isinstance(claim_id, str) and claim_id.strip():
        return f"{event_type}|{claim_id.strip()}"
    return f"{event_type}|{payload.get('worker_id') or ''}|{payload.get('goal_id') or ''}|{timestamp.isoformat()}"
