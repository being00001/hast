"""Tests for devf init."""

from __future__ import annotations

from pathlib import Path

from devf.core.init_project import init_project


def test_init_creates_files(tmp_path: Path) -> None:
    created = init_project(tmp_path)
    assert len(created) == 20
    assert (tmp_path / ".ai" / "config.yaml").exists()
    assert (tmp_path / ".ai" / "goals.yaml").exists()
    assert (tmp_path / ".ai" / "rules.md").exists()
    assert (tmp_path / ".ai" / "sessions").is_dir()
    assert (tmp_path / ".ai" / "handoffs").is_dir()
    assert (tmp_path / ".ai" / "decisions").is_dir()
    assert (tmp_path / ".ai" / "proposals").is_dir()
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
    assert (tmp_path / ".ai" / "templates" / "decision_ticket.yaml").exists()
    assert (tmp_path / ".ai" / "templates" / "pre-commit-config.yaml").exists()
    assert (tmp_path / ".ai" / "schemas" / "decision_evidence.schema.yaml").exists()


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


def test_init_goals_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "goals:" in content


def test_init_rules_content(tmp_path: Path) -> None:
    init_project(tmp_path)
    content = (tmp_path / ".ai" / "rules.md").read_text(encoding="utf-8")
    assert "Verification" in content
    assert "Commit Format" in content
    # Handoff protocol removed
    assert "Handoff Protocol" not in content
