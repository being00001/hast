"""Tests for consumer role policy mapping."""

from __future__ import annotations

from pathlib import Path

from hast.core.consumer_roles import (
    goal_is_claimable_for_role,
    normalize_consumer_role,
    role_for_phase,
)


def test_default_role_mapping(tmp_path: Path) -> None:
    assert role_for_phase(tmp_path, "implement") == "implement"
    assert role_for_phase(tmp_path, "adversarial") == "test"
    assert role_for_phase(tmp_path, "gate") == "verify"
    assert role_for_phase(tmp_path, None) == "implement"


def test_normalize_consumer_role() -> None:
    assert normalize_consumer_role("IMPLEMENT") == "implement"
    assert normalize_consumer_role("test") == "test"
    assert normalize_consumer_role("verify") == "verify"
    assert normalize_consumer_role("unknown") is None


def test_goal_claimable_for_role_with_custom_policy(tmp_path: Path) -> None:
    policies_dir = tmp_path / ".ai" / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "consumer_role_policy.yaml").write_text(
        """
version: v1
default_role: verify
phase_to_role:
  implement: implement
  adversarial: test
  gate: verify
""",
        encoding="utf-8",
    )

    assert goal_is_claimable_for_role(tmp_path, role="implement", phase="implement") is True
    assert goal_is_claimable_for_role(tmp_path, role="verify", phase=None) is True
    assert goal_is_claimable_for_role(tmp_path, role="test", phase="gate") is False

