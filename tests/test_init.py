"""Tests for hast init."""

from __future__ import annotations

import json
from pathlib import Path

from hast.core.init_project import init_project


def test_init_creates_files(tmp_path: Path) -> None:
    created = init_project(tmp_path)
    assert len(created) == 32
    assert (tmp_path / ".ai" / ".hast-metadata").exists()
    assert (tmp_path / ".ai" / "config.yaml").exists()
    assert (tmp_path / ".ai" / "goals.yaml").exists()
    assert (tmp_path / ".ai" / "rules.md").exists()
    assert (tmp_path / ".ai" / "sessions").is_dir()
    assert (tmp_path / ".ai" / "handoffs").is_dir()
    assert (tmp_path / ".ai" / "decisions").is_dir()
    assert (tmp_path / ".ai" / "proposals").is_dir()
    assert (tmp_path / ".ai" / "protocols").is_dir()
    assert (tmp_path / ".ai" / "templates").is_dir()
    assert (tmp_path / ".ai" / "schemas").is_dir()
    assert (tmp_path / ".ai" / "policies" / "retry_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "risk_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "transition_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "model_routing.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "admission_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "docs_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "immune_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "security_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "spike_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "execution_queue_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "observability_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "event_bus_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "operator_inbox_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "consumer_role_policy.yaml").exists()
    assert (tmp_path / ".ai" / "policies" / "protocol_adapter_policy.yaml").exists()
    assert (tmp_path / ".ai" / "templates" / "decision_ticket.yaml").exists()
    assert (tmp_path / ".ai" / "templates" / "pre-commit-config.yaml").exists()
    assert (tmp_path / ".ai" / "schemas" / "decision_evidence.schema.yaml").exists()
    assert (tmp_path / ".ai" / "schemas" / "control_plane_evidence.schema.yaml").exists()


def test_init_idempotent(tmp_path: Path) -> None:
    init_project(tmp_path)
    second = init_project(tmp_path)
    assert second == []


def test_init_config_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "config.yaml").read_text(encoding="utf-8")
    assert "test_command" in content
    assert "ai_tool" in content
    assert "{prompt}" in content
    assert "mutation_enabled" in content
    assert "mutation_high_risk_only" in content
    assert "min_mutation_score_python" in content
    assert "min_mutation_score_rust" in content
    assert "pytest_parallel" in content
    assert "pytest_workers" in content
    assert "pytest_reruns_on_flaky" in content
    assert "pytest_random_order" in content
    assert "security_commands" in content


def test_init_feedback_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").read_text(encoding="utf-8")
    assert "publish:" in content
    assert "backend: codeberg" in content
    assert "token_env: CODEBERG_TOKEN" in content


def test_init_admission_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "admission_policy.yaml").read_text(encoding="utf-8")
    assert "min_frequency:" in content
    assert "goal_root_id:" in content


def test_init_docs_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "docs_policy.yaml").read_text(encoding="utf-8")
    assert "freshness:" in content
    assert "warn_stale: true" in content
    assert "block_on_high_risk: true" in content


def test_init_immune_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "immune_policy.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in content
    assert "require_grant_for_writes: true" in content
    assert "protected_path_patterns:" in content


def test_init_spike_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "spike_policy.yaml").read_text(encoding="utf-8")
    assert "prefer_lower_diff_lines: true" in content
    assert "prefer_lower_changed_files: true" in content
    assert "include_duration_tiebreaker: false" in content


def test_init_security_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "security_policy.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in content
    assert "gitleaks_enabled: true" in content
    assert "semgrep_enabled: true" in content
    assert "dependency_scanner_mode: either" in content
    assert "audit_file: \".ai/security/audit.jsonl\"" in content
    assert "ignore_rules:" in content


def test_init_risk_policy_security_hardening_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "risk_policy.yaml").read_text(encoding="utf-8")
    assert "security_failed_check_bonus:" in content
    assert "security_missing_tool_bonus:" in content
    assert "security_expired_ignore_bonus:" in content
    assert "security_force_block_on_failed_checks: true" in content


