"""Tests for immune guardrail policy."""

from __future__ import annotations

from pathlib import Path
import textwrap

from devf.core.immune_policy import (
    evaluate_immune_changes,
    load_immune_policy,
    write_repair_grant,
)


def test_load_immune_policy_defaults(tmp_path: Path) -> None:
    policy = load_immune_policy(tmp_path)
    assert policy.version == "v1"
    assert policy.enabled is False
    assert policy.require_grant_for_writes is True
    assert policy.grant_file == ".ai/immune/grant.yaml"


def test_load_immune_policy_custom(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "immune_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v2
            enabled: true
            require_grant_for_writes: false
            grant_file: .ai/immune/custom_grant.yaml
            audit_file: .ai/immune/custom_audit.jsonl
            max_changed_files: 9
            protected_path_patterns:
              - ".ai/protocols/**"
            """
        ),
        encoding="utf-8",
    )

    policy = load_immune_policy(tmp_path)
    assert policy.version == "v2"
    assert policy.enabled is True
    assert policy.require_grant_for_writes is False
    assert policy.grant_file == ".ai/immune/custom_grant.yaml"
    assert policy.audit_file == ".ai/immune/custom_audit.jsonl"
    assert policy.max_changed_files == 9
    assert policy.protected_path_patterns == [".ai/protocols/**"]


def test_evaluate_immune_changes_blocks_without_grant(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "immune_policy.yaml").write_text(
        "enabled: true\nrequire_grant_for_writes: true\n",
        encoding="utf-8",
    )

    result = evaluate_immune_changes(tmp_path, ["src/app.py"], metadata={"goal_id": "G1"})
    assert result.allowed is False
    assert result.violation_code == "grant-missing"
    audit = tmp_path / ".ai" / "immune" / "audit.jsonl"
    assert audit.exists()


def test_evaluate_immune_changes_allows_with_grant(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "immune_policy.yaml").write_text(
        "enabled: true\nrequire_grant_for_writes: true\n",
        encoding="utf-8",
    )
    write_repair_grant(
        tmp_path,
        allowed_changes=["src/**/*.py"],
        approved_by="supervisor",
        ttl_minutes=30,
    )

    result = evaluate_immune_changes(tmp_path, ["src/core/app.py"])
    assert result.allowed is True


def test_evaluate_immune_changes_blocks_protected_paths(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "immune_policy.yaml").write_text(
        "enabled: true\nrequire_grant_for_writes: false\n",
        encoding="utf-8",
    )

    result = evaluate_immune_changes(tmp_path, [".ai/policies/risk_policy.yaml"])
    assert result.allowed is False
    assert result.violation_code == "protected-path-modified"
