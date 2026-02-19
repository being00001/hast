"""Tests for feedback policy loading."""

from __future__ import annotations

from pathlib import Path
import textwrap

from hast.core.feedback_policy import load_feedback_policy


def test_load_feedback_policy_defaults(tmp_path: Path) -> None:
    policy = load_feedback_policy(tmp_path)
    assert policy.enabled is True
    assert policy.promotion.min_frequency == 3
    assert policy.promotion.min_confidence == 0.6
    assert policy.promotion.auto_promote_impact == "high"
    assert policy.dedup.strategy == "fingerprint_v1"
    assert policy.publish.enabled is False
    assert policy.publish.backend == "codeberg"
    assert policy.publish.token_env == "CODEBERG_TOKEN"


def test_load_feedback_policy_custom(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "feedback_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v2
            enabled: false
            promotion:
              min_frequency: 5
              min_confidence: 0.75
              auto_promote_impact: medium
            dedup:
              strategy: fp_v2
            publish:
              enabled: true
              backend: codeberg
              repository: owner/repo
              token_env: CBG_TOKEN
              base_url: https://codeberg.org
              labels: [bot-reported, quality]
              min_status: accepted
            """
        ),
        encoding="utf-8",
    )

    policy = load_feedback_policy(tmp_path)
    assert policy.version == "v2"
    assert policy.enabled is False
    assert policy.promotion.min_frequency == 5
    assert policy.promotion.min_confidence == 0.75
    assert policy.promotion.auto_promote_impact == "medium"
    assert policy.dedup.strategy == "fp_v2"
    assert policy.publish.enabled is True
    assert policy.publish.repository == "owner/repo"
    assert policy.publish.token_env == "CBG_TOKEN"
    assert policy.publish.labels == ["bot-reported", "quality"]
