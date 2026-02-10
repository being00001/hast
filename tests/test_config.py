"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from devf.core.config import Config, load_config
from devf.core.errors import DevfError


def _write_config(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_load_minimal(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
    """)
    config, warnings = load_config(p)
    assert config.test_command == "pytest"
    assert config.ai_tool == "claude -p {prompt}"
    assert config.timeout_minutes == 30
    assert config.max_retries == 3
    assert config.max_context_bytes == 120_000
    assert warnings == []


def test_load_with_overrides(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "make test"
        ai_tool: "codex exec {prompt}"
        timeout_minutes: 60
        max_retries: 5
        max_context_bytes: 50000
    """)
    config, _ = load_config(p)
    assert config.timeout_minutes == 60
    assert config.max_retries == 5
    assert config.max_context_bytes == 50000


def test_load_with_ai_tools(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        ai_tools:
          codex: "codex exec {prompt}"
          gemini: "gemini -p {prompt}"
    """)
    config, _ = load_config(p)
    assert "codex" in config.ai_tools
    assert "gemini" in config.ai_tools


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DevfError, match="config not found"):
        load_config(tmp_path / "nope.yaml")


def test_load_missing_test_command(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        ai_tool: "claude -p {prompt}"
    """)
    with pytest.raises(DevfError, match="test_command"):
        load_config(p)


def test_load_missing_ai_tool(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
    """)
    with pytest.raises(DevfError, match="ai_tool"):
        load_config(p)


def test_load_missing_prompt_placeholder(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude run"
    """)
    with pytest.raises(DevfError, match="prompt"):
        load_config(p)


def test_load_prompt_file_placeholder(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt_file}"
    """)
    config, _ = load_config(p)
    assert "{prompt_file}" in config.ai_tool


def test_load_negative_timeout(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        timeout_minutes: -1
    """)
    with pytest.raises(DevfError, match="positive"):
        load_config(p)


def test_load_unknown_keys_warning(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        unknown_key: "value"
    """)
    _, warnings = load_config(p)
    assert any("unknown" in w for w in warnings)


def test_config_frozen() -> None:
    config = Config(test_command="pytest", ai_tool="echo {prompt}")
    with pytest.raises(Exception):
        config.test_command = "other"  # type: ignore[misc]
