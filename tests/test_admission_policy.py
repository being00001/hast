"""Tests for admission policy loading."""

from __future__ import annotations

from pathlib import Path
import textwrap

from hast.core.admission_policy import load_admission_policy


def test_load_admission_policy_defaults(tmp_path: Path) -> None:
    policy = load_admission_policy(tmp_path)
    assert policy.enabled is True
    assert policy.promotion.min_frequency == 2
    assert policy.promotion.min_confidence == 0.6
    assert policy.promotion.ttl_days == 30
    assert policy.promotion.high_risk_fast_track is True
    assert policy.promotion.goal_root_id == "PX_2X"
    assert policy.dedup.strategy == "fingerprint_v1"


def test_load_admission_policy_custom(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "admission_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v2
            enabled: false
            promotion:
              min_frequency: 4
              min_confidence: 0.75
              ttl_days: 14
              high_risk_fast_track: false
              max_fast_track_overflow: 0
              goal_root_id: PX_CUSTOM
              owner_agent: tester
              max_promote_per_run: 3
            dedup:
              strategy: fp_v2
            """
        ),
        encoding="utf-8",
    )

    policy = load_admission_policy(tmp_path)
    assert policy.version == "v2"
    assert policy.enabled is False
    assert policy.promotion.min_frequency == 4
    assert policy.promotion.min_confidence == 0.75
    assert policy.promotion.ttl_days == 14
    assert policy.promotion.high_risk_fast_track is False
    assert policy.promotion.max_fast_track_overflow == 0
    assert policy.promotion.goal_root_id == "PX_CUSTOM"
    assert policy.promotion.owner_agent == "tester"
    assert policy.promotion.max_promote_per_run == 3
    assert policy.dedup.strategy == "fp_v2"
