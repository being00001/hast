"""CLI tests for proposal inbox commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from devf.cli import main


def test_propose_note_command_and_list(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    note = runner.invoke(
        main,
        [
            "propose",
            "note",
            "--category",
            "risk",
            "--impact",
            "high",
            "--risk",
            "high",
            "--title",
            "Retry storm on gate failures",
            "--why-now",
            "Repeated failures across latest run",
            "--evidence-ref",
            ".ai/runs/RUN1/evidence.jsonl#L3",
            "--affects-goal",
            "G1",
        ],
    )
    assert note.exit_code == 0
    assert "Proposal recorded:" in note.output
    assert (tmp_path / ".ai" / "proposals" / "notes.jsonl").exists()

    listed = runner.invoke(
        main,
        [
            "propose",
            "list",
            "--window",
            "30",
            "--limit",
            "5",
        ],
    )
    assert listed.exit_code == 0
    assert "Proposals loaded: 1" in listed.output


def test_propose_note_rejects_malformed_payload(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "propose",
            "note",
            "--category",
            "risk",
            "--impact",
            "high",
            "--risk",
            "high",
            "--title",
            "Missing why-now should fail",
        ],
    )
    assert result.exit_code != 0
    assert "Missing option '--why-now'" in result.output


def test_propose_note_does_not_modify_goals_yaml(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    goals = tmp_path / ".ai" / "goals.yaml"
    original = "goals:\n  - id: G1\n    title: Keep unchanged\n    status: active\n"
    goals.write_text(original, encoding="utf-8")
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "propose",
            "note",
            "--category",
            "workflow_friction",
            "--impact",
            "medium",
            "--risk",
            "low",
            "--title",
            "Better command hints",
            "--why-now",
            "Workers repeatedly misuse parameters",
        ],
    )
    assert result.exit_code == 0
    assert goals.read_text(encoding="utf-8") == original


def test_propose_promote_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    args = [
        "propose",
        "note",
        "--category",
        "workflow_friction",
        "--impact",
        "medium",
        "--risk",
        "medium",
        "--title",
        "Retry churn",
        "--why-now",
        "Repeated retries across sessions",
    ]
    assert runner.invoke(main, args).exit_code == 0
    assert runner.invoke(main, args).exit_code == 0

    result = runner.invoke(
        main,
        [
            "propose",
            "promote",
            "--window",
            "30",
            "--max-active",
            "5",
        ],
    )
    assert result.exit_code == 0
    assert "Accepted: 1" in result.output
    assert "Goals added: 1" in result.output

    goals_text = (tmp_path / ".ai" / "goals.yaml").read_text(encoding="utf-8")
    assert "id: PX_2X" in goals_text
