"""Tests for decision ticket evaluation flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from devf.core.decision import (
    apply_decision_result,
    create_decision_ticket,
    evaluate_decision_ticket,
    load_decision_ticket,
    save_decision_ticket,
)
from devf.core.errors import DevfError


def test_evaluate_decision_ticket_picks_eligible_winner() -> None:
    ticket = create_decision_ticket(
        goal_id="G_LOGIN",
        question="Choose auth session strategy",
        alternatives=["A", "B"],
        decision_id="D_LOGIN_STRATEGY",
    )
    criteria = [str(row["criterion"]) for row in ticket["validation_matrix"]]
    ticket["scores"]["A"] = {name: 4 for name in criteria}
    ticket["scores"]["B"] = {name: 2 for name in criteria}

    evaluation = evaluate_decision_ticket(ticket)
    assert evaluation.winner_id == "A"
    assert evaluation.winner_eligible is True
    assert evaluation.ranking[0].total_score > evaluation.ranking[1].total_score


def test_evaluate_decision_ticket_blocks_when_threshold_not_met() -> None:
    ticket = create_decision_ticket(
        goal_id="G_LOGIN",
        question="Choose auth session strategy",
        alternatives=["A", "B"],
        decision_id="D_LOGIN_STRATEGY",
    )
    criteria = [str(row["criterion"]) for row in ticket["validation_matrix"]]
    ticket["scores"]["A"] = {name: 5 for name in criteria}
    ticket["scores"]["A"]["security_posture"] = 1
    ticket["scores"]["B"] = {name: 2 for name in criteria}

    evaluation = evaluate_decision_ticket(ticket)
    assert evaluation.winner_id == "A"
    assert evaluation.winner_eligible is False
    assert "security_posture" in evaluation.ranking[0].failed_criteria


def test_apply_decision_result_updates_status() -> None:
    ticket = create_decision_ticket(
        goal_id="G_LOGIN",
        question="Choose auth session strategy",
        alternatives=["A", "B"],
        decision_id="D_LOGIN_STRATEGY",
    )
    criteria = [str(row["criterion"]) for row in ticket["validation_matrix"]]
    ticket["scores"]["A"] = {name: 4 for name in criteria}
    ticket["scores"]["B"] = {name: 1 for name in criteria}
    evaluation = evaluate_decision_ticket(ticket)

    updated = apply_decision_result(ticket, evaluation, actor="manager")
    assert updated["status"] == "accepted"
    assert updated["selected_alternative"] == "A"
    assert len(updated["decision_history"]) == 1


def test_load_decision_ticket_rejects_invalid_score(tmp_path: Path) -> None:
    path = tmp_path / ".ai" / "decisions" / "bad.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        """decision:
  decision_id: D_BAD
  goal_id: G_BAD
  question: "?"
  status: proposed
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 30
      min_score: 3
  scores:
    A:
      contract_fit: 7
    B: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(DevfError, match="must be in 0..5"):
        load_decision_ticket(path)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / ".ai" / "decisions" / "d.yaml"
    ticket = create_decision_ticket(
        goal_id="G1",
        question="pick one",
        alternatives=["A", "B"],
        decision_id="D1",
    )
    save_decision_ticket(path, ticket)
    loaded = load_decision_ticket(path)
    assert loaded["decision_id"] == "D1"
