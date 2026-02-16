"""Tests for environment variable path resolution."""

from __future__ import annotations

from pathlib import Path

from hast.core.config import resolve_ai_dir, resolve_config_path


def test_resolve_config_path_default(tmp_path: Path) -> None:
    result = resolve_config_path(tmp_path)
    assert result == tmp_path / ".ai" / "config.yaml"


def test_resolve_config_path_hast_ai_dir(tmp_path: Path, monkeypatch: object) -> None:
    custom_ai = tmp_path / "custom_ai"
    monkeypatch.setenv("HAST_AI_DIR", str(custom_ai))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == custom_ai / "config.yaml"


def test_resolve_config_path_hast_config_path(tmp_path: Path, monkeypatch: object) -> None:
    custom = tmp_path / "my" / "config.yaml"
    monkeypatch.setenv("HAST_CONFIG_PATH", str(custom))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == custom


def test_resolve_config_path_priority(tmp_path: Path, monkeypatch: object) -> None:
    """HAST_CONFIG_PATH takes priority over HAST_AI_DIR."""
    monkeypatch.setenv("HAST_AI_DIR", str(tmp_path / "ai"))  # type: ignore[attr-defined]
    monkeypatch.setenv("HAST_CONFIG_PATH", str(tmp_path / "direct.yaml"))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == tmp_path / "direct.yaml"


def test_resolve_ai_dir_default(tmp_path: Path) -> None:
    result = resolve_ai_dir(tmp_path)
    assert result == tmp_path / ".ai"


def test_resolve_ai_dir_override(tmp_path: Path, monkeypatch: object) -> None:
    custom = tmp_path / "custom_ai"
    monkeypatch.setenv("HAST_AI_DIR", str(custom))  # type: ignore[attr-defined]
    result = resolve_ai_dir(tmp_path)
    assert result == custom
