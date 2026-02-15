"""Config loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from devf.core.errors import DevfError


@dataclass(frozen=True)
class GateConfig:
    mypy_command: str = ""
    ruff_command: str = ""
    max_diff_lines: int = 200
    required_checks: list[str] = field(default_factory=list)
    fail_on_skipped_required: bool = True
    security_commands: list[str] = field(default_factory=list)
    pytest_parallel: bool = False
    pytest_workers: str = "auto"
    pytest_reruns_on_flaky: int = 0
    pytest_random_order: bool = False


@dataclass(frozen=True)
class CircuitBreakerConfig:
    max_cycles_per_session: int = 10
    max_consecutive_no_progress: int = 3


@dataclass(frozen=True)
class MergeTrainConfig:
    pre_merge_command: str = ""
    post_merge_command: str = ""
    auto_rollback: bool = True


@dataclass(frozen=True)
class ModelConfig:
    model: str | None
    temperature: float = 0.0
    max_tokens: int | None = None
    api_key: str | None = None  # Env var name or value


@dataclass(frozen=True)
class RolesConfig:
    architect: ModelConfig | None = None
    worker: ModelConfig | None = None
    tester: ModelConfig | None = None


@dataclass(frozen=True)
class LanguageProfileConfig:
    enabled: bool = True
    test_file_globs: list[str] = field(default_factory=list)
    assertion_patterns: list[str] = field(default_factory=list)
    trivial_assertions: list[str] = field(default_factory=list)
    targeted_test_command: str = ""
    gate_commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Config:
    test_command: str
    ai_tool: str
    timeout_minutes: int = 30
    max_retries: int = 3
    max_context_bytes: int = 120_000
    ai_tools: dict[str, str] = field(default_factory=dict)
    gate: GateConfig = field(default_factory=GateConfig)
    merge_train: MergeTrainConfig = field(default_factory=MergeTrainConfig)
    circuit_breakers: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    language_profiles: dict[str, LanguageProfileConfig] = field(default_factory=dict)
    roles: RolesConfig = field(default_factory=RolesConfig)


def _validate_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise DevfError(f"{field_name} must be a positive integer")
    return value


def _validate_tool_command(command: str, field_name: str) -> None:
    if "{prompt}" not in command and "{prompt_file}" not in command:
        raise DevfError(f"{field_name} must include {{prompt}} or {{prompt_file}}")


def _parse_model_config(data: Any, field_name: str) -> ModelConfig:
    if not isinstance(data, dict):
        raise DevfError(f"{field_name} must be a mapping")
    model = data.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise DevfError(f"{field_name}.model must be a non-empty string if provided")

    temperature = data.get("temperature", 0.0)
    if not isinstance(temperature, (int, float)):
        raise DevfError(f"{field_name}.temperature must be a number")

    max_tokens = data.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
        raise DevfError(f"{field_name}.max_tokens must be a positive integer")

    api_key = data.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise DevfError(f"{field_name}.api_key must be a string")

    return ModelConfig(
        model=model,
        temperature=float(temperature),
        max_tokens=max_tokens,
        api_key=api_key,
    )


def _parse_str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise DevfError(f"{field_name} must be a list")
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise DevfError(f"{field_name} entries must be strings")
        v = item.strip()
        if v:
            parsed.append(v)
    return parsed


def _default_language_profiles(test_command: str, gate: GateConfig) -> dict[str, LanguageProfileConfig]:
    python_gate_commands = [test_command]
    if gate.ruff_command:
        python_gate_commands.append(gate.ruff_command)
    if gate.mypy_command:
        python_gate_commands.append(gate.mypy_command)

    return {
        "python": LanguageProfileConfig(
            enabled=True,
            test_file_globs=[
                "tests/**/*.py",
                "tests/*.py",
                "**/test_*.py",
                "**/*_test.py",
            ],
            assertion_patterns=[
                "assert ",
                "pytest.raises(",
            ],
            trivial_assertions=[
                "assert True",
                "assert 1 == 1",
                "assert 0 == 0",
            ],
            targeted_test_command="pytest -q {files}",
            gate_commands=python_gate_commands,
        ),
        "rust": LanguageProfileConfig(
            enabled=True,
            test_file_globs=[
                "tests/**/*.rs",
                "tests/*.rs",
            ],
            assertion_patterns=[
                "assert!(",
                "assert_eq!(",
                "assert_ne!(",
                "matches!(",
            ],
            trivial_assertions=[
                "assert!(true)",
                "assert_eq!(1, 1)",
                "assert_eq!(0, 0)",
            ],
            targeted_test_command="cargo test",
            gate_commands=[
                "cargo test",
                "cargo fmt --check",
                "cargo clippy -- -D warnings",
            ],
        ),
    }


def _parse_language_profiles(
    raw: Any,
    test_command: str,
    gate: GateConfig,
) -> dict[str, LanguageProfileConfig]:
    defaults = _default_language_profiles(test_command, gate)
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise DevfError("language_profiles must be a mapping")

    profiles = dict(defaults)
    for name, item in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise DevfError("language_profiles keys must be non-empty strings")
        if not isinstance(item, dict):
            raise DevfError(f"language_profiles.{name} must be a mapping")

        base = profiles.get(name, LanguageProfileConfig())
        enabled = item.get("enabled", base.enabled)
        if not isinstance(enabled, bool):
            raise DevfError(f"language_profiles.{name}.enabled must be a boolean")

        test_file_globs = item.get("test_file_globs", base.test_file_globs)
        assertion_patterns = item.get("assertion_patterns", base.assertion_patterns)
        trivial_assertions = item.get("trivial_assertions", base.trivial_assertions)
        gate_commands = item.get("gate_commands", base.gate_commands)

        targeted_test_command = item.get("targeted_test_command", base.targeted_test_command)
        if not isinstance(targeted_test_command, str):
            raise DevfError(
                f"language_profiles.{name}.targeted_test_command must be a string"
            )

        profiles[name] = LanguageProfileConfig(
            enabled=enabled,
            test_file_globs=_parse_str_list(
                test_file_globs, f"language_profiles.{name}.test_file_globs"
            ),
            assertion_patterns=_parse_str_list(
                assertion_patterns, f"language_profiles.{name}.assertion_patterns"
            ),
            trivial_assertions=_parse_str_list(
                trivial_assertions, f"language_profiles.{name}.trivial_assertions"
            ),
            targeted_test_command=targeted_test_command.strip(),
            gate_commands=_parse_str_list(
                gate_commands, f"language_profiles.{name}.gate_commands"
            ),
        )

    return profiles


def _parse_gate_config(raw: Any) -> GateConfig:
    if raw is None:
        return GateConfig()
    if not isinstance(raw, dict):
        raise DevfError("gate must be a mapping")

    mypy_command = raw.get("mypy_command", "")
    if not isinstance(mypy_command, str):
        raise DevfError("gate.mypy_command must be a string")

    ruff_command = raw.get("ruff_command", "")
    if not isinstance(ruff_command, str):
        raise DevfError("gate.ruff_command must be a string")

    max_diff_lines_raw = raw.get("max_diff_lines", 200)
    if not isinstance(max_diff_lines_raw, int) or max_diff_lines_raw <= 0:
        raise DevfError("gate.max_diff_lines must be a positive integer")

    required_checks_raw = raw.get("required_checks", [])
    required_checks = _parse_str_list(required_checks_raw, "gate.required_checks")

    fail_on_skipped_required = raw.get("fail_on_skipped_required", True)
    if not isinstance(fail_on_skipped_required, bool):
        raise DevfError("gate.fail_on_skipped_required must be a boolean")

    security_commands_raw = raw.get("security_commands", [])
    security_commands = _parse_str_list(security_commands_raw, "gate.security_commands")

    pytest_parallel = raw.get("pytest_parallel", False)
    if not isinstance(pytest_parallel, bool):
        raise DevfError("gate.pytest_parallel must be a boolean")

    pytest_workers = raw.get("pytest_workers", "auto")
    if not isinstance(pytest_workers, str) or not pytest_workers.strip():
        raise DevfError("gate.pytest_workers must be a non-empty string")

    pytest_reruns_on_flaky = raw.get("pytest_reruns_on_flaky", 0)
    if not isinstance(pytest_reruns_on_flaky, int) or pytest_reruns_on_flaky < 0:
        raise DevfError("gate.pytest_reruns_on_flaky must be a non-negative integer")

    pytest_random_order = raw.get("pytest_random_order", False)
    if not isinstance(pytest_random_order, bool):
        raise DevfError("gate.pytest_random_order must be a boolean")

    return GateConfig(
        mypy_command=mypy_command,
        ruff_command=ruff_command,
        max_diff_lines=max_diff_lines_raw,
        required_checks=required_checks,
        fail_on_skipped_required=fail_on_skipped_required,
        security_commands=security_commands,
        pytest_parallel=pytest_parallel,
        pytest_workers=pytest_workers.strip(),
        pytest_reruns_on_flaky=pytest_reruns_on_flaky,
        pytest_random_order=pytest_random_order,
    )


def load_config(path: Path) -> tuple[Config, list[str]]:
    if not path.exists():
        raise DevfError(f"config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError("config.yaml must be a mapping")

    warnings: list[str] = []
    known_keys = {
        "test_command",
        "ai_tool",
        "timeout_minutes",
        "max_retries",
        "max_context_bytes",
        "ai_tools",
        "gate",
        "merge_train",
        "circuit_breakers",
        "language_profiles",
        "roles",
    }
    for key in data.keys():
        if key not in known_keys:
            warnings.append(f"unknown config key ignored: {key}")

    test_command = data.get("test_command")
    if not isinstance(test_command, str) or not test_command.strip():
        raise DevfError("test_command is required and must be a string")

    ai_tool = data.get("ai_tool")
    if not isinstance(ai_tool, str) or not ai_tool.strip():
        raise DevfError("ai_tool is required and must be a string")
    _validate_tool_command(ai_tool, "ai_tool")

    timeout_minutes = _validate_positive_int(
        data.get("timeout_minutes", 30), "timeout_minutes"
    )
    max_retries = _validate_positive_int(data.get("max_retries", 3), "max_retries")
    max_context_bytes = _validate_positive_int(
        data.get("max_context_bytes", 120_000), "max_context_bytes"
    )

    ai_tools_raw = data.get("ai_tools", {})
    if not isinstance(ai_tools_raw, dict):
        raise DevfError("ai_tools must be a mapping of name to command")
    ai_tools: dict[str, str] = {}
    for name, command in ai_tools_raw.items():
        if not isinstance(name, str) or not isinstance(command, str):
            raise DevfError("ai_tools must be a mapping of name to command strings")
        _validate_tool_command(command, f"ai_tools.{name}")
        ai_tools[name] = command

    gate = _parse_gate_config(data.get("gate"))

    mt_raw = data.get("merge_train", {})
    if not isinstance(mt_raw, dict):
        raise DevfError("merge_train must be a mapping")
    merge_train = MergeTrainConfig(**mt_raw) if mt_raw else MergeTrainConfig()

    cb_raw = data.get("circuit_breakers", {})
    if not isinstance(cb_raw, dict):
        raise DevfError("circuit_breakers must be a mapping")
    circuit_breakers = CircuitBreakerConfig(**cb_raw) if cb_raw else CircuitBreakerConfig()

    language_profiles = _parse_language_profiles(
        data.get("language_profiles"),
        test_command=test_command.strip(),
        gate=gate,
    )

    roles_raw = data.get("roles", {})
    if not isinstance(roles_raw, dict):
        raise DevfError("roles must be a mapping")

    architect_raw = roles_raw.get("architect")
    architect = _parse_model_config(architect_raw, "roles.architect") if architect_raw else None

    worker_raw = roles_raw.get("worker")
    worker = _parse_model_config(worker_raw, "roles.worker") if worker_raw else None

    tester_raw = roles_raw.get("tester")
    tester = _parse_model_config(tester_raw, "roles.tester") if tester_raw else None

    roles = RolesConfig(architect=architect, worker=worker, tester=tester)

    return (
        Config(
            test_command=test_command.strip(),
            ai_tool=ai_tool.strip(),
            timeout_minutes=timeout_minutes,
            max_retries=max_retries,
            max_context_bytes=max_context_bytes,
            ai_tools=ai_tools,
            gate=gate,
            merge_train=merge_train,
            circuit_breakers=circuit_breakers,
            language_profiles=language_profiles,
            roles=roles,
        ),
        warnings,
    )
