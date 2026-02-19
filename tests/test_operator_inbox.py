"""Tests for operator inbox policy-action loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hast.core.errors import DevfError
from hast.core.goals import load_goals
from hast.core.operator_inbox import apply_inbox_action, list_inbox_items, summarize_inbox


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
""",
        encoding="utf-8",
    )


def _seed_inbox(root: Path) -> None:
    state_dir = root / ".ai" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "operator_inbox.yaml").write_text(
        """
version: v1
event_count: 2
duplicate_events_ignored: 0
items:
  - inbox_id: inbox-1
    event_id: evt-1
    event_type: auto_attempt
    source: evidence
    goal_id: G1
    priority: high
    reason_code: security_failure
    summary: "security escalation"
    timestamp: "2026-02-15T00:00:02+00:00"
  - inbox_id: inbox-2
    event_id: evt-2
    event_type: queue_claim_rejected
    source: queue
    goal_id: G2
    priority: medium
    reason_code: claim_collision
    summary: "claim collision"
    timestamp: "2026-02-15T00:00:01+00:00"
""",
        encoding="utf-8",
    )


def test_summarize_and_list_open_items(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    _seed_inbox(tmp_path)

    applied = apply_inbox_action(
        tmp_path,
        inbox_id="inbox-2",
        action="defer",
        operator_id="operator-a",
        reason="wait for evidence",
    )
    assert applied.resolved is False

    open_items = list_inbox_items(tmp_path, include_resolved=False)
    assert len(open_items) == 2
    assert open_items[0]["inbox_id"] == "inbox-1"

    summary = summarize_inbox(tmp_path, top_k=1)
    assert summary.total_items == 2
    assert summary.unresolved_items == 2
    assert summary.resolved_items == 0
    assert summary.high_priority_unresolved == 1
    assert summary.by_reason_code["security_failure"] == 1
    assert len(summary.top_items) == 1
    assert summary.top_items[0]["inbox_id"] == "inbox-1"


def test_apply_inbox_action_updates_goal_status_when_authorized(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    _seed_inbox(tmp_path)

    result = apply_inbox_action(
        tmp_path,
        inbox_id="inbox-1",
        action="reject",
        operator_id="operator-a",
        reason="security gate failed",
        goal_status="blocked",
    )
    assert result.resolved is True
    assert result.goal_id == "G1"
    assert result.goal_status == "blocked"

    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g1 = next(goal for goal in goals if goal.id == "G1")
    assert g1.status == "blocked"

    actions_path = tmp_path / ".ai" / "state" / "operator_actions.jsonl"
    rows = [
        json.loads(line)
        for line in actions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["inbox_id"] == "inbox-1"
    assert rows[-1]["action"] == "reject"


def test_apply_inbox_action_rejects_unauthorized_transition(tmp_path: Path) -> None:
    _seed_goals(tmp_path)
    _seed_inbox(tmp_path)

    with pytest.raises(DevfError, match="unauthorized transition"):
        apply_inbox_action(
            tmp_path,
            inbox_id="inbox-1",
            action="reject",
            operator_id="operator-a",
            reason="invalid transition",
            goal_status="done",
        )

