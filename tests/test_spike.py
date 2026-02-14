"""Tests for decision spike runner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml

from devf.core.decision import create_decision_ticket, save_decision_ticket
from devf.core.spike import run_decision_spikes


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
    assert result.escalated is False

    for row in result.alternatives:
        assert (tmp_path / row.output_file).exists()
        assert (tmp_path / row.metadata_file).exists()

    evidence = tmp_path / ".ai" / "decisions" / "evidence.jsonl"
    assert evidence.exists()
    spike_rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert any(row.get("event_type") == "decision_spike" for row in spike_rows)

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
    assert result.escalated is True
    assert all(row.passed is False for row in result.alternatives)
