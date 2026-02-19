"""Tests for auto summary builder."""

from __future__ import annotations

import json
from pathlib import Path

from hast.core.auto_summary import build_auto_summary


def _write_evidence(tmp_path: Path, run_id: str, rows: list[dict]) -> None:
    run_dir = tmp_path / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fp = run_dir / "evidence.jsonl"
    with fp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_auto_summary_empty_run(tmp_path: Path) -> None:
    summary = build_auto_summary(tmp_path, "run1", 0)
    assert summary["exit_code"] == 0
    assert summary["run_id"] == "run1"
    assert summary["goals_processed"] == []
    assert summary["changed_files"] == []
    assert summary["evidence_summary"]["total_rows"] == 0


def test_build_auto_summary_with_rows(tmp_path: Path) -> None:
    rows = [
        {
            "goal_id": "G1",
            "success": True,
            "classification": "advance",
            "phase": "implement",
            "action_taken": "advance",
            "risk_score": 20,
            "changed_files": ["src/a.py"],
        },
        {
            "goal_id": "G2",
            "success": False,
            "classification": "impl-defect",
            "phase": "implement",
            "action_taken": "retry",
            "risk_score": 40,
            "changed_files": ["src/b.py"],
        },
    ]
    _write_evidence(tmp_path, "run1", rows)
    summary = build_auto_summary(tmp_path, "run1", 1)
    assert summary["exit_code"] == 1
    assert len(summary["goals_processed"]) == 2
    assert summary["goals_processed"][0]["id"] == "G1"
    assert summary["goals_processed"][0]["success"] is True
    assert summary["goals_processed"][1]["id"] == "G2"
    assert summary["goals_processed"][1]["success"] is False
    assert sorted(summary["changed_files"]) == ["src/a.py", "src/b.py"]
    assert summary["evidence_summary"]["total_rows"] == 2
    assert summary["evidence_summary"]["successes"] == 1
    assert summary["evidence_summary"]["failures"] == 1


def test_build_auto_summary_changed_files_deduplicated(tmp_path: Path) -> None:
    rows = [
        {"goal_id": "G1", "success": True, "changed_files": ["src/a.py", "src/b.py"]},
        {"goal_id": "G1", "success": True, "changed_files": ["src/a.py", "src/c.py"]},
    ]
    _write_evidence(tmp_path, "run1", rows)
    summary = build_auto_summary(tmp_path, "run1", 0)
    assert sorted(summary["changed_files"]) == ["src/a.py", "src/b.py", "src/c.py"]


def test_aggregate_goals_takes_last_row(tmp_path: Path) -> None:
    rows = [
        {"goal_id": "G1", "success": False, "phase": "implement", "action_taken": "retry"},
        {"goal_id": "G1", "success": True, "phase": "merge", "action_taken": "advance"},
    ]
    _write_evidence(tmp_path, "run1", rows)
    summary = build_auto_summary(tmp_path, "run1", 0)
    assert len(summary["goals_processed"]) == 1
    assert summary["goals_processed"][0]["success"] is True
    assert summary["goals_processed"][0]["phase"] == "merge"
