"""Tests for security policy loading."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from hast.core.security_policy import load_security_policy


def test_load_security_policy_defaults(tmp_path: Path) -> None:
    policy = load_security_policy(tmp_path)
    assert policy.version == "v1"
    assert policy.enabled is False
    assert policy.fail_on_missing_tools is False
    assert policy.audit_file == ".ai/security/audit.jsonl"
    assert policy.dependency_scanner_mode == "either"
    assert policy.gitleaks_enabled is True
    assert policy.semgrep_enabled is True
    assert policy.trivy_enabled is True
    assert policy.grype_enabled is True
    assert policy.ignore_rules == []


def test_load_security_policy_custom(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".ai" / "policies"
    policy_dir.mkdir(parents=True)
    (policy_dir / "security_policy.yaml").write_text(
        """
version: v2
enabled: true
fail_on_missing_tools: true
dependency_scanner_mode: all
gitleaks_enabled: false
gitleaks_command: "gitleaks detect --source ."
semgrep_enabled: true
semgrep_command: "semgrep scan --config p/ci --error"
trivy_enabled: true
trivy_command: "trivy fs --exit-code 1 ."
grype_enabled: false
grype_command: "grype . --fail-on medium"
audit_file: ".ai/security/custom-audit.jsonl"
ignore_rules:
  - id: "SG-001"
    checks: ["semgrep", "dependency_scan"]
    pattern: "known false positive"
    reason: "tracked in SEC-12"
    expires_on: "2026-12-31"
""",
        encoding="utf-8",
    )

    policy = load_security_policy(tmp_path)
    assert policy.version == "v2"
    assert policy.enabled is True
    assert policy.fail_on_missing_tools is True
    assert policy.dependency_scanner_mode == "all"
    assert policy.gitleaks_enabled is False
    assert policy.semgrep_enabled is True
    assert policy.semgrep_command == "semgrep scan --config p/ci --error"
    assert policy.trivy_enabled is True
    assert policy.grype_enabled is False
    assert policy.audit_file == ".ai/security/custom-audit.jsonl"
    assert len(policy.ignore_rules) == 1
    assert policy.ignore_rules[0].rule_id == "SG-001"
    assert policy.ignore_rules[0].checks == ["semgrep", "dependency_scan"]
    assert policy.ignore_rules[0].pattern == "known false positive"
    assert policy.ignore_rules[0].expires_on == date(2026, 12, 31)
