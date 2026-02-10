"""Tests for devf init."""

from __future__ import annotations

from pathlib import Path

from devf.core.init_project import init_project


def test_init_creates_files(tmp_path: Path) -> None:
    created = init_project(tmp_path)
    assert len(created) == 5
    assert (tmp_path / ".ai" / "config.yaml").exists()
    assert (tmp_path / ".ai" / "goals.yaml").exists()
    assert (tmp_path / ".ai" / "rules.md").exists()
    assert (tmp_path / ".ai" / "sessions").is_dir()
    assert (tmp_path / ".ai" / "handoffs").is_dir()


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
