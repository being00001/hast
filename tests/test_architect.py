"""Tests for Architect mode."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hast.core.architect import plan_goals
from hast.core.errors import HastError
from hast.core.runner import GoalRunner, RunnerResult


class _StubRunner(GoalRunner):
    def __init__(self, result: RunnerResult) -> None:
        self._result = result

    def run(self, root: Path, config, goal, prompt: str, tool_name: str | None = None) -> RunnerResult:  # type: ignore[override]
        return self._result


@pytest.fixture
def mock_root(tmp_path: Path) -> Path:
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "config.yaml").write_text(
        """
test_command: pytest
ai_tool: "cat {prompt_file}"
""",
        encoding="utf-8",
    )
    return tmp_path


def test_plan_goals_creates_files(mock_root: Path) -> None:
    result = RunnerResult(
        success=True,
        output="""
Here is the plan:

```gherkin:features/login.feature
Feature: Login
  Scenario: Success
```

```yaml:goals_append.yaml
- id: G_LOGIN
  title: Login Feature
  status: active
  spec_file: features/login.feature
```
""",
    )
    goal_id = plan_goals(mock_root, "implement login", runner=_StubRunner(result))

    assert goal_id == "G_LOGIN"

    feature_file = mock_root / "features" / "login.feature"
    assert feature_file.exists()
    assert "Feature: Login" in feature_file.read_text(encoding="utf-8")

    goals_file = mock_root / ".ai" / "goals.yaml"
    assert goals_file.exists()
    data = yaml.safe_load(goals_file.read_text(encoding="utf-8"))
    assert len(data["goals"]) == 1
    assert data["goals"][0]["id"] == "G_LOGIN"
    assert data["goals"][0]["spec_file"] == "features/login.feature"


def test_plan_goals_no_output(mock_root: Path) -> None:
    result = RunnerResult(success=True, output="I cannot do that.")
    goal_id = plan_goals(mock_root, "implement login", runner=_StubRunner(result))
    assert goal_id is None
    assert not (mock_root / ".ai" / "goals.yaml").exists()


def test_plan_goals_runner_failure(mock_root: Path) -> None:
    result = RunnerResult(success=False, output="", error_message="boom")
    with pytest.raises(HastError, match="boom"):
        plan_goals(mock_root, "implement login", runner=_StubRunner(result))


def test_plan_goals_tool_name_passed_to_local_runner(mock_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {"tool_name": None}

    def _fake_run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        captured["tool_name"] = tool_name
        return RunnerResult(
            success=True,
            output="""```yaml:goals_append.yaml
- id: G_TOOL
  title: Tool Goal
  status: active
```""",
        )

    monkeypatch.setattr("hast.core.architect.LocalRunner.run", _fake_run)
    goal_id = plan_goals(mock_root, "tool check", tool_name="codex")
    assert goal_id == "G_TOOL"
    assert captured["tool_name"] == "codex"


def test_plan_goals_llm_runner_uses_architect_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "config.yaml").write_text(
        """
test_command: pytest
ai_tool: "echo {prompt}"
roles:
  architect:
    model: test-architect
""",
        encoding="utf-8",
    )

    captured: dict[str, str | None] = {"tool_name": None}

    def _fake_run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        captured["tool_name"] = tool_name
        return RunnerResult(
            success=True,
            output="""```yaml:goals_append.yaml
- id: G_LLM
  title: LLM Goal
  status: active
```""",
        )

    monkeypatch.setattr("hast.core.architect.LLMRunner.run", _fake_run)
    goal_id = plan_goals(tmp_path, "llm check")
    assert goal_id == "G_LLM"
    assert captured["tool_name"] == "architect"


def test_plan_goals_annotates_decision_required_goal(mock_root: Path) -> None:
    result = RunnerResult(
        success=True,
        output="""```yaml:goals_append.yaml
- id: G_API
  title: "Design API surface"
  status: active
  uncertainty: high
```""",
    )

    goal_id = plan_goals(mock_root, "plan api refactor", runner=_StubRunner(result))
    assert goal_id == "G_API"

    data = yaml.safe_load((mock_root / ".ai" / "goals.yaml").read_text(encoding="utf-8"))
    goal = data["goals"][0]
    assert goal["decision_required"] is True
    assert goal["auto_eligible"] is False
    assert str(goal["blocked_by"]).startswith("DECISION:")


def test_plan_goals_respects_explicit_execution_metadata(mock_root: Path) -> None:
    result = RunnerResult(
        success=True,
        output="""```yaml:goals_append.yaml
- id: G_IMPL
  title: "Mechanical rename"
  status: active
  decision_required: false
  auto_eligible: true
```""",
    )

    goal_id = plan_goals(mock_root, "rename variable", runner=_StubRunner(result))
    assert goal_id == "G_IMPL"

    data = yaml.safe_load((mock_root / ".ai" / "goals.yaml").read_text(encoding="utf-8"))
    goal = data["goals"][0]
    assert goal["decision_required"] is False
    assert goal["auto_eligible"] is True
    assert "blocked_by" not in goal
