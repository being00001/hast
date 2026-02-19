"""Tests for lifecycle state transition policy."""

from __future__ import annotations

from hast.core.state_policy import decide_goal_state


def test_state_does_not_change_on_failure() -> None:
    assert decide_goal_state("planned", "bdd-red", False, "failed") == "planned"


def test_bdd_red_success_to_red_verified() -> None:
    assert decide_goal_state(None, "bdd-red", True, "red-verified") == "red_verified"


def test_gate_success_to_review_ready() -> None:
    assert decide_goal_state("green_verified", "gate", True, "gate-pass") == "review_ready"


def test_merge_success_to_merged() -> None:
    assert decide_goal_state("review_ready", "merge", True, "merged") == "merged"


def test_policy_is_monotonic() -> None:
    assert decide_goal_state("merged", "plan", True, "complete") == "merged"
