"""Tests for event bus writer/reducer shadow mode."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import yaml

from hast.core.event_bus import emit_shadow_event, replay_event_log


def _write_event_bus_policy(root: Path, *, auto_reduce_on_emit: bool = False) -> None:
    policies_dir = root / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "event_bus_policy.yaml").write_text(
        (
            "version: v1\n"
            "enabled: true\n"
            "shadow_mode: true\n"
            "emit_from_evidence: true\n"
            "emit_from_queue: true\n"
            "emit_from_orchestrator: true\n"
            f"auto_reduce_on_emit: {'true' if auto_reduce_on_emit else 'false'}\n"
        ),
        encoding="utf-8",
    )


def test_replay_event_log_deduplicates_and_writes_deterministic_snapshots(tmp_path: Path) -> None:
    events_path = tmp_path / ".ai" / "events" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-02-15T00:00:01+00:00",
            "event_id": "evt_1",
            "event_type": "auto_attempt",
            "source": "evidence",
            "payload": {
                "goal_id": "G1",
                "success": False,
                "failure_classification": "security",
                "action_taken": "block",
            },
        },
        {
            "timestamp": "2026-02-15T00:00:02+00:00",
            "event_id": "evt_2",
            "event_type": "queue_claim_created",
            "source": "queue",
            "payload": {
                "goal_id": "G1",
                "claim_id": "QCLM_1",
                "worker_id": "worker-a",
                "expires_at": "2026-02-15T00:30:00+00:00",
            },
        },
        {
            "timestamp": "2026-02-15T00:00:03+00:00",
            "event_id": "evt_3",
            "event_type": "queue_claim_rejected",
            "source": "queue",
            "payload": {
                "goal_id": "G1",
                "worker_id": "worker-b",
                "reason_code": "goal_already_claimed",
            },
        },
        {
            "timestamp": "2026-02-15T00:00:04+00:00",
            "event_id": "evt_4",
            "event_type": "orchestrate_cycle_blocked",
            "source": "orchestrator",
            "payload": {"reason": "baseline guards failed"},
        },
        {
            "timestamp": "2026-02-15T00:00:05+00:00",
            "event_id": "evt_1",
            "event_type": "auto_attempt",
            "source": "evidence",
            "payload": {
                "goal_id": "G1",
                "success": False,
                "failure_classification": "security",
                "action_taken": "block",
            },
        },
    ]
    events_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    first = replay_event_log(tmp_path, write_snapshots=True)
    assert first.total_events == 5
    assert first.unique_events == 4
    assert first.duplicate_events == 1
    assert first.goal_count == 1
    assert first.inbox_items == 3
    assert first.goal_views_path is not None
    assert first.operator_inbox_path is not None

    goal_doc = yaml.safe_load(first.goal_views_path.read_text(encoding="utf-8")) or {}
    goals = goal_doc.get("goals", [])
    assert isinstance(goals, list)
    goal = next((item for item in goals if item.get("goal_id") == "G1"), None)
    assert goal is not None
    assert goal["event_count"] == 3
    assert goal["failure_count"] == 1
    assert goal["block_count"] == 1
    assert goal["security_incidents"] == 1
    assert goal["claim_collision_count"] == 1
    assert goal["claimed_by"] == "worker-a"
    assert goal["claim_id"] == "QCLM_1"

    inbox_doc = yaml.safe_load(first.operator_inbox_path.read_text(encoding="utf-8")) or {}
    items = inbox_doc.get("items", [])
    assert isinstance(items, list)
    reason_codes = [item.get("reason_code") for item in items]
    assert "security_failure" in reason_codes
    assert "claim_collision" in reason_codes
    assert "baseline_blocked" in reason_codes

    first_goal_text = first.goal_views_path.read_text(encoding="utf-8")
    first_inbox_text = first.operator_inbox_path.read_text(encoding="utf-8")
    second = replay_event_log(tmp_path, write_snapshots=True)
    assert second.unique_events == first.unique_events
    assert second.duplicate_events == first.duplicate_events
    assert second.goal_views_path is not None
    assert second.operator_inbox_path is not None
    assert second.goal_views_path.read_text(encoding="utf-8") == first_goal_text
    assert second.operator_inbox_path.read_text(encoding="utf-8") == first_inbox_text


def test_emit_shadow_event_respects_policy_and_auto_reduce(tmp_path: Path) -> None:
    _write_event_bus_policy(tmp_path, auto_reduce_on_emit=True)

    event_id = emit_shadow_event(
        tmp_path,
        source="queue",
        event_type="queue_claim_created",
        payload={
            "goal_id": "G2",
            "worker_id": "worker-a",
            "claim_id": "QCLM_2",
            "expires_at": "2026-02-15T01:00:00+00:00",
        },
        timestamp=datetime(2026, 2, 15, 0, 10, tzinfo=timezone.utc),
        idempotency_key="claim-created|QCLM_2",
    )

    assert event_id is not None
    events_path = tmp_path / ".ai" / "events" / "events.jsonl"
    assert events_path.exists()
    rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row.get("event_id") == event_id for row in rows)

    goal_views_path = tmp_path / ".ai" / "state" / "goal_views.yaml"
    assert goal_views_path.exists()
    goal_doc = yaml.safe_load(goal_views_path.read_text(encoding="utf-8")) or {}
    goals = goal_doc.get("goals", [])
    assert isinstance(goals, list)
    assert any(item.get("goal_id") == "G2" for item in goals)
