"""Tests for LLMRunner."""

from unittest.mock import MagicMock, patch

import pytest

from devf.core.config import Config, ModelConfig, RolesConfig
from devf.core.goals import Goal
from devf.core.runners.llm import LLMRunner


@pytest.fixture
def config():
    return Config(
        test_command="pytest",
        ai_tool="dummy",
        roles=RolesConfig(
            worker=ModelConfig(model="test-model", temperature=0.5)
        )
    )


@pytest.fixture
def goal():
    return Goal(id="G1", title="Test Goal", status="active")


def test_llm_runner_success(tmp_path, config, goal):
    runner = LLMRunner()

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Here is the code."

    with patch("devf.core.runners.llm.completion", return_value=mock_response) as mock_compl:
        result = runner.run(tmp_path, config, goal, "do something", tool_name="worker")

        assert result.success
        assert result.output == "Here is the code."

        mock_compl.assert_called_once()
        args, kwargs = mock_compl.call_args
        assert kwargs["model"] == "test-model"
        assert kwargs["temperature"] == 0.5


def test_llm_runner_missing_config(tmp_path, goal):
    # Config without worker model
    empty_config = Config(
        test_command="pytest",
        ai_tool="dummy",
        roles=RolesConfig() # No worker
    )

    runner = LLMRunner()
    result = runner.run(tmp_path, empty_config, goal, "prompt", tool_name="worker")

    assert not result.success
    assert "No model configuration" in result.error_message


def test_llm_runner_exception(tmp_path, config, goal):
    runner = LLMRunner()

    with patch("devf.core.runners.llm.completion", side_effect=Exception("API Error")):
        result = runner.run(tmp_path, config, goal, "prompt", tool_name="worker")

        assert not result.success
        assert "LLM execution failed" in result.error_message
        assert "API Error" in result.error_message
