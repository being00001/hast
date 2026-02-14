"""Tests for goals parsing and selection."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from devf.core.errors import DevfError
from devf.core.goals import (
    Goal,
    collect_goals,
    find_goal,
    iter_goals,
    load_goals,
    select_active_goal,
    update_goal_fields,
    update_goal_status,
)


def _write_goals(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_load_empty(tmp_path: Path) -> None:
    p = tmp_path / "goals.yaml"
    p.write_text("goals: []\n", encoding="utf-8")
    assert load_goals(p) == []


def test_load_missing_file(tmp_path: Path) -> None:
    assert load_goals(tmp_path / "nope.yaml") == []


def test_load_basic_tree(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: M1
            title: "Feature"
            status: active
            children:
              - id: M1.1
                title: "Sub"
                status: pending
    """)
    goals = load_goals(p)
    assert len(goals) == 1
    assert goals[0].id == "M1"
    assert len(goals[0].children) == 1
    assert goals[0].children[0].id == "M1.1"


def test_duplicate_id(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: X
            title: A
            status: active
          - id: X
            title: B
            status: pending
    """)
    with pytest.raises(DevfError, match="duplicate"):
        load_goals(p)


def test_invalid_status(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: X
            title: A
            status: unknown
    """)
    with pytest.raises(DevfError, match="status invalid"):
        load_goals(p)


def test_iter_goals() -> None:
    child = Goal(id="M1.1", title="Sub", status="active")
    root = Goal(id="M1", title="Root", status="active", children=[child])
    nodes = list(iter_goals([root]))
    assert len(nodes) == 2
    assert nodes[0].goal.id == "M1"
    assert nodes[0].depth == 0
    assert nodes[1].goal.id == "M1.1"
    assert nodes[1].depth == 1
    assert nodes[1].parent is root


def test_find_goal() -> None:
    child = Goal(id="M1.1", title="Sub", status="active")
    root = Goal(id="M1", title="Root", status="active", children=[child])
    assert find_goal([root], "M1.1") is child
    assert find_goal([root], "nope") is None


def test_select_active_goal_deepest() -> None:
    child = Goal(id="M1.1", title="Sub", status="active")
    root = Goal(id="M1", title="Root", status="active", children=[child])
    selected = select_active_goal([root], preferred_id=None)
    assert selected is not None
    assert selected.id == "M1.1"


def test_select_active_goal_preferred() -> None:
    a = Goal(id="A", title="A", status="active")
    b = Goal(id="B", title="B", status="active")
    selected = select_active_goal([a, b], preferred_id="B")
    assert selected is not None
    assert selected.id == "B"


def test_select_active_goal_skips_interactive() -> None:
    a = Goal(id="A", title="A", status="active", mode="interactive")
    b = Goal(id="B", title="B", status="active")
    selected = select_active_goal([a, b], preferred_id=None)
    assert selected is not None
    assert selected.id == "B"


def test_collect_goals_non_recursive() -> None:
    child = Goal(id="M1.1", title="Sub", status="active")
    root = Goal(id="M1", title="Root", status="active", children=[child])
    result = collect_goals([root], "M1.1", recursive=False)
    assert len(result) == 1
    assert result[0].id == "M1.1"


def test_collect_goals_recursive() -> None:
    c1 = Goal(id="M1.1", title="A", status="active")
    c2 = Goal(id="M1.2", title="B", status="pending")
    c3 = Goal(id="M1.3", title="C", status="active", mode="interactive")
    root = Goal(id="M1", title="Root", status="active", children=[c1, c2, c3])
    result = collect_goals([root], "M1", recursive=True)
    ids = [g.id for g in result]
    assert "M1" in ids
    assert "M1.1" in ids
    assert "M1.2" not in ids  # pending
    assert "M1.3" not in ids  # interactive


def test_collect_goals_recursive_requires_id() -> None:
    with pytest.raises(DevfError, match="goal_id is required"):
        collect_goals([], None, recursive=True)


def test_update_goal_status(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: M1
            title: "Feature"
            status: active
            children:
              - id: M1.1
                title: "Sub"
                status: active
    """)
    update_goal_status(p, "M1.1", "done")
    goals = load_goals(p)
    sub = find_goal(goals, "M1.1")
    assert sub is not None
    assert sub.status == "done"


def test_goal_optional_fields(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "TDD"
            status: active
            expect_failure: true
            allowed_changes: ["src/*.py"]
            prompt_mode: adversarial
            tool: codex
    """)
    goals = load_goals(p)
    g = goals[0]
    assert g.expect_failure is True
    assert g.allowed_changes == ["src/*.py"]
    assert g.prompt_mode == "adversarial"
    assert g.tool == "codex"


def test_goal_notes_and_acceptance(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Login"
            status: active
            notes: |
              JWT 사용, bcrypt for hashing
            acceptance:
              - "pytest tests/test_auth.py 통과"
              - "POST /auth/login 동작"
    """)
    goals = load_goals(p)
    g = goals[0]
    assert "JWT" in (g.notes or "")
    assert len(g.acceptance) == 2
    assert "pytest" in g.acceptance[0]


def test_goal_notes_and_acceptance_defaults() -> None:
    g = Goal(id="G1", title="Test", status="active")
    assert g.notes is None
    assert g.acceptance == []


def test_goal_invalid_notes(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Test"
            status: active
            notes: 123
    """)
    with pytest.raises(DevfError, match="notes must be a string"):
        load_goals(p)


def test_goal_invalid_acceptance(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Test"
            status: active
            acceptance: "not a list"
    """)
    with pytest.raises(DevfError, match="acceptance must be a list"):
        load_goals(p)


def test_update_goal_fields_phase(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Test"
            status: active
            phase: plan
    """)
    update_goal_fields(p, "G1", {"phase": "implement"})
    goals = load_goals(p)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.phase == "implement"


def test_update_goal_fields_multiple(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Test"
            status: active
    """)
    update_goal_fields(p, "G1", {
        "phase": "implement",
        "acceptance": ["cond1", "cond2"],
        "edge_cases": ["edge1"],
    })
    goals = load_goals(p)
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.phase == "implement"
    assert g.acceptance == ["cond1", "cond2"]
    assert g.edge_cases == ["edge1"]


def test_update_goal_fields_nested(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: M1
            title: "Parent"
            status: active
            children:
              - id: M1.1
                title: "Child"
                status: active
                phase: plan
    """)
    update_goal_fields(p, "M1.1", {"phase": "gate"})
    goals = load_goals(p)
    g = find_goal(goals, "M1.1")
    assert g is not None
    assert g.phase == "gate"


def test_update_goal_fields_not_found(tmp_path: Path) -> None:
    p = _write_goals(tmp_path / "goals.yaml", """\
        goals:
          - id: G1
            title: "Test"
            status: active
    """)
    with pytest.raises(DevfError, match="goal not found"):
        update_goal_fields(p, "NOPE", {"phase": "gate"})
