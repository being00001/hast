"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from hast.core.config import Config, load_config
from hast.core.errors import DevfError


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


def test_load_with_always_allow_changes(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        always_allow_changes:
          - "docs/ARCHITECTURE.md"
          - "src/protocols.py"
    """)
    config, _ = load_config(p)
    assert config.always_allow_changes == [
        "docs/ARCHITECTURE.md",
        "src/protocols.py",
    ]


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


def test_load_gate_config(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          mypy_command: "mypy core/"
          ruff_command: "ruff check ."
          max_diff_lines: 150
          required_checks: ["pytest", "ruff"]
          fail_on_skipped_required: false
          mutation_enabled: true
          mutation_high_risk_only: true
          mutation_python_command: "mutmut run --paths-to-mutate src"
          mutation_rust_command: "cargo mutants --timeout 300"
          min_mutation_score_python: 70
          min_mutation_score_rust: 60
          pytest_parallel: true
          pytest_workers: "auto"
          pytest_reruns_on_flaky: 2
          pytest_random_order: true
          security_commands:
            - "gitleaks detect --no-git --source ."
    """)
    config, warnings = load_config(p)
    assert config.gate.mypy_command == "mypy core/"
    assert config.gate.ruff_command == "ruff check ."
    assert config.gate.max_diff_lines == 150
    assert config.gate.required_checks == ["pytest", "ruff"]
    assert config.gate.fail_on_skipped_required is False
    assert config.gate.mutation_enabled is True
    assert config.gate.mutation_high_risk_only is True
    assert config.gate.mutation_python_command == "mutmut run --paths-to-mutate src"
    assert config.gate.mutation_rust_command == "cargo mutants --timeout 300"
    assert config.gate.min_mutation_score_python == 70
    assert config.gate.min_mutation_score_rust == 60
    assert config.gate.pytest_parallel is True
    assert config.gate.pytest_workers == "auto"
    assert config.gate.pytest_reruns_on_flaky == 2
    assert config.gate.pytest_random_order is True
    assert config.gate.security_commands == ["gitleaks detect --no-git --source ."]
    assert warnings == []


def test_load_gate_config_defaults(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
    """)
    config, _ = load_config(p)
    assert config.gate.mypy_command == ""
    assert config.gate.ruff_command == ""
    assert config.gate.max_diff_lines == 200
    assert config.gate.required_checks == []
    assert config.gate.fail_on_skipped_required is True
    assert config.gate.mutation_enabled is False
    assert config.gate.mutation_high_risk_only is True
    assert config.gate.mutation_python_command == "mutmut run --paths-to-mutate src"
    assert config.gate.mutation_rust_command == "cargo mutants --timeout 300"
    assert config.gate.min_mutation_score_python == 0
    assert config.gate.min_mutation_score_rust == 0
    assert config.gate.pytest_parallel is False
    assert config.gate.pytest_workers == "auto"
    assert config.gate.pytest_reruns_on_flaky == 0
    assert config.gate.pytest_random_order is False
    assert config.gate.security_commands == []


def test_load_gate_required_checks_invalid(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          required_checks: "pytest"
    """)
    with pytest.raises(DevfError, match="required_checks"):
        load_config(p)


def test_load_gate_security_commands_invalid(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          security_commands: "gitleaks detect --no-git"
    """)
    with pytest.raises(DevfError, match="security_commands"):
        load_config(p)


def test_load_gate_pytest_reruns_invalid(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          pytest_reruns_on_flaky: -1
    """)
    with pytest.raises(DevfError, match="pytest_reruns_on_flaky"):
        load_config(p)


def test_load_gate_pytest_workers_invalid(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          pytest_workers: 4
    """)
    with pytest.raises(DevfError, match="pytest_workers"):
        load_config(p)


def test_load_gate_min_mutation_score_invalid(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        gate:
          min_mutation_score_python: 120
    """)
    with pytest.raises(DevfError, match="min_mutation_score_python"):
        load_config(p)


def test_load_circuit_breakers(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        circuit_breakers:
          max_cycles_per_session: 5
          max_consecutive_no_progress: 2
    """)
    config, _ = load_config(p)
    assert config.circuit_breakers.max_cycles_per_session == 5
    assert config.circuit_breakers.max_consecutive_no_progress == 2


def test_load_circuit_breakers_defaults(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
    """)
    config, _ = load_config(p)
    assert config.circuit_breakers.max_cycles_per_session == 10
    assert config.circuit_breakers.max_consecutive_no_progress == 3


def test_load_merge_train_config(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        merge_train:
          pre_merge_command: "pytest -q"
          post_merge_command: "pytest tests/smoke -q"
          auto_rollback: false
    """)
    config, warnings = load_config(p)
    assert config.merge_train.pre_merge_command == "pytest -q"
    assert config.merge_train.post_merge_command == "pytest tests/smoke -q"
    assert config.merge_train.auto_rollback is False
    assert warnings == []


def test_load_merge_train_defaults(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
    """)
    config, _ = load_config(p)
    assert config.merge_train.pre_merge_command == ""
    assert config.merge_train.post_merge_command == ""
    assert config.merge_train.auto_rollback is True


def test_load_language_profiles_defaults(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest -q"
        ai_tool: "claude -p {prompt}"
    """)
    config, _ = load_config(p)
    assert "python" in config.language_profiles
    assert "rust" in config.language_profiles
    assert config.language_profiles["python"].targeted_test_command == "pytest -q {files}"
    assert "cargo test" in config.language_profiles["rust"].targeted_test_command


def test_load_language_profiles_override(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest -q"
        ai_tool: "claude -p {prompt}"
        language_profiles:
          rust:
            enabled: true
            test_file_globs: ["tests/*.rs"]
            assertion_patterns: ["assert_eq!("]
            trivial_assertions: ["assert_eq!(1, 1)"]
            targeted_test_command: "cargo test --test smoke"
            gate_commands:
              - "cargo test --test smoke"
    """)
    config, _ = load_config(p)
    rust = config.language_profiles["rust"]
    assert rust.test_file_globs == ["tests/*.rs"]
    assert rust.targeted_test_command == "cargo test --test smoke"
    assert rust.gate_commands == ["cargo test --test smoke"]


def test_load_language_profiles_invalid_shape(tmp_path: Path) -> None:
    p = _write_config(tmp_path / "config.yaml", """\
        test_command: "pytest"
        ai_tool: "claude -p {prompt}"
        language_profiles:
          rust:
            test_file_globs: "tests/*.rs"
    """)
    with pytest.raises(DevfError, match="test_file_globs"):
        load_config(p)


def test_load_config_with_root(tmp_path: Path) -> None:
    """load_config(root=...) resolves path automatically."""
    ai = tmp_path / ".ai"
    ai.mkdir()
    p = ai / "config.yaml"
    p.write_text(
        "test_command: pytest\nai_tool: echo {prompt}\n",
        encoding="utf-8",
    )
    config, _ = load_config(root=tmp_path)
    assert config.test_command == "pytest"


def test_load_config_with_overrides(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(
        "test_command: pytest\nai_tool: echo {prompt}\ntimeout_minutes: 30\n",
        encoding="utf-8",
    )
    config, _ = load_config(p, overrides={"timeout_minutes": 10, "max_retries": 5})
    assert config.timeout_minutes == 10
    assert config.max_retries == 5


def test_load_config_requires_path_or_root() -> None:
    with pytest.raises(DevfError, match="either path or root"):
        load_config()
