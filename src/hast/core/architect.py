"""Architect mode: Planning and Goal Generation."""

from __future__ import annotations

import sys
from pathlib import Path
import re
from typing import Any

import yaml

from hast.core.config import Config, load_config
from hast.core.errors import HastError
from hast.core.goals import Goal
from hast.core.runner import GoalRunner
from hast.core.runners.llm import LLMRunner
from hast.core.runners.local import LocalRunner
from hast.utils.file_parser import parse_file_changes, apply_file_changes


def plan_goals(
    root: Path,
    instruction: str,
    tool_name: str | None = None,
    runner: GoalRunner | None = None,
) -> str | None:
    """Run the Architect loop to generate goals and feature files."""

    config, _ = load_config(root / ".ai" / "config.yaml")
    selected_runner = _select_runner(config, tool_name, runner)

    # 1. Gather Context
    goals_path = root / ".ai" / "goals.yaml"
    current_goals = goals_path.read_text(encoding="utf-8") if goals_path.exists() else "goals: []"

    # Read docs if instruction is vague?
    # For now, let's rely on the instruction.

    prompt = f"""
    You are the Chief Architect of this software project.

    CURRENT GOALS (goals.yaml):
    {current_goals}

    USER INSTRUCTION:
    "{instruction}"

    TASK:
    1. Analyze the instruction.
    2. Design one or more goals to fulfill it.
    3. Create a BDD feature file (features/xxx.feature).
    4. Append new goals to goals.yaml.

    PLANNING INTELLIGENCE:
    - For each new goal include:
      - auto_eligible: true/false
      - decision_required: true/false
      - blocked_by: "DECISION: ..." when design decision must be made first
    - If design/interface ambiguity exists, set auto_eligible=false and decision_required=true.

    OUTPUT FORMAT:
    Provide the content of the new files in markdown code blocks.

    Example:
    ```gherkin:features/new_feature.feature
    Feature: New Capability
      Scenario: ...
    ```

    ```yaml:goals_append.yaml
    - id: G_NEW
      title: "Implement New Capability"
      status: active
      spec_file: "features/new_feature.feature"
      phase: implement
      auto_eligible: true
      decision_required: false
    ```
    """

    print(f"[Architect] Thinking about: {instruction}...", file=sys.stderr)

    synthetic_goal = Goal(id="PLAN", title="Architect Planning", status="active")
    runner_tool_name = tool_name
    if runner_tool_name is None and isinstance(selected_runner, LLMRunner):
        runner_tool_name = "architect"

    result = selected_runner.run(
        root=root,
        config=config,
        goal=synthetic_goal,
        prompt=prompt,
        tool_name=runner_tool_name,
    )

    if not result.success:
        reason = result.error_message or "unknown runner failure"
        raise HastError(f"Architect failed: {reason}")

    content = result.output

    # Parse output
    changes = parse_file_changes(content)

    new_goal_id = None

    # Apply changes manually to handle 'goals_append.yaml' special case
    for change in changes:
        if change.path == "goals_append.yaml" or change.path.endswith("goals.yaml"):
            # Append to actual goals.yaml
            appended_goals = _append_goals(goals_path, change.content)
            if appended_goals and new_goal_id is None:
                candidate = appended_goals[0].get("id")
                if isinstance(candidate, str) and candidate.strip():
                    new_goal_id = candidate.strip()
        else:
            # Normal file (feature file)
            apply_file_changes(root, [change])
            print(f"[Architect] Created {change.path}", file=sys.stderr)

    if new_goal_id:
        print(f"[Architect] Goal created: {new_goal_id}", file=sys.stderr)
        return new_goal_id

    print("[Architect] No goal ID found in output.", file=sys.stderr)
    return None


def _select_runner(
    config: Config,
    tool_name: str | None,
    runner: GoalRunner | None,
) -> GoalRunner:
    if runner is not None:
        return runner

    # Explicit CLI tool selection is process-based by design (config.ai_tools).
    if tool_name:
        return LocalRunner()

    # If architect role model exists, use API-based runner.
    architect_conf = config.roles.architect
    if architect_conf and architect_conf.model:
        return LLMRunner()

    # Fallback: shell-based local runner.
    return LocalRunner()


def _append_goals(path: Path, content: str) -> list[dict[str, Any]]:
    """Append new goals to goals.yaml."""
    data: dict[str, Any]
    if not path.exists():
        data = {}
    else:
        current_text = path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(current_text) or {}
        if not isinstance(loaded, dict):
            loaded = {}
        data = loaded

    new_data = yaml.safe_load(content)

    # Normalize new_data
    new_goals: list[dict[str, Any]] = []
    if isinstance(new_data, list):
        new_goals = [item for item in new_data if isinstance(item, dict)]
    elif isinstance(new_data, dict) and "goals" in new_data:
        raw = new_data["goals"]
        if isinstance(raw, list):
            new_goals = [item for item in raw if isinstance(item, dict)]

    if not new_goals:
        return []

    for goal in new_goals:
        _annotate_goal_execution_metadata(goal)

    current_goals = data.get("goals", [])
    if current_goals is None:
        current_goals = []
    if not isinstance(current_goals, list):
        current_goals = []

    current_goals.extend(new_goals)
    data["goals"] = current_goals

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return new_goals


def _annotate_goal_execution_metadata(goal: dict[str, Any]) -> None:
    """Attach execution-planning hints for auto loop operators.

    This is metadata-only and does not force status changes.
    """
    title = str(goal.get("title") or "")
    notes = str(goal.get("notes") or "")
    blocked_by = str(goal.get("blocked_by") or "")
    uncertainty = str(goal.get("uncertainty") or "").strip().lower()
    decision_file = str(goal.get("decision_file") or "").strip()

    decision_required = _as_optional_bool(goal.get("decision_required"))
    if decision_required is None:
        has_decision_terms = bool(_DECISION_HINT_RE.search(f"{title}\n{notes}\n{blocked_by}"))
        decision_required = (
            uncertainty == "high"
            or bool(decision_file)
            or has_decision_terms
        )
    goal["decision_required"] = decision_required

    auto_eligible = _as_optional_bool(goal.get("auto_eligible"))
    if auto_eligible is None:
        auto_eligible = not decision_required
    goal["auto_eligible"] = auto_eligible

    if decision_required and not auto_eligible and not blocked_by:
        if decision_file:
            goal["blocked_by"] = f"DECISION: accept {decision_file}"
        else:
            goal["blocked_by"] = "DECISION: interface/contract decision required"


def _as_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


_DECISION_HINT_RE = re.compile(
    r"\b(decision|interface|contract|api|signature|trade[- ]?off|clarify)\b",
    flags=re.IGNORECASE,
)
