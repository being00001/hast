"""Tests for proposal inbox helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hast.core.errors import HastError
from hast.core.proposals import (
    create_proposal_note,
    load_proposal_backlog,
    load_proposal_notes,
    write_proposal_note,
)


def test_create_and_load_proposal_note(tmp_path: Path) -> None:
    note = create_proposal_note(
        source="worker",
        category="risk",
        impact="high",
        risk="high",
        confidence=0.8,
        effort_hint="m",
        title="Auth retry storm",
        why_now="Repeated failures observed in latest run",
        run_id="RUN1",
        goal_id="G1",
        evidence_refs=[".ai/runs/RUN1/evidence.jsonl#L2"],
        affected_goals=["G1", "G2"],
    )
    path = write_proposal_note(tmp_path, note)
    assert path.exists()

    loaded = load_proposal_notes(tmp_path, window_days=30)
    assert len(loaded) == 1
    assert loaded[0]["proposal_id"] == note["proposal_id"]
    assert loaded[0]["status"] == "proposed"
    assert loaded[0]["affected_goals"] == ["G1", "G2"]


def test_create_proposal_note_rejects_invalid_payload() -> None:
    with pytest.raises(HastError, match="category"):
        create_proposal_note(
            source="worker",
            category="unknown",
            impact="high",
            risk="high",
            confidence=0.8,
            effort_hint="m",
            title="Title",
            why_now="Now",
        )

    with pytest.raises(HastError, match="effort_hint"):
        create_proposal_note(
            source="worker",
            category="risk",
            impact="high",
            risk="high",
            confidence=0.8,
            effort_hint="huge",
            title="Title",
            why_now="Now",
        )


def test_load_proposal_backlog(tmp_path: Path) -> None:
    proposals_dir = tmp_path / ".ai" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "backlog.yaml").write_text(
        """
generated_at: "2026-02-15T00:00:00+00:00"
items:
  - proposal_id: prop-1
    status: accepted
    promoted_goal_id: PX_2X.1
  - proposal_id: prop-2
    status: deferred
""",
        encoding="utf-8",
    )
    rows = load_proposal_backlog(tmp_path)
    assert len(rows) == 2
    assert rows[0]["proposal_id"] == "prop-1"
