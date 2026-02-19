"""Feedback loop policy loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FeedbackPromotionPolicy:
    min_frequency: int = 3
    min_confidence: float = 0.6
    auto_promote_impact: str = "high"


@dataclass(frozen=True)
class FeedbackDedupPolicy:
    strategy: str = "fingerprint_v1"


@dataclass(frozen=True)
class FeedbackPublishPolicy:
    enabled: bool = False
    backend: str = "codeberg"
    repository: str = ""
    token_env: str = "CODEBERG_TOKEN"
    base_url: str = "https://codeberg.org"
    labels: list[str] = field(default_factory=lambda: ["bot-reported", "hast-feedback"])
    min_status: str = "accepted"


@dataclass(frozen=True)
class FeedbackPolicy:
    version: str = "v1"
    enabled: bool = True
    promotion: FeedbackPromotionPolicy = field(default_factory=FeedbackPromotionPolicy)
    dedup: FeedbackDedupPolicy = field(default_factory=FeedbackDedupPolicy)
    publish: FeedbackPublishPolicy = field(default_factory=FeedbackPublishPolicy)


def load_feedback_policy(root: Path) -> FeedbackPolicy:
    path = root / ".ai" / "policies" / "feedback_policy.yaml"
    if not path.exists():
        return FeedbackPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return FeedbackPolicy()

    promotion_raw = data.get("promotion", {})
    if not isinstance(promotion_raw, dict):
        promotion_raw = {}

    dedup_raw = data.get("dedup", {})
    if not isinstance(dedup_raw, dict):
        dedup_raw = {}
    publish_raw = data.get("publish", {})
    if not isinstance(publish_raw, dict):
        publish_raw = {}

    promotion = FeedbackPromotionPolicy(
        min_frequency=_parse_positive_int(promotion_raw.get("min_frequency"), 3),
        min_confidence=_parse_ratio(promotion_raw.get("min_confidence"), 0.6),
        auto_promote_impact=_parse_impact(
            promotion_raw.get("auto_promote_impact"),
            default="high",
        ),
    )

    dedup = FeedbackDedupPolicy(
        strategy=_parse_non_empty_str(dedup_raw.get("strategy"), "fingerprint_v1"),
    )
    publish = FeedbackPublishPolicy(
        enabled=bool(publish_raw.get("enabled", False)),
        backend=_parse_non_empty_str(publish_raw.get("backend"), "codeberg"),
        repository=_parse_non_empty_str(publish_raw.get("repository"), ""),
        token_env=_parse_non_empty_str(publish_raw.get("token_env"), "CODEBERG_TOKEN"),
        base_url=_parse_non_empty_str(publish_raw.get("base_url"), "https://codeberg.org"),
        labels=_parse_str_list(publish_raw.get("labels"), ["bot-reported", "hast-feedback"]),
        min_status=_parse_non_empty_str(publish_raw.get("min_status"), "accepted"),
    )

    return FeedbackPolicy(
        version=_parse_non_empty_str(data.get("version"), "v1"),
        enabled=bool(data.get("enabled", True)),
        promotion=promotion,
        dedup=dedup,
        publish=publish,
    )


def _parse_positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value > 0:
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


def _parse_impact(value: Any, default: str) -> str:
    if isinstance(value, str) and value in {"low", "medium", "high"}:
        return value
    return default


def _parse_str_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    parsed: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            parsed.append(item.strip())
    return parsed or list(default)
