"""Tests for execution queue lease/TTL/idempotency semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from hast.core.errors import HastError
from hast.core.execution_queue import (
    claim_goal,
    list_claims,
    release_claim,
    renew_claim,
    sweep_expired_claims,
)


def _seed_goals(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
  - id: G2
    title: Goal 2
    status: active
  - id: G3
    title: Goal 3
    status: pending
""",
        encoding="utf-8",
    )


def _seed_goals_for_roles(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    phase: implement
  - id: G2
    title: Goal 2
    status: active
    phase: adversarial
  - id: G3
    title: Goal 3
    status: active
    phase: gate
""",
        encoding="utf-8",
    )


def _read_goals_yaml(root: Path) -> str:
    return (root / ".ai" / "goals.yaml").read_text(encoding="utf-8")


def _enable_event_bus(root: Path) -> None:
    policies_dir = root / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "event_bus_policy.yaml").write_text(
        """
version: v1
enabled: true
shadow_mode: true
emit_from_evidence: true
emit_from_queue: true
emit_from_orchestrator: true
auto_reduce_on_emit: false
""",
        encoding="utf-8",
    )


def test_claim_goal_assigns_first_active_goal_and_marks_metadata(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    result = claim_goal(tmp_path, worker_id="worker-a", now=now)

    assert result.created is True
    assert result.claim.goal_id == "G1"
    assert result.claim.worker_id == "worker-a"
    goals_text = _read_goals_yaml(tmp_path)
    assert "claimed_by: worker-a" in goals_text
    assert f"claim_id: {result.claim.claim_id}" in goals_text


def test_claim_goal_idempotency_reuses_existing_claim(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    first = claim_goal(
        tmp_path,
        worker_id="worker-a",
        goal_id="G1",
        idempotency_key="req-1",
        now=now,
    )
    second = claim_goal(
        tmp_path,
        worker_id="worker-a",
        idempotency_key="req-1",
        now=now + timedelta(seconds=10),
    )
    assert first.created is True
    assert second.created is False
    assert second.idempotent_reused is True
    assert second.claim.claim_id == first.claim.claim_id
    assert len(list_claims(tmp_path)) == 1


def test_claim_goal_enforces_max_active_claims_per_worker(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    claim_goal(tmp_path, worker_id="worker-a", goal_id="G1", now=now)
    with pytest.raises(HastError, match="max active claims"):
        claim_goal(tmp_path, worker_id="worker-a", goal_id="G2", now=now + timedelta(seconds=1))


def test_sweep_expired_claims_marks_expired_and_clears_goal_metadata(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    claim_goal(tmp_path, worker_id="worker-a", goal_id="G1", ttl_minutes=1, now=now)
    expired = sweep_expired_claims(tmp_path, now=now + timedelta(minutes=2))
    assert expired == 1
    active = list_claims(tmp_path, active_only=True)
    assert active == []
    goals_text = _read_goals_yaml(tmp_path)
    assert "claimed_by: null" in goals_text


def test_release_claim_updates_goal_status(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    created = claim_goal(tmp_path, worker_id="worker-a", goal_id="G1", now=now)
    released = release_claim(
        tmp_path,
        claim_id=created.claim.claim_id,
        worker_id="worker-a",
        reason="completed by worker",
        goal_status="done",
        now=now + timedelta(minutes=5),
    )
    assert released.status == "released"
    goals_text = _read_goals_yaml(tmp_path)
    assert "status: done" in goals_text


def test_renew_claim_extends_expiry(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    created = claim_goal(tmp_path, worker_id="worker-a", goal_id="G1", now=now)
    renewed = renew_claim(
        tmp_path,
        claim_id=created.claim.claim_id,
        worker_id="worker-a",
        ttl_minutes=45,
        now=now + timedelta(minutes=1),
    )
    assert renewed.expires_at > created.claim.expires_at


def test_claim_rejection_writes_collision_event(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    _enable_event_bus(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
    claim_goal(tmp_path, worker_id="worker-a", goal_id="G1", now=now)
    with pytest.raises(HastError, match="already claimed"):
        claim_goal(tmp_path, worker_id="worker-b", goal_id="G1", now=now + timedelta(seconds=1))

    events_path = tmp_path / ".ai" / "queue" / "events.jsonl"
    rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        row.get("event_type") == "claim_rejected"
        and row.get("reason_code") == "goal_already_claimed"
        for row in rows
    )

    shadow_events_path = tmp_path / ".ai" / "events" / "events.jsonl"
    shadow_rows = [
        json.loads(line)
        for line in shadow_events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        row.get("event_type") == "queue_claim_rejected"
        and row.get("source") == "queue"
        and isinstance(row.get("payload"), dict)
        and row["payload"].get("reason_code") == "goal_already_claimed"
        for row in shadow_rows
    )


def test_claim_goal_role_filter_selects_matching_phase(tmp_path: Path) -> None:
    _seed_goals_for_roles(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)

    test_claim = claim_goal(tmp_path, worker_id="worker-test", role="test", now=now)
    assert test_claim.claim.goal_id == "G2"
    assert test_claim.claim.role == "test"

    verify_claim = claim_goal(tmp_path, worker_id="worker-verify", role="verify", now=now + timedelta(seconds=1))
    assert verify_claim.claim.goal_id == "G3"
    assert verify_claim.claim.role == "verify"

    snapshot = list_claims(tmp_path, active_only=True, now=now + timedelta(seconds=2))
    assert len(snapshot) == 2


def test_claim_goal_role_filter_rejects_specific_goal_mismatch(tmp_path: Path) -> None:
    _seed_goals_for_roles(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(HastError, match="not claimable for role"):
        claim_goal(
            tmp_path,
            worker_id="worker-verify",
            role="verify",
            goal_id="G1",
            now=now,
        )

    events_path = tmp_path / ".ai" / "queue" / "events.jsonl"
    rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        row.get("event_type") == "claim_rejected"
        and row.get("reason_code") == "role_phase_mismatch"
        for row in rows
    )


def test_claim_goal_rejects_invalid_role(tmp_path: Path) -> None:
    _seed_goals_for_roles(tmp_path)
    now = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(HastError, match="invalid role"):
        claim_goal(tmp_path, worker_id="worker-a", role="planner", now=now)