def test_init_execution_queue_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "execution_queue_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "default_lease_ttl_minutes:" in content
    assert "max_lease_ttl_minutes:" in content
    assert "max_active_claims_per_worker:" in content


def test_init_observability_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "observability_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "first_pass_success_rate_min:" in content
    assert "block_rate_max:" in content
    assert "claim_collision_rate_max:" in content


def test_init_event_bus_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "event_bus_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "enabled: false" in content
    assert "shadow_mode: true" in content
    assert "emit_from_evidence: true" in content
    assert "emit_from_queue: true" in content
    assert "emit_from_orchestrator: true" in content


def test_init_operator_inbox_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "operator_inbox_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "default_top_k: 10" in content
    assert "security_failure:" in content
    assert "approve: [active]" in content
    assert "reject: [blocked]" in content


def test_init_consumer_role_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "consumer_role_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "default_role: implement" in content
    assert "phase_to_role:" in content
    assert "adversarial: test" in content
    assert "gate: verify" in content


def test_init_protocol_adapter_policy_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "policies" / "protocol_adapter_policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "enabled_adapters:" in content
    assert "- langgraph" in content
    assert "- openhands" in content
    assert "default_export_context_format: pack" in content
    assert "require_goal_exists: true" in content
    assert "include_prompt_by_default: true" in content
    assert "result_inbox_dir: \".ai/protocols/inbox\"" in content
    assert "max_wait_seconds: 900" in content


def test_init_goals_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "goals:" in content


def test_init_precommit_template_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "templates" / "pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "minimum_pre_commit_version:" in content
    assert "https://github.com/pre-commit/pre-commit-hooks" in content
    assert "https://github.com/astral-sh/ruff-pre-commit" in content
    assert "https://github.com/pre-commit/mirrors-mypy" in content
    assert "types-PyYAML" in content
    assert "cargo fmt --check (if Rust workspace present)" in content
    assert "cargo clippy -- -D warnings (if Rust workspace present)" in content


def test_init_control_plane_schema_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "schemas" / "control_plane_evidence.schema.yaml").read_text(
        encoding="utf-8"
    )
    assert "version: control_plane_evidence.v1" in content
    assert "event_type:" in content
    assert "action_taken:" in content
    assert "contract_version:" in content


def test_init_hast_metadata(tmp_path: Path) -> None:
    init_project(tmp_path)
    meta = tmp_path / ".ai" / ".hast-metadata"
    assert meta.exists()
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data["tool"] == "hast"
    assert "version" in data
    assert "created_at" in data


def test_init_hast_metadata_idempotent(tmp_path: Path) -> None:
    init_project(tmp_path)
    meta = tmp_path / ".ai" / ".hast-metadata"
    original = meta.read_text(encoding="utf-8")
    init_project(tmp_path)
    assert meta.read_text(encoding="utf-8") == original


def test_init_creates_gitignore(tmp_path: Path) -> None:
    init_project(tmp_path)
    gi = tmp_path / ".gitignore"
    assert gi.exists()
    content = gi.read_text(encoding="utf-8")
    assert ".ai/runs/" in content
    assert ".ai/sessions/" in content
    assert ".ai/auto.lock" in content
    assert ".ai/archive/" in content


def test_init_gitignore_idempotent(tmp_path: Path) -> None:
    init_project(tmp_path)
    gi = tmp_path / ".gitignore"
    first = gi.read_text(encoding="utf-8")
    init_project(tmp_path)
    assert gi.read_text(encoding="utf-8") == first


def test_init_gitignore_appends_to_existing(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n", encoding="utf-8")
    init_project(tmp_path)
    content = gi.read_text(encoding="utf-8")
    assert content.startswith("node_modules/\n")
    assert ".ai/runs/" in content


def test_init_gitignore_appends_newline_if_missing(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text("*.pyc", encoding="utf-8")
    init_project(tmp_path)
    content = gi.read_text(encoding="utf-8")
    assert "*.pyc\n# --- hast" in content


def test_init_rules_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "rules.md").read_text(encoding="utf-8")
    assert "Verification" in content
    assert "Commit Format" in content
    # Handoff protocol removed
    assert "Handoff Protocol" not in content
