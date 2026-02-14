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


@dataclass(frozen=True)
class CircuitBreakerConfig:
    max_cycles_per_session: int = 10
    max_consecutive_no_progress: int = 3


@dataclass(frozen=True)
class Config:
    test_command: str
    ai_tool: str
    timeout_minutes: int = 30
    max_retries: int = 3
    max_context_bytes: int = 120_000
    ai_tools: dict[str, str] = field(default_factory=dict)
    gate: GateConfig = field(default_factory=GateConfig)
    circuit_breakers: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


def _validate_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise DevfError(f"{field_name} must be a positive integer")
    return value


def _validate_tool_command(command: str, field_name: str) -> None:
    if "{prompt}" not in command and "{prompt_file}" not in command:
        raise DevfError(f"{field_name} must include {{prompt}} or {{prompt_file}}")


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
        "circuit_breakers",
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

    gate_raw = data.get("gate", {})
    if not isinstance(gate_raw, dict):
        raise DevfError("gate must be a mapping")
    gate = GateConfig(**gate_raw) if gate_raw else GateConfig()

    cb_raw = data.get("circuit_breakers", {})
    if not isinstance(cb_raw, dict):
        raise DevfError("circuit_breakers must be a mapping")
    circuit_breakers = CircuitBreakerConfig(**cb_raw) if cb_raw else CircuitBreakerConfig()

    return (
        Config(
            test_command=test_command.strip(),
            ai_tool=ai_tool.strip(),
            timeout_minutes=timeout_minutes,
            max_retries=max_retries,
            max_context_bytes=max_context_bytes,
            ai_tools=ai_tools,
            gate=gate,
            circuit_breakers=circuit_breakers,
        ),
        warnings,
    )
