"""Tests for post-completion replan invalidation logic."""

from __future__ import annotations

from pathlib import Path
import textwrap

import yaml

from hast.core.replan import apply_post_goal_replan


def _write_goals(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_replan_applies_explicit_invalidation_lists(tmp_path: Path) -> None:
    goals_path = tmp_path / ".ai" / "goals.yaml"
    _write_goals(
        goals_path,
        """\
        goals:
          - id: G1
            title: Core
            status: done
            obsoletes: [G2]
            supersedes: [G3]
            merges: [G4]
          - id: G2
            title: Old
            status: pending
          - id: G3
            title: Legacy
            status: active
          - id: G4
            title: Merge target
            status: pending
        """,
    )

    events = apply_post_goal_replan(tmp_path, "G1")
    assert len(events) == 3
    assert {event.goal_id for event in events} == {"G2", "G3", "G4"}

    data = yaml.safe_load(goals_path.read_text(encoding="utf-8"))
    goals = {goal["id"]: goal for goal in data["goals"]}
    assert goals["G2"]["status"] == "obsolete"
    assert goals["G3"]["status"] == "superseded"
    assert goals["G4"]["status"] == "merged_into"


def test_replan_duplicate_proposal_fingerprint_resolved(tmp_path: Path) -> None:
    goals_path = tmp_path / ".ai" / "goals.yaml"
    _write_goals(
        goals_path,
        """\
        goals:
          - id: PX_2X
            title: Program
            status: active
            children:
              - id: PX_2X.1
                title: Done item
                status: done
                proposal_fingerprint: fp_login
              - id: PX_2X.2
                title: Duplicate pending
                status: pending
                proposal_fingerprint: fp_login
        """,
    )

    events = apply_post_goal_replan(tmp_path, "PX_2X.1")
    assert len(events) == 1
    assert events[0].goal_id == "PX_2X.2"
    assert events[0].to_status == "merged_into"
    assert events[0].reason_code == "duplicate_proposal_resolved"

    data = yaml.safe_load(goals_path.read_text(encoding="utf-8"))
    child = data["goals"][0]["children"][1]
    assert child["status"] == "merged_into"


def test_replan_skips_when_completed_goal_not_done(tmp_path: Path) -> None:
    goals_path = tmp_path / ".ai" / "goals.yaml"
    _write_goals(
        goals_path,
        """\
        goals:
          - id: G1
            title: Not completed
            status: active
            obsoletes: [G2]
          - id: G2
            title: Candidate
            status: pending
        """,
    )

    events = apply_post_goal_replan(tmp_path, "G1")
    assert events == []

    data = yaml.safe_load(goals_path.read_text(encoding="utf-8"))
    goals = {goal["id"]: goal for goal in data["goals"]}
    assert goals["G2"]["status"] == "pending"
