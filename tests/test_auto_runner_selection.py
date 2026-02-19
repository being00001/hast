"""Tests for auto runner selection routing."""

from __future__ import annotations

from hast.core.auto import _resolve_runner
from hast.core.config import Config, ModelConfig, RolesConfig
from hast.core.runners.llm import LLMRunner
from hast.core.runners.local import LocalRunner
from hast.core.runners.protocol import ProtocolRunner


def test_resolve_runner_prefers_explicit_runner() -> None:
    config = Config(test_command="true", ai_tool="echo {prompt}")
    explicit = LocalRunner()
    resolved = _resolve_runner(config, "langgraph", explicit)
    assert resolved is explicit


def test_resolve_runner_uses_protocol_runner_for_adapter_tool() -> None:
    config = Config(test_command="true", ai_tool="echo {prompt}")
    resolved = _resolve_runner(config, "langgraph", None)
    assert isinstance(resolved, ProtocolRunner)


def test_resolve_runner_uses_llm_when_roles_configured() -> None:
    config = Config(
        test_command="true",
        ai_tool="echo {prompt}",
        roles=RolesConfig(worker=ModelConfig(model="anthropic/claude-3-5-sonnet")),
    )
    resolved = _resolve_runner(config, None, None)
    assert isinstance(resolved, LLMRunner)


def test_resolve_runner_defaults_to_local() -> None:
    config = Config(test_command="true", ai_tool="echo {prompt}")
    resolved = _resolve_runner(config, None, None)
    assert isinstance(resolved, LocalRunner)

