"""Tests for feedback note/backlog helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hast.core.errors import HastError
from hast.core.feedback import (
    build_feedback_backlog,
    create_feedback_note,
    load_feedback_backlog,
    load_feedback_notes,
    save_feedback_backlog,
    write_feedback_note,
)
from hast.core.feedback_policy import FeedbackPolicy, FeedbackPromotionPolicy


def test_write_and_load_feedback_note(tmp_path: Path) -> None:
    note = create_feedback_note(
        run_id="RUN1",
        goal_id="G1",
        phase="implement",
        source="worker_explicit",
        category="workflow_friction",
        impact="medium",
        expected="A",
        actual="B",
        workaround="W",
        confidence=0.8,
        evidence_ids=["abc"],
    )
    write_feedback_note(tmp_path, note)

    notes = load_feedback_notes(tmp_path)
    assert len(notes) == 1
    assert notes[0]["goal_id"] == "G1"
    assert notes[0]["lane"] == "project"
    assert notes[0]["fingerprint"]


def test_build_feedback_backlog_promotion() -> None:
    notes = []
    for _ in range(3):
        notes.append(
            create_feedback_note(
                run_id="RUN1",
                goal_id="G1",
                phase="implement",
                source="worker_explicit",
                category="waste",
                impact="medium",
                expected="avoid waste",
                actual="many retries",
                workaround="manual retry",
                confidence=0.7,
            )
        )

    policy = FeedbackPolicy(
        promotion=FeedbackPromotionPolicy(
            min_frequency=3,
            min_confidence=0.6,
            auto_promote_impact="high",
        )
    )
    items = build_feedback_backlog(notes, policy=policy, promote=True)
    assert len(items) == 1
    assert items[0]["status"] == "accepted"
    assert items[0]["count"] == 3
    assert items[0]["lane"] == "project"


def test_save_and_load_backlog(tmp_path: Path) -> None:
    items = [
        {
            "feedback_key": "k1",
            "title": "t",
            "summary": "s",
            "first_seen": "2026-02-14T00:00:00+00:00",
            "last_seen": "2026-02-14T00:00:00+00:00",
            "count": 1,
            "max_impact": "low",
            "avg_confidence": 0.5,
            "sample_note_ids": ["n1"],
            "status": "candidate",
            "decision_reason": "x",
            "recommended_change": "y",
            "owner": "manager",
        }
    ]
    path = save_feedback_backlog(tmp_path, items)
    assert path.exists()
    loaded = load_feedback_backlog(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["feedback_key"] == "k1"


def test_create_feedback_note_invalid_lane() -> None:
    with pytest.raises(HastError, match="invalid feedback lane"):
        create_feedback_note(
            run_id="RUN1",
            goal_id="G1",
            phase="implement",
            source="worker_explicit",
            lane="invalid",
            category="workflow_friction",
            impact="medium",
            expected="A",
            actual="B",
            workaround="",
            confidence=0.8,
        )
