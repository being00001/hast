"""Tests for triage/retry/risk policies."""

from __future__ import annotations

from pathlib import Path

from devf.core.retry_policy import (
    BLOCK_ACTION,
    ESCALATE_ACTION,
    RETRY_ACTION,
    RetryPolicy,
    decide_retry_action,
    load_retry_policy,
)
from devf.core.risk_policy import RiskPolicy, compute_risk_score, load_risk_policy
from devf.core.triage import classify_failure


def test_classify_failure_taxonomy() -> None:
    assert classify_failure("contract-invalid", "contract parse failed", "") == "spec-ambiguous"
    assert classify_failure("decision-pending", "decision ticket missing", "") == "spec-ambiguous"
    assert classify_failure("failed-env", "ImportError", "ModuleNotFoundError") == "env-flaky"
    assert classify_failure("failed-impl", "assertion mismatch", "") == "impl-defect"
    assert classify_failure("failed", "secret leaked", "gitleaks fail") == "security"


def test_retry_policy_default_and_no_repeat() -> None:
    policy = RetryPolicy(
        default_max_retries=3,
        no_repeat_same_classification=True,
        max_retries_by_classification={"impl-defect": 3},
        repeated_failure_action=ESCALATE_ACTION,
    )
    action1 = decide_retry_action(policy, "impl-defect", [], attempt=1, fallback_max_retries=3)
    action2 = decide_retry_action(
        policy,
        "impl-defect",
        ["impl-defect"],
        attempt=2,
        fallback_max_retries=3,
    )
    assert action1 == RETRY_ACTION
    assert action2 == ESCALATE_ACTION


def test_retry_policy_exceed_limit() -> None:
    policy = RetryPolicy(
        default_max_retries=1,
        max_retries_by_classification={"spec-ambiguous": 1},
        exceed_limit_action=BLOCK_ACTION,
    )
    action = decide_retry_action(
        policy,
        "spec-ambiguous",
        [],
        attempt=2,
        fallback_max_retries=3,
    )
    assert action == BLOCK_ACTION


def test_load_retry_policy_from_file(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".ai" / "policies"
    policy_dir.mkdir(parents=True)
    (policy_dir / "retry_policy.yaml").write_text(
        """
version: v9
default_max_retries: 4
no_repeat_same_classification: false
max_retries_by_classification:
  impl-defect: 7
actions:
  exceed_limit: block
  no_repeat_same: retry
""",
        encoding="utf-8",
    )
    policy = load_retry_policy(tmp_path)
    assert policy.version == "v9"
    assert policy.default_max_retries == 4
    assert policy.max_retries_by_classification["impl-defect"] == 7
    assert policy.no_repeat_same_classification is False


def test_risk_score_increases_for_sensitive_paths() -> None:
    policy = RiskPolicy(
        base_score_by_classification={"impl-defect": 40},
        phase_weights={"gate": 20},
        sensitive_path_patterns=["src/**/auth*.py"],
        sensitive_path_weight=20,
    )
    score = compute_risk_score(
        policy,
        phase="gate",
        changed_files=["src/api/auth_service.py"],
        failure_classification="impl-defect",
    )
    assert score == 80


def test_load_risk_policy_from_file(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".ai" / "policies"
    policy_dir.mkdir(parents=True)
    (policy_dir / "risk_policy.yaml").write_text(
        """
version: v3
max_score: 100
success_base_score: 10
sensitive_path_weight: 25
block_threshold: 88
rollback_threshold: 66
base_score_by_classification:
  impl-defect: 33
phase_weights:
  merge: 11
sensitive_path_patterns:
  - "pyproject.toml"
""",
        encoding="utf-8",
    )
    policy = load_risk_policy(tmp_path)
    assert policy.version == "v3"
    assert policy.success_base_score == 10
    assert policy.sensitive_path_weight == 25
    assert policy.base_score_by_classification["impl-defect"] == 33
    assert policy.block_threshold == 88
    assert policy.rollback_threshold == 66
