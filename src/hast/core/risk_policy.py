"""Risk scoring policy for auto-loop outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "v1"
    max_score: int = 100
    success_base_score: int = 15
    base_score_by_classification: dict[str, int] = field(default_factory=dict)
    phase_weights: dict[str, int] = field(default_factory=dict)
    sensitive_path_patterns: list[str] = field(default_factory=list)
    sensitive_path_weight: int = 20
    security_failed_check_bonus: int = 15
    security_missing_tool_bonus: int = 5
    security_expired_ignore_bonus: int = 10
    security_force_block_on_failed_checks: bool = True
    security_force_block_on_missing_tools: bool = False
    block_threshold: int = 95
    rollback_threshold: int = 80


def load_risk_policy(root: Path) -> RiskPolicy:
    path = root / ".ai" / "policies" / "risk_policy.yaml"
    if not path.exists():
        return RiskPolicy(
            base_score_by_classification={
                "spec-ambiguous": 55,
                "test-defect": 45,
                "impl-defect": 40,
                "env-flaky": 35,
                "dep-build": 70,
                "security": 90,
            },
            phase_weights={
                "plan": 5,
                "implement": 10,
                "bdd-red": 10,
                "bdd-green": 15,
                "gate": 20,
                "merge": 25,
                "legacy": 10,
            },
            sensitive_path_patterns=[
                "src/**/auth*.py",
                "src/**/security*.py",
                ".github/workflows/*",
                "pyproject.toml",
                "requirements*.txt",
            ],
            block_threshold=95,
            rollback_threshold=80,
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return RiskPolicy()

    base_raw = data.get("base_score_by_classification", {})
    base_scores: dict[str, int] = {}
    if isinstance(base_raw, dict):
        for key, value in base_raw.items():
            if isinstance(key, str) and isinstance(value, int):
                base_scores[key] = value

    phase_raw = data.get("phase_weights", {})
    phase_weights: dict[str, int] = {}
    if isinstance(phase_raw, dict):
        for key, value in phase_raw.items():
            if isinstance(key, str) and isinstance(value, int):
                phase_weights[key] = value

    patterns = data.get("sensitive_path_patterns", [])
    parsed_patterns = [p for p in patterns if isinstance(p, str)] if isinstance(patterns, list) else []

    return RiskPolicy(
        version=str(data.get("version", "v1")),
        max_score=_parse_positive_int(data.get("max_score"), 100),
        success_base_score=_parse_non_negative_int(data.get("success_base_score"), 15),
        base_score_by_classification=base_scores,
        phase_weights=phase_weights,
        sensitive_path_patterns=parsed_patterns,
        sensitive_path_weight=_parse_non_negative_int(data.get("sensitive_path_weight"), 20),
        security_failed_check_bonus=_parse_non_negative_int(data.get("security_failed_check_bonus"), 15),
        security_missing_tool_bonus=_parse_non_negative_int(
            data.get("security_missing_tool_bonus"), 5
        ),
        security_expired_ignore_bonus=_parse_non_negative_int(
            data.get("security_expired_ignore_bonus"), 10
        ),
        security_force_block_on_failed_checks=_parse_bool(
            data.get("security_force_block_on_failed_checks"), True
        ),
        security_force_block_on_missing_tools=_parse_bool(
            data.get("security_force_block_on_missing_tools"), False
        ),
        block_threshold=_parse_positive_int(data.get("block_threshold"), 95),
        rollback_threshold=_parse_positive_int(data.get("rollback_threshold"), 80),
    )


def compute_risk_score(
    policy: RiskPolicy,
    phase: str | None,
    changed_files: list[str],
    failure_classification: str | None,
    security_failed_checks: int = 0,
    security_missing_tools: int = 0,
    security_expired_ignores: int = 0,
) -> int:
    """Compute risk score in the range [0, policy.max_score]."""
    if failure_classification:
        score = policy.base_score_by_classification.get(failure_classification, 50)
    else:
        score = policy.success_base_score

    if phase:
        score += policy.phase_weights.get(phase, 0)

    if policy.sensitive_path_patterns and _touches_sensitive_paths(changed_files, policy.sensitive_path_patterns):
        score += policy.sensitive_path_weight

    if security_failed_checks > 0:
        score += security_failed_checks * policy.security_failed_check_bonus
    if security_missing_tools > 0:
        score += security_missing_tools * policy.security_missing_tool_bonus
    if security_expired_ignores > 0:
        score += security_expired_ignores * policy.security_expired_ignore_bonus

    return max(0, min(policy.max_score, score))


def _touches_sensitive_paths(files: list[str], patterns: list[str]) -> bool:
    for path in files:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
    return False


def _parse_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return default


def _parse_positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default
