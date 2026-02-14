"""Tests for evidence-driven feedback inference."""

from __future__ import annotations

import json
from pathlib import Path

from devf.core.feedback_infer import infer_and_store_feedback_notes
from devf.core.feedback_policy import FeedbackPolicy


def _write_evidence(root: Path, run_id: str, rows: list[dict]) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_infer_and_store_feedback_notes(tmp_path: Path) -> None:
    run_id = "20260214T150000+0000"
    _write_evidence(
        tmp_path,
        run_id,
        [
            {
                "timestamp": "2026-02-14T15:00:00+00:00",
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 1,
                "success": False,
                "classification": "failed-impl",
                "failure_classification": "impl-defect",
                "action_taken": "retry",
                "model_used": "worker-model",
            },
            {
                "timestamp": "2026-02-14T15:01:00+00:00",
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 2,
                "success": False,
                "classification": "failed-impl",
                "failure_classification": "impl-defect",
                "action_taken": "retry",
                "model_used": "worker-model",
            },
            {
                "timestamp": "2026-02-14T15:02:00+00:00",
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 3,
                "success": False,
                "classification": "no-progress",
                "failure_classification": "impl-defect",
                "action_taken": "retry",
                "model_used": "worker-model",
            },
            {
                "timestamp": "2026-02-14T15:03:00+00:00",
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 4,
                "success": True,
                "classification": "complete",
                "action_taken": "advance",
            },
        ],
    )

    created = infer_and_store_feedback_notes(tmp_path, run_id, FeedbackPolicy())
    assert created

    notes_fp = tmp_path / ".ai" / "feedback" / "notes.jsonl"
    assert notes_fp.exists()
    lines = [line for line in notes_fp.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2
