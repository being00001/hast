"""Architect mode: Planning and Goal Generation."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from devf.core.config import Config, load_config
from devf.core.errors import DevfError
from devf.core.goals import Goal
from devf.core.runner import GoalRunner
from devf.core.runners.llm import LLMRunner
from devf.core.runners.local import LocalRunner
from devf.utils.file_parser import parse_file_changes, apply_file_changes


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
    2. Design a new feature or task to fulfill it.
    3. Create a BDD feature file (features/xxx.feature).
    4. Append a new goal to goals.yaml.

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
        raise DevfError(f"Architect failed: {reason}")

    content = result.output

    # Parse output
    changes = parse_file_changes(content)

    new_goal_id = None

    # Apply changes manually to handle 'goals_append.yaml' special case
    for change in changes:
        if change.path == "goals_append.yaml" or change.path.endswith("goals.yaml"):
            # Append to actual goals.yaml
            _append_goals(goals_path, change.content)
            # Try to extract ID
            try:
                data = yaml.safe_load(change.content)
                if isinstance(data, list) and len(data) > 0:
                    new_goal_id = data[0].get("id")
                elif isinstance(data, dict):  # wrapped in goals:?
                    goals_list = data.get("goals", [])
                    if goals_list:
                        new_goal_id = goals_list[0].get("id")
            except Exception:
                pass
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


def _append_goals(path: Path, content: str) -> None:
    """Append new goals to goals.yaml."""
    if not path.exists():
        path.write_text(f"goals:\n{content}", encoding="utf-8")
        return

    # Naive append: parse both, merge lists, dump
    current_text = path.read_text(encoding="utf-8")
    current_data = yaml.safe_load(current_text) or {}
    
    new_data = yaml.safe_load(content)
    
    # Normalize new_data
    new_goals = []
    if isinstance(new_data, list):
        new_goals = new_data
    elif isinstance(new_data, dict) and "goals" in new_data:
        new_goals = new_data["goals"]
    
    if not new_goals:
        return

    current_goals = current_data.get("goals", [])
    if current_goals is None: 
        current_goals = []
        
    current_goals.extend(new_goals)
    current_data["goals"] = current_goals
    
    path.write_text(yaml.safe_dump(current_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
