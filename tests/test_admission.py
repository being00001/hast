"""Tests for proposal admission and promotion engine."""

from __future__ import annotations

from pathlib import Path

import yaml

from hast.core.admission import promote_proposals
from hast.core.proposals import create_proposal_note, write_proposal_note


def _write_note(
    root: Path,
    *,
    category: str = "workflow_friction",
    impact: str = "medium",
    risk: str = "medium",
    confidence: float = 0.8,
    title: str = "Reduce retry churn",
    why_now: str = "Frequent repeated failures",
) -> None:
    note = create_proposal_note(
        source="worker",
        category=category,
        impact=impact,
        risk=risk,
        confidence=confidence,
        effort_hint="m",
        title=title,
        why_now=why_now,
    )
    write_proposal_note(root, note)


def test_promote_proposals_accepts_and_creates_goal(tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    _write_note(tmp_path)
    _write_note(tmp_path)

    result = promote_proposals(tmp_path, window_days=30, max_active=5)
    assert result.total == 1
    assert result.accepted == 1
    assert result.deferred == 0
    assert result.rejected == 0
    assert result.goals_added == 1
    assert result.backlog_path.exists()

    goals = yaml.safe_load((tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8"))["goals"]
    root_goal = next(goal for goal in goals if goal["id"] == "PX_2X")
    assert root_goal["children"]
    child = root_goal["children"][0]
    assert child["status"] == "active"
    assert child["proposal_fingerprint"]

    backlog = yaml.safe_load((tmp_path / ".ai" / "proposals" / "backlog.yaml").read_text(encoding="utf-8"))
    assert backlog["items"][0]["status"] == "accepted"
    assert backlog["items"][0]["reason_code"] == "accepted_standard"


def test_promote_proposals_respects_active_budget(tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "goals.yaml").write_text(
        """goals:
  - id: PX_2X
    title: Program
    status: active
    children:
      - id: PX_2X.1
        title: Existing
        status: active
        proposal_fingerprint: fp_existing
""",
        encoding="utf-8",
    )
    _write_note(tmp_path)
    _write_note(tmp_path)

    result = promote_proposals(tmp_path, window_days=30, max_active=1)
    assert result.total == 1
    assert result.accepted == 0
    assert result.deferred == 1
    assert result.rejected == 0
    assert result.goals_added == 0

    backlog = yaml.safe_load((tmp_path / ".ai" / "proposals" / "backlog.yaml").read_text(encoding="utf-8"))
    assert backlog["items"][0]["reason_code"] == "active_goal_budget_exceeded"


def test_promote_proposals_high_risk_fast_track_overflow(tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "goals.yaml").write_text(
        """goals:
  - id: PX_2X
    title: Program
    status: active
    children:
      - id: PX_2X.1
        title: Existing
        status: active
        proposal_fingerprint: fp_existing
""",
        encoding="utf-8",
    )
    _write_note(
        tmp_path,
        category="risk",
        impact="high",
        risk="high",
        confidence=0.1,
        title="Critical auth incident",
        why_now="Live risk discovered",
    )

    result = promote_proposals(tmp_path, window_days=30, max_active=1)
    assert result.total == 1
    assert result.accepted == 1
    assert result.goals_added == 1

    backlog = yaml.safe_load((tmp_path / ".ai" / "proposals" / "backlog.yaml").read_text(encoding="utf-8"))
    assert backlog["items"][0]["reason_code"] == "accepted_fast_track_overflow"
