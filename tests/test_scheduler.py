"""Tests for goal dependency scheduler."""

from __future__ import annotations

from hast.core.errors import HastError
from hast.core.goals import Goal
from hast.core.scheduler import build_execution_batches


def _goal(
    goal_id: str,
    status: str = "active",
    depends_on: list[str] | None = None,
) -> Goal:
    return Goal(
        id=goal_id,
        title=goal_id,
        status=status,
        depends_on=depends_on or [],
    )


def test_build_execution_batches_linear() -> None:
    g1 = _goal("G1")
    g2 = _goal("G2", depends_on=["G1"])
    g3 = _goal("G3", depends_on=["G2"])
    batches = build_execution_batches([g1, g2, g3], [g1, g2, g3])
    assert [[g.id for g in batch] for batch in batches] == [["G1"], ["G2"], ["G3"]]


def test_build_execution_batches_parallel_ready() -> None:
    g1 = _goal("G1")
    g2 = _goal("G2")
    g3 = _goal("G3", depends_on=["G1", "G2"])
    batches = build_execution_batches([g1, g2, g3], [g1, g2, g3])
    assert [sorted(g.id for g in batch) for batch in batches] == [["G1", "G2"], ["G3"]]


def test_build_execution_batches_external_done_dependency() -> None:
    g0 = _goal("G0", status="done")
    g1 = _goal("G1", depends_on=["G0"])
    batches = build_execution_batches([g0, g1], [g1])
    assert [[g.id for g in batch] for batch in batches] == [["G1"]]


def test_build_execution_batches_external_unsatisfied_dependency() -> None:
    g0 = _goal("G0", status="active")
    g1 = _goal("G1", depends_on=["G0"])
    try:
        build_execution_batches([g0, g1], [g1])
    except HastError as exc:
        assert "dependency not satisfied" in str(exc)
    else:
        raise AssertionError("expected dependency satisfaction error")


def test_build_execution_batches_cycle_detected() -> None:
    g1 = _goal("G1", depends_on=["G2"])
    g2 = _goal("G2", depends_on=["G1"])
    try:
        build_execution_batches([g1, g2], [g1, g2])
    except HastError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("expected cycle error")
