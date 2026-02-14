"""Tests for phase transition and template loading."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from devf.core.goals import Goal
from devf.core.phase import (
    PHASE_ORDER,
    advance_phase,
    load_phase_template,
    next_phase,
    parse_plan_output,
    regress_phase,
)


def _make_goal(**overrides: object) -> Goal:
    defaults: dict = {
        "id": "G1",
        "title": "Test Goal",
        "status": "active",
        "phase": "implement",
    }
    defaults.update(overrides)
    return Goal(**defaults)  # type: ignore[arg-type]


def test_phase_order():
    assert PHASE_ORDER == ["plan", "implement", "gate", "adversarial", "merge"]


def test_next_phase():
    assert next_phase("plan") == "implement"
    assert next_phase("implement") == "gate"
    assert next_phase("gate") == "adversarial"
    assert next_phase("adversarial") == "merge"
    assert next_phase("merge") is None


def test_regress_phase():
    assert regress_phase("gate") == "implement"
    assert regress_phase("adversarial") == "implement"


def test_load_phase_template_exists(tmp_path: Path):
    tpl_dir = tmp_path / ".ai" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "implement.md.j2").write_text(
        "Goal: {{ goal.id }}\nTitle: {{ goal.title }}"
    )
    tpl = load_phase_template(tmp_path, "implement")
    assert tpl is not None
    goal = _make_goal()
    rendered = tpl.render(goal=goal)
    assert "Goal: G1" in rendered
    assert "Title: Test Goal" in rendered


def test_load_phase_template_missing(tmp_path: Path):
    # No .ai/templates dir at all
    assert load_phase_template(tmp_path, "implement") is None


def test_load_phase_template_unknown_phase(tmp_path: Path):
    tpl_dir = tmp_path / ".ai" / "templates"
    tpl_dir.mkdir(parents=True)
    assert load_phase_template(tmp_path, "unknown") is None


def test_parse_plan_output_valid():
    output = textwrap.dedent("""\
        Here is the plan:

        ```yaml
        goal_update:
          acceptance:
            - "테스트 통과"
          edge_cases:
            - "빈 입력"
        ```

        Done.
    """)
    result = parse_plan_output(output)
    assert result is not None
    assert result["acceptance"] == ["테스트 통과"]
    assert result["edge_cases"] == ["빈 입력"]


def test_parse_plan_output_no_yaml():
    output = "This is just plain text with no code blocks."
    assert parse_plan_output(output) is None


def test_parse_plan_output_invalid_yaml():
    output = textwrap.dedent("""\
        ```yaml
        this is: [not: valid: yaml
        ```
    """)
    assert parse_plan_output(output) is None
