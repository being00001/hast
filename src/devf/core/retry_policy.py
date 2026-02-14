"""Retry policy decisions for failed attempts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

Action = str
RETRY_ACTION = "retry"
ESCALATE_ACTION = "escalate"
BLOCK_ACTION = "block"
ADVANCE_ACTION = "advance"


@dataclass(frozen=True)
class RetryPolicy:
    version: str = "v1"
    default_max_retries: int = 3
    no_repeat_same_classification: bool = True
    max_retries_by_classification: dict[str, int] = field(default_factory=dict)
    exceed_limit_action: Action = BLOCK_ACTION
    repeated_failure_action: Action = ESCALATE_ACTION


def load_retry_policy(root: Path) -> RetryPolicy:
    path = root / ".ai" / "policies" / "retry_policy.yaml"
    if not path.exists():
        return RetryPolicy(
            max_retries_by_classification={
                "spec-ambiguous": 1,
                "test-defect": 2,
                "impl-defect": 3,
                "env-flaky": 2,
                "dep-build": 1,
                "security": 0,
            },
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return RetryPolicy()

    max_by_class = data.get("max_retries_by_classification", {})
    parsed_max_by_class: dict[str, int] = {}
    if isinstance(max_by_class, dict):
        for key, value in max_by_class.items():
            if isinstance(key, str) and isinstance(value, int) and value >= 0:
                parsed_max_by_class[key] = value

    actions = data.get("actions", {})
    exceed_limit_action = BLOCK_ACTION
    repeated_failure_action = ESCALATE_ACTION
    if isinstance(actions, dict):
        exceed_raw = actions.get("exceed_limit")
        if exceed_raw in {RETRY_ACTION, ESCALATE_ACTION, BLOCK_ACTION}:
            exceed_limit_action = exceed_raw
        repeat_raw = actions.get("no_repeat_same")
        if repeat_raw in {RETRY_ACTION, ESCALATE_ACTION, BLOCK_ACTION}:
            repeated_failure_action = repeat_raw

    return RetryPolicy(
        version=str(data.get("version", "v1")),
        default_max_retries=_parse_non_negative_int(data.get("default_max_retries"), 3),
        no_repeat_same_classification=bool(data.get("no_repeat_same_classification", True)),
        max_retries_by_classification=parsed_max_by_class,
        exceed_limit_action=exceed_limit_action,
        repeated_failure_action=repeated_failure_action,
    )


def decide_retry_action(
    policy: RetryPolicy,
    failure_classification: str,
    prior_failure_classifications: list[str],
    attempt: int,
    fallback_max_retries: int,
) -> Action:
    """Decide how the loop should handle this failure."""
    limit = policy.max_retries_by_classification.get(
        failure_classification,
        policy.default_max_retries or fallback_max_retries,
    )
    if limit <= 0:
        return policy.exceed_limit_action
    if attempt > limit:
        return policy.exceed_limit_action

    if (
        policy.no_repeat_same_classification
        and prior_failure_classifications
        and prior_failure_classifications[-1] == failure_classification
    ):
        return policy.repeated_failure_action

    return RETRY_ACTION


def _parse_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return default
