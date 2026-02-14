"""BDD tests for evidence logging in auto loop."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from devf.core.auto import run_auto
from devf.core.goals import find_goal, load_goals
from devf.core.runner import GoalRunner, RunnerResult


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_project(root: Path, test_command: str = "true") -> None:
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "config.yaml").write_text(
        f'test_command: "{test_command}"\nai_tool: "echo {{prompt}}"\n',
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text(
        "goals:\n  - id: G1\n    title: Evidence goal\n    status: active\n",
        encoding="utf-8",
    )
    (root / ".ai" / "rules.md").write_text("# rules\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def _read_evidence_lines(root: Path) -> list[dict]:
    runs_dir = root / ".ai" / "runs"
    files = sorted(runs_dir.glob("*/evidence.jsonl"))
    assert files, "expected evidence file under .ai/runs/*/evidence.jsonl"
    lines = [line for line in files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


class _SuccessRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        (root / "src" / "feature.py").write_text("value = 1\n", encoding="utf-8")
        return RunnerResult(success=True, output="ok")


class _FailRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        (root / "src" / "feature.py").write_text("value = 1\n", encoding="utf-8")
        return RunnerResult(success=True, output="ok")


def test_auto_writes_evidence_on_success(tmp_path: Path) -> None:
    _init_project(tmp_path, test_command="true")
    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_SuccessRunner(),
    )
    assert code == 0

    rows = _read_evidence_lines(tmp_path)
    assert rows
    assert any(r["goal_id"] == "G1" for r in rows)
    assert any(r["classification"] == "complete" for r in rows)
    assert any(r["classification"] == "merged" for r in rows)
    assert all("run_id" in r for r in rows)
    assert all("timestamp" in r for r in rows)
    assert all("state_from" in r for r in rows)
    assert all("state_to" in r for r in rows)
    assert all("policy_version" in r for r in rows)
    assert all("action_taken" in r for r in rows)
    assert all("risk_score" in r for r in rows)
    assert any(r["action_taken"] == "advance" for r in rows)

    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.state == "merged"


def test_auto_writes_evidence_on_failure(tmp_path: Path) -> None:
    _init_project(tmp_path, test_command="false")
    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_FailRunner(),
    )
    assert code == 1

    rows = _read_evidence_lines(tmp_path)
    assert rows
    assert any(r["goal_id"] == "G1" for r in rows)
    assert any(r["success"] is False for r in rows)
    assert any("failed" in r["classification"] for r in rows)
    assert all(r["state_to"] is None for r in rows)
    assert all("failure_classification" in r for r in rows)
    assert any(r["action_taken"] in {"retry", "escalate", "block"} for r in rows)


def test_gate_evidence_includes_per_check_outcomes(tmp_path: Path) -> None:
    _init_project(tmp_path, test_command="true")
    (tmp_path / ".ai" / "goals.yaml").write_text(
        "goals:\n  - id: G1\n    title: Gate goal\n    status: active\n    phase: gate\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "set gate phase")

    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
    )
    assert code == 0

    rows = _read_evidence_lines(tmp_path)
    gate_rows = [row for row in rows if row.get("phase") == "gate"]
    assert gate_rows
    gate_row = gate_rows[-1]
    assert isinstance(gate_row.get("gate_checks"), list)
    assert any(check.get("name") == "pytest" for check in gate_row["gate_checks"])
    assert isinstance(gate_row.get("gate_failed_checks"), list)
