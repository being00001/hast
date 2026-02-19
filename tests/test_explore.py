"""Tests for read-only design exploration."""

from __future__ import annotations

from pathlib import Path

from hast.core.explore import explore_question


def _seed_explore_project(root: Path) -> None:
    (root / "core").mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    (root / "core" / "economy.py").write_text(
        """\
class EconomyPort:
    def evaluate(self, value: int, mode: str = "safe") -> int:
        return value
""",
        encoding="utf-8",
    )
    (root / "app" / "vitals_loop.py").write_text(
        """\
from core.economy import EconomyPort


def tick(v: int) -> int:
    port = EconomyPort()
    return port.evaluate(v)
""",
        encoding="utf-8",
    )
    (root / "tests" / "test_economy.py").write_text(
        """\
from core.economy import EconomyPort


def test_evaluate() -> None:
    assert EconomyPort().evaluate(1) == 1
""",
        encoding="utf-8",
    )


def test_explore_question_finds_matches_and_impact(tmp_project: Path) -> None:
    _seed_explore_project(tmp_project)

    report = explore_question(
        tmp_project,
        "EconomyPort.evaluate()가 perform_deployment_actions 파라미터를 지원하려면?",
    )

    assert report.matches
    assert any(m.symbol == "EconomyPort.evaluate" for m in report.matches)
    assert "core/economy.py" in report.callers_by_file
    assert "app/vitals_loop.py" in report.callers_by_file["core/economy.py"]
    assert report.impact["matched_files"] >= 1
    assert len(report.approaches) == 3
    assert report.approaches[0].name == "Backward-Compatible Signature Extension"
