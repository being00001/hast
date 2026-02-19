"""Tests for productivity orchestration."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

import pytest

from hast.core.errors import DevfError
from hast.core.feedback import create_feedback_note, write_feedback_note
from hast.core.orchestrator import orchestrate_productivity_cycle


def _write_evidence(root: Path, run_id: str, rows: list[dict]) -> None:
    run_dir = root / ".ai" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_orchestrate_productivity_cycle_adds_goals(tmp_path: Path) -> None:
    run_id = "20260214T230000+0000"
    _write_evidence(
        tmp_path,
        run_id,
        [
            {
                "timestamp": "2026-02-14T23:00:00+00:00",
                "run_id": run_id,
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
                "timestamp": "2026-02-14T23:01:00+00:00",
                "run_id": run_id,
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
                "timestamp": "2026-02-14T23:02:00+00:00",
                "run_id": run_id,
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
                "timestamp": "2026-02-14T23:03:00+00:00",
                "run_id": run_id,
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 4,
                "success": True,
                "classification": "complete",
                "action_taken": "advance",
            },
        ],
    )
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v1
            enabled: true
            promotion:
              min_frequency: 1
              min_confidence: 0.5
              auto_promote_impact: high
            dedup:
              strategy: fingerprint_v1
            publish:
              enabled: false
              backend: codeberg
              repository: ""
              token_env: CODEBERG_TOKEN
              base_url: https://codeberg.org
              labels: [bot-reported, hast-feedback]
              min_status: accepted
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")

    result = orchestrate_productivity_cycle(
        tmp_path,
        run_id=run_id,
        window_days=30,
        max_goals=3,
        publish=False,
        publish_dry_run=False,
    )

    assert result.inferred_notes >= 1
    assert result.accepted_items >= 1
    assert result.goals_added >= 1

    goals_text = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "id: PX_2X" in goals_text
    assert "feedback_key:" in goals_text


def test_orchestrate_ignores_tool_lane_for_goal_sync(tmp_path: Path) -> None:
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v1
            enabled: true
            promotion:
              min_frequency: 1
              min_confidence: 0.5
              auto_promote_impact: high
            dedup:
              strategy: fingerprint_v1
            publish:
              enabled: false
              backend: codeberg
              repository: ""
              token_env: CODEBERG_TOKEN
              base_url: https://codeberg.org
              labels: [bot-reported, hast-feedback]
              min_status: accepted
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")

    write_feedback_note(
        tmp_path,
        create_feedback_note(
            run_id=None,
            goal_id=None,
            phase=None,
            source="worker_explicit",
            lane="project",
            category="workflow_friction",
            impact="high",
            expected="project feedback should become goal",
            actual="project flow friction",
            workaround="",
            confidence=0.9,
        ),
    )
    write_feedback_note(
        tmp_path,
        create_feedback_note(
            run_id=None,
            goal_id=None,
            phase=None,
            source="worker_explicit",
            lane="tool",
            category="workflow_friction",
            impact="high",
            expected="tool feedback should not become project goal",
            actual="tool flow friction",
            workaround="",
            confidence=0.9,
        ),
    )

    result = orchestrate_productivity_cycle(
        tmp_path,
        run_id=None,
        window_days=30,
        max_goals=10,
        publish=False,
        publish_dry_run=False,
    )
    assert result.accepted_items == 1
    assert result.goals_added == 1

    goals_text = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "project feedback should become goal" in goals_text
    assert "tool feedback should not become project goal" not in goals_text


def test_orchestrate_blocks_when_enforce_baseline_enabled(tmp_path: Path) -> None:
    run_id = "20260214T230000+0000"
    _write_evidence(
        tmp_path,
        run_id,
        [
            {
                "timestamp": "2026-02-14T23:00:00+00:00",
                "run_id": run_id,
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 1,
                "success": False,
                "classification": "failed-impl",
                "failure_classification": "impl-defect",
                "action_taken": "retry",
            },
            {
                "timestamp": "2026-02-14T23:01:00+00:00",
                "run_id": run_id,
                "goal_id": "G1",
                "phase": "implement",
                "attempt": 2,
                "success": False,
                "classification": "no-progress",
                "failure_classification": "impl-defect",
                "action_taken": "block",
            },
        ],
    )
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "feedback_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v1
            enabled: true
            promotion:
              min_frequency: 1
              min_confidence: 0.5
              auto_promote_impact: high
            dedup:
              strategy: fingerprint_v1
            publish:
              enabled: false
              backend: codeberg
              repository: ""
              token_env: CODEBERG_TOKEN
              base_url: https://codeberg.org
              labels: [bot-reported, hast-feedback]
              min_status: accepted
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")

    with pytest.raises(DevfError, match="observability baseline not ready"):
        orchestrate_productivity_cycle(
            tmp_path,
            run_id=run_id,
            window_days=30,
            max_goals=3,
            publish=False,
            publish_dry_run=False,
            enforce_baseline=True,
        )
