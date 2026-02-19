"""Policy loading for decision spike comparator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SpikePolicy:
    version: str = "v1"
    prefer_lower_diff_lines: bool = True
    prefer_lower_changed_files: bool = True
    include_duration_tiebreaker: bool = False

    def comparison_criteria(self) -> list[str]:
        criteria = ["passed"]
        if self.prefer_lower_diff_lines:
            criteria.append("diff_lines")
        if self.prefer_lower_changed_files:
            criteria.append("changed_files")
        if self.include_duration_tiebreaker:
            criteria.append("duration_ms")
        criteria.append("alternative_id")
        return criteria


def load_spike_policy(root: Path) -> SpikePolicy:
    path = root / ".ai" / "policies" / "spike_policy.yaml"
    if not path.exists():
        return SpikePolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return SpikePolicy()

    return SpikePolicy(
        version=str(data.get("version", "v1")),
        prefer_lower_diff_lines=_parse_bool(data.get("prefer_lower_diff_lines"), True),
        prefer_lower_changed_files=_parse_bool(data.get("prefer_lower_changed_files"), True),
        include_duration_tiebreaker=_parse_bool(data.get("include_duration_tiebreaker"), False),
    )


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default
