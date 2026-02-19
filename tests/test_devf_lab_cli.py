"""Tests for hast-lab CLI."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast_lab.cli import main


def test_lab_new_scaffolds_project(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["new", "demo-lab", "--dir", tmp_path.as_posix(), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    project_root = Path(payload["project_root"])
    assert (project_root / ".ai" / "config.yaml").exists()
    assert (project_root / ".ai" / "goals.yaml").exists()
    assert (project_root / ".lab" / "project.yaml").exists()
    assert (project_root / "tests" / "test_app.py").exists()


def test_lab_run_protocol_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()
    created = runner.invoke(
        main,
        ["new", "demo-run", "--dir", tmp_path.as_posix(), "--json"],
    )
    assert created.exit_code == 0
    project_root = Path(json.loads(created.output)["project_root"])

    run_result = runner.invoke(
        main,
        [
            "run",
            "protocol-roundtrip",
            "--project",
            project_root.as_posix(),
            "--json",
        ],
    )
    assert run_result.exit_code == 0
    payload = json.loads(run_result.output)
    assert payload["scenario"] == "protocol-roundtrip"
    assert payload["success"] is True
    assert payload["worker_processed"] is True
    assert Path(payload["run_record"]).exists()


def test_lab_run_no_progress_returns_failure_json(tmp_path: Path) -> None:
    runner = CliRunner()
    created = runner.invoke(
        main,
        ["new", "demo-np", "--dir", tmp_path.as_posix(), "--json"],
    )
    assert created.exit_code == 0
    project_root = Path(json.loads(created.output)["project_root"])

    run_result = runner.invoke(
        main,
        [
            "run",
            "no-progress",
            "--project",
            project_root.as_posix(),
            "--json",
        ],
    )
    assert run_result.exit_code == 1
    payload = json.loads(run_result.output)
    assert payload["scenario"] == "no-progress"
    assert payload["success"] is False
    assert payload["classification"] == "no-progress"
    assert "run_record" in payload
    assert Path(payload["run_record"]).exists()


def test_lab_report_aggregates_records(tmp_path: Path) -> None:
    project_root = tmp_path / "demo-report"
    runs_dir = project_root / ".lab" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "run_1.json").write_text(
        json.dumps({"scenario": "protocol-roundtrip", "success": True}),
        encoding="utf-8",
    )
    (runs_dir / "run_2.json").write_text(
        json.dumps({"scenario": "protocol-roundtrip", "success": False}),
        encoding="utf-8",
    )
    (runs_dir / "run_3.json").write_text(
        json.dumps({"scenario": "other", "success": True}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["report", "--project", project_root.as_posix(), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_runs"] == 3
    assert payload["success_runs"] == 2
    assert payload["failed_runs"] == 1
    assert payload["by_scenario"]["protocol-roundtrip"] == 2


def test_lab_report_counts_no_progress_scenario(tmp_path: Path) -> None:
    runner = CliRunner()
    created = runner.invoke(
        main,
        ["new", "demo-mixed", "--dir", tmp_path.as_posix(), "--json"],
    )
    assert created.exit_code == 0
    project_root = Path(json.loads(created.output)["project_root"])

    run1 = runner.invoke(
        main,
        ["run", "protocol-roundtrip", "--project", project_root.as_posix(), "--json"],
    )
    assert run1.exit_code == 0
    run2 = runner.invoke(
        main,
        ["run", "no-progress", "--project", project_root.as_posix(), "--json"],
    )
    assert run2.exit_code == 1

    report = runner.invoke(main, ["report", "--project", project_root.as_posix(), "--json"])
    assert report.exit_code == 0
    payload = json.loads(report.output)
    assert payload["total_runs"] == 2
    assert payload["by_scenario"]["protocol-roundtrip"] == 1
    assert payload["by_scenario"]["no-progress"] == 1
