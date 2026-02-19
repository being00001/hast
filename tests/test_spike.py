"""Tests for decision spike runner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml

from hast.core.decision import create_decision_ticket, save_decision_ticket
from hast.core.spike import run_decision_spikes


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=True,
    )


def _init_repo(root: Path) -> None:
    (root / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def _write_decision(root: Path) -> Path:
    ticket = create_decision_ticket(
        goal_id="G_SPIKE",
        question="Choose approach",
        alternatives=["A", "B"],
        decision_id="D_SPIKE",
    )
    path = root / ".ai" / "decisions" / "D_SPIKE.yaml"
    save_decision_ticket(path, ticket)
    return path


def test_run_decision_spikes_writes_artifacts_and_evidence(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    decision_path = _write_decision(tmp_path)

    result = run_decision_spikes(
        root=tmp_path,
        decision_file=decision_path,
        parallel=2,
        command_template="echo spike-{alternative_id}",
        backend="thread",
        actor="tester",
        log_evidence=True,
    )

    assert result.decision_id == "D_SPIKE"
    assert result.goal_id == "G_SPIKE"
    assert result.summary_path.exists()
    assert len(result.alternatives) == 2
    assert result.winner_id == "A"
    assert result.winner_reason == "why:alternative_id"
    assert result.winner_reason_code == "alternative_id"
    assert "deterministic tie-break on alternative_id" in result.winner_reason_detail
    assert result.winner_vs_runner_up is not None
    assert result.escalated is False
    assert sorted(row.comparison_rank for row in result.alternatives) == [1, 2]

    for row in result.alternatives:
        assert (tmp_path / row.output_file).exists()
        assert (tmp_path / row.metadata_file).exists()
        assert row.changed_files == 0
        assert row.added_lines == 0
        assert row.deleted_lines == 0
        assert row.diff_lines == 0

    evidence = tmp_path / ".ai" / "decisions" / "evidence.jsonl"
    assert evidence.exists()
    spike_rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert any(row.get("event_type") == "decision_spike" for row in spike_rows)
    latest_spike = next(row for row in reversed(spike_rows) if row.get("event_type") == "decision_spike")
    assert all("comparison_rank" in item for item in list(latest_spike.get("ranking") or []))
    assert "winner_reason" in latest_spike
    assert latest_spike["winner_reason"] == "why:alternative_id"
    assert latest_spike["winner_reason_code"] == "alternative_id"
    assert "winner_vs_runner_up" in latest_spike

    loaded = yaml.safe_load(decision_path.read_text(encoding="utf-8"))["decision"]
    refs = list(loaded.get("evidence_refs") or [])
    assert any("summary.json" in ref for ref in refs)


def test_run_decision_spikes_escalates_on_failures(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    decision_path = _write_decision(tmp_path)

    result = run_decision_spikes(
        root=tmp_path,
        decision_file=decision_path,
        parallel=2,
        command_template="false",
        backend="thread",
        actor="tester",
        log_evidence=False,
    )

    assert result.winner_id is None
    assert result.winner_reason == "why:no_passing"
    assert result.winner_reason_code == "no_passing"
    assert result.winner_reason_detail == "No passing alternatives; escalation required."
    assert result.winner_vs_runner_up is None
    assert result.escalated is True
    assert all(row.passed is False for row in result.alternatives)


def test_run_decision_spikes_prefers_lower_diff_lines(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    decision_path = _write_decision(tmp_path)

    result = run_decision_spikes(
        root=tmp_path,
        decision_file=decision_path,
        parallel=2,
        command_template=(
            "sh -lc \"if [ '{alternative_id}' = 'A' ]; then "
            "printf 'a\\nb\\n' >> src/main.py; "
            "else printf 'c\\n' >> src/main.py; fi\""
        ),
        backend="thread",
        actor="tester",
        log_evidence=False,
    )

    assert result.escalated is False
    assert result.winner_id == "B"
    assert result.winner_reason == "why:diff_lines"
    assert result.winner_reason_code == "diff_lines"
    assert "fewer diff_lines" in result.winner_reason_detail
    by_id = {row.alternative_id: row for row in result.alternatives}
    assert by_id["A"].diff_lines > by_id["B"].diff_lines
    assert by_id["A"].comparison_rank > by_id["B"].comparison_rank


def test_run_decision_spikes_uses_deterministic_tiebreaker_by_default(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    decision_path = _write_decision(tmp_path)

    result = run_decision_spikes(
        root=tmp_path,
        decision_file=decision_path,
        parallel=2,
        command_template=(
            "sh -lc \"if [ '{alternative_id}' = 'A' ]; then sleep 0.05; fi; echo spike-{alternative_id}\""
        ),
        backend="thread",
        actor="tester",
        log_evidence=False,
    )

    assert result.escalated is False
    assert result.winner_id == "A"
    assert result.winner_reason == "why:alternative_id"
    assert result.winner_reason_code == "alternative_id"
    by_id = {row.alternative_id: row for row in result.alternatives}
    assert by_id["A"].diff_lines == by_id["B"].diff_lines == 0
    assert by_id["A"].changed_files == by_id["B"].changed_files == 0


def test_run_decision_spikes_can_enable_duration_tiebreaker(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    policy_path = tmp_path / ".ai" / "policies" / "spike_policy.yaml"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        """
version: v1
prefer_lower_diff_lines: true
prefer_lower_changed_files: true
include_duration_tiebreaker: true
""",
        encoding="utf-8",
    )
    decision_path = _write_decision(tmp_path)

    result = run_decision_spikes(
        root=tmp_path,
        decision_file=decision_path,
        parallel=2,
        command_template=(
            "sh -lc \"if [ '{alternative_id}' = 'A' ]; then sleep 0.05; fi; echo spike-{alternative_id}\""
        ),
        backend="thread",
        actor="tester",
        log_evidence=False,
    )

    assert result.escalated is False
    assert result.winner_id == "B"
    assert result.winner_reason == "why:duration_ms"
    assert result.winner_reason_code == "duration_ms"
    assert "lower duration_ms" in result.winner_reason_detail
