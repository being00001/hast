"""Security gate policy loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SecurityIgnoreRule:
    rule_id: str
    pattern: str
    checks: list[str] = field(default_factory=list)
    reason: str = ""
    expires_on: date | None = None


@dataclass(frozen=True)
class SecurityPolicy:
    version: str = "v1"
    enabled: bool = False
    fail_on_missing_tools: bool = False
    audit_file: str = ".ai/security/audit.jsonl"
    dependency_scanner_mode: str = "either"  # either | all
    gitleaks_enabled: bool = True
    gitleaks_command: str = "gitleaks detect --no-git --source ."
    semgrep_enabled: bool = True
    semgrep_command: str = "semgrep scan --config auto --error"
    trivy_enabled: bool = True
    trivy_command: str = "trivy fs --severity HIGH,CRITICAL --exit-code 1 ."
    grype_enabled: bool = True
    grype_command: str = "grype . --fail-on high"
    ignore_rules: list[SecurityIgnoreRule] = field(default_factory=list)


def load_security_policy(root: Path) -> SecurityPolicy:
    path = root / ".ai" / "policies" / "security_policy.yaml"
    if not path.exists():
        return SecurityPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return SecurityPolicy()

    mode = str(data.get("dependency_scanner_mode", "either")).strip().lower()
    if mode not in {"either", "all"}:
        mode = "either"

    return SecurityPolicy(
        version=str(data.get("version", "v1")),
        enabled=_as_bool(data.get("enabled"), False),
        fail_on_missing_tools=_as_bool(data.get("fail_on_missing_tools"), False),
        audit_file=_as_str(data.get("audit_file"), ".ai/security/audit.jsonl"),
        dependency_scanner_mode=mode,
        gitleaks_enabled=_as_bool(data.get("gitleaks_enabled"), True),
        gitleaks_command=_as_str(data.get("gitleaks_command"), "gitleaks detect --no-git --source ."),
        semgrep_enabled=_as_bool(data.get("semgrep_enabled"), True),
        semgrep_command=_as_str(data.get("semgrep_command"), "semgrep scan --config auto --error"),
        trivy_enabled=_as_bool(data.get("trivy_enabled"), True),
        trivy_command=_as_str(
            data.get("trivy_command"),
            "trivy fs --severity HIGH,CRITICAL --exit-code 1 .",
        ),
        grype_enabled=_as_bool(data.get("grype_enabled"), True),
        grype_command=_as_str(data.get("grype_command"), "grype . --fail-on high"),
        ignore_rules=_parse_ignore_rules(data.get("ignore_rules")),
    )


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_ignore_rules(value: Any) -> list[SecurityIgnoreRule]:
    if not isinstance(value, list):
        return []

    rules: list[SecurityIgnoreRule] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        pattern = _as_str(item.get("pattern"), "")
        if not pattern:
            continue

        checks_raw = item.get("checks")
        checks: list[str] = []
        if isinstance(checks_raw, list):
            for check in checks_raw:
                if isinstance(check, str) and check.strip():
                    checks.append(check.strip())

        rules.append(
            SecurityIgnoreRule(
                rule_id=_as_str(item.get("id"), f"security-ignore-{idx}"),
                pattern=pattern,
                checks=checks,
                reason=_as_str(item.get("reason"), ""),
                expires_on=_as_date(item.get("expires_on")),
            )
        )
    return rules


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None
