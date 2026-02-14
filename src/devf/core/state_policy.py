"""Goal lifecycle state transition policy."""

from __future__ import annotations

GOAL_STATE_ORDER = [
    "planned",
    "red_verified",
    "green_verified",
    "review_ready",
    "merged",
]

_STATE_RANK = {state: idx for idx, state in enumerate(GOAL_STATE_ORDER)}


def decide_goal_state(
    current_state: str | None,
    phase: str | None,
    success: bool,
    classification: str,
) -> str | None:
    """Return lifecycle state after evaluating one attempt."""
    if not success:
        return current_state

    target = _target_state_for_success(phase, classification)
    if target is None:
        return current_state

    if current_state is None:
        return target
    if current_state not in _STATE_RANK:
        return target
    if _STATE_RANK[target] < _STATE_RANK[current_state]:
        return current_state
    return target


def _target_state_for_success(phase: str | None, classification: str) -> str | None:
    if classification == "merged" or phase == "merge":
        return "merged"
    if phase == "gate":
        return "review_ready"
    if phase == "bdd-green":
        return "green_verified"
    if phase == "bdd-red":
        return "red_verified"
    if phase in ("implement", "adversarial", "legacy"):
        return "green_verified"
    if phase == "plan":
        return "planned"
    return None
