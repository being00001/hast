"""Tests for AutoResult and GoalResult dataclasses."""

from __future__ import annotations

from hast.core.result import AutoResult, GoalResult


def test_goal_result_fields() -> None:
    gr = GoalResult(id="G1", success=True, classification="advance", phase="merge")
    assert gr.id == "G1"
    assert gr.success is True
    assert gr.classification == "advance"
    assert gr.phase == "merge"
    assert gr.action_taken is None
    assert gr.risk_score is None


def test_auto_result_success_property() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[GoalResult(id="G1", success=True)],
        changed_files=["src/a.py"],
        evidence_summary={"total_rows": 1, "successes": 1, "failures": 0},
        errors=[],
    )
    assert r.success is True
    assert r.exit_code == 0


def test_auto_result_failure() -> None:
    r = AutoResult(
        exit_code=1,
        run_id="run2",
        goals=[GoalResult(id="G1", success=False)],
        changed_files=[],
        evidence_summary={"total_rows": 1, "successes": 0, "failures": 1},
        errors=["test failed"],
    )
    assert r.success is False
    assert r.errors == ["test failed"]


def test_auto_result_to_dict() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[
            GoalResult(id="G1", success=True, classification="advance", phase="merge",
                       action_taken="advance", risk_score=25),
        ],
        changed_files=["src/a.py", "src/b.py"],
        evidence_summary={"total_rows": 2, "successes": 2, "failures": 0},
        errors=[],
    )
    d = r.to_dict()
    assert d["exit_code"] == 0
    assert d["run_id"] == "run1"
    assert len(d["goals_processed"]) == 1
    assert d["goals_processed"][0]["id"] == "G1"
    assert d["goals_processed"][0]["success"] is True
    assert d["goals_processed"][0]["risk_score"] == 25
    assert d["changed_files"] == ["src/a.py", "src/b.py"]
    assert d["errors"] == []


def test_auto_result_to_dict_empty() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[],
        changed_files=[],
        evidence_summary={"total_rows": 0},
        errors=[],
    )
    d = r.to_dict()
    assert d["goals_processed"] == []
    assert d["changed_files"] == []


def test_public_api_imports() -> None:
    """Verify public API is accessible from top-level package."""
    import hast

    assert hasattr(hast, "AutoResult")
    assert hasattr(hast, "GoalResult")
    assert hasattr(hast, "Config")
    assert hasattr(hast, "load_config")
    assert hasattr(hast, "resolve_ai_dir")
    assert hasattr(hast, "resolve_config_path")
