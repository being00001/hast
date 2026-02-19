"""Admission policy loading for proposal promotion."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AdmissionPromotionPolicy:
    min_frequency: int = 2
    min_confidence: float = 0.6
    ttl_days: int = 30
    high_risk_fast_track: bool = True
    max_fast_track_overflow: int = 1
    goal_root_id: str = "PX_2X"
    owner_agent: str = "architect"
    max_promote_per_run: int = 20


@dataclass(frozen=True)
class AdmissionDedupPolicy:
    strategy: str = "fingerprint_v1"


@dataclass(frozen=True)
class AdmissionPolicy:
    version: str = "v1"
    enabled: bool = True
    promotion: AdmissionPromotionPolicy = field(default_factory=AdmissionPromotionPolicy)
    dedup: AdmissionDedupPolicy = field(default_factory=AdmissionDedupPolicy)


def load_admission_policy(root: Path) -> AdmissionPolicy:
    path = root / ".ai" / "policies" / "admission_policy.yaml"
    if not path.exists():
        return AdmissionPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return AdmissionPolicy()

    promotion_raw = data.get("promotion", {})
    if not isinstance(promotion_raw, dict):
        promotion_raw = {}
    dedup_raw = data.get("dedup", {})
    if not isinstance(dedup_raw, dict):
        dedup_raw = {}

    promotion = AdmissionPromotionPolicy(
        min_frequency=_parse_positive_int(promotion_raw.get("min_frequency"), 2),
        min_confidence=_parse_ratio(promotion_raw.get("min_confidence"), 0.6),
        ttl_days=_parse_positive_int(promotion_raw.get("ttl_days"), 30),
        high_risk_fast_track=bool(promotion_raw.get("high_risk_fast_track", True)),
        max_fast_track_overflow=_parse_non_negative_int(
            promotion_raw.get("max_fast_track_overflow"), 1
        ),
        goal_root_id=_parse_non_empty_str(promotion_raw.get("goal_root_id"), "PX_2X"),
        owner_agent=_parse_non_empty_str(promotion_raw.get("owner_agent"), "architect"),
        max_promote_per_run=_parse_positive_int(promotion_raw.get("max_promote_per_run"), 20),
    )
    dedup = AdmissionDedupPolicy(
        strategy=_parse_non_empty_str(dedup_raw.get("strategy"), "fingerprint_v1"),
    )

    return AdmissionPolicy(
        version=_parse_non_empty_str(data.get("version"), "v1"),
        enabled=bool(data.get("enabled", True)),
        promotion=promotion,
        dedup=dedup,
    )


def _parse_positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _parse_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return default


def _parse_ratio(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        parsed = float(value)
        if 0.0 <= parsed <= 1.0:
            return parsed
    return default


def _parse_non_empty_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
