"""Documentation freshness policy loading."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DocsFreshnessPolicy:
    warn_stale: bool = True
    block_on_high_risk: bool = True
    high_risk_path_patterns: list[str] = field(
        default_factory=lambda: [
            "src/**/auth*.py",
            "src/**/security*.py",
            ".github/workflows/*",
            "pyproject.toml",
            "requirements*.txt",
        ]
    )


@dataclass(frozen=True)
class DocsPolicy:
    version: str = "v1"
    freshness: DocsFreshnessPolicy = field(default_factory=DocsFreshnessPolicy)


def load_docs_policy(root: Path) -> DocsPolicy:
    path = root / ".ai" / "policies" / "docs_policy.yaml"
    if not path.exists():
        return DocsPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return DocsPolicy()

    freshness_raw = data.get("freshness", {})
    if not isinstance(freshness_raw, dict):
        freshness_raw = {}

    freshness = DocsFreshnessPolicy(
        warn_stale=bool(freshness_raw.get("warn_stale", True)),
        block_on_high_risk=bool(freshness_raw.get("block_on_high_risk", True)),
        high_risk_path_patterns=_parse_str_list(
            freshness_raw.get("high_risk_path_patterns"),
            [
                "src/**/auth*.py",
                "src/**/security*.py",
                ".github/workflows/*",
                "pyproject.toml",
                "requirements*.txt",
            ],
        ),
    )
    return DocsPolicy(
        version=_parse_non_empty_str(data.get("version"), "v1"),
        freshness=freshness,
    )


def match_high_risk_paths(paths: list[Path], patterns: list[str]) -> list[Path]:
    matched: list[Path] = []
    for path in paths:
        text = path.as_posix()
        if any(fnmatch.fnmatch(text, pattern) for pattern in patterns):
            matched.append(path)
    return sorted(matched)


def _parse_non_empty_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_str_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    parsed: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            parsed.append(item.strip())
    return parsed or list(default)
