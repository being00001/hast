"""Tests for merge-train and risk-threshold controls."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

from devf.core.auto import run_auto
from devf.core.goals import find_goal, load_goals
from devf.core.runner import GoalRunner, RunnerResult


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(root: Path, config_yaml: str, risk_policy_yaml: str) -> None:
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "config.yaml").write_text(textwrap.dedent(config_yaml), encoding="utf-8")
    (root / ".ai" / "rules.md").write_text("# rules\n", encoding="utf-8")
    (root / ".ai" / "goals.yaml").write_text(
        textwrap.dedent(
            """\
            goals:
              - id: G1
                title: Risk merge
                status: active
            """
        ),
        encoding="utf-8",
    )
    (root / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "policies" / "risk_policy.yaml").write_text(
        textwrap.dedent(risk_policy_yaml),
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def _read_evidence(root: Path) -> list[dict]:
    evidence_files = sorted((root / ".ai" / "runs").glob("*/evidence.jsonl"))
    assert evidence_files
    lines = [line for line in evidence_files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


class _WriteRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        (root / "src" / "feature.py").write_text("value = 1\n", encoding="utf-8")
        return RunnerResult(success=True, output="ok")


def test_risk_block_before_merge(tmp_path: Path) -> None:
    _init_repo(
        tmp_path,
        """
        test_command: "true"
        ai_tool: "echo {prompt}"
        merge_train:
          pre_merge_command: "true"
        """,
        """
        version: v1
        max_score: 100
        success_base_score: 15
        block_threshold: 30
        rollback_threshold: 20
        phase_weights:
          merge: 25
        """,
    )
    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_WriteRunner(),
    )
    assert code == 1
    assert not (tmp_path / "src" / "feature.py").exists()
    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "blocked"
    rows = _read_evidence(tmp_path)
    assert any(r.get("classification") == "risk-blocked" for r in rows)


def test_post_merge_auto_rollback(tmp_path: Path) -> None:
    _init_repo(
        tmp_path,
        """
        test_command: "true"
        ai_tool: "echo {prompt}"
        merge_train:
          pre_merge_command: "true"
          post_merge_command: "false"
          auto_rollback: true
        """,
        """
        version: v1
        max_score: 100
        success_base_score: 15
        block_threshold: 99
        rollback_threshold: 20
        phase_weights:
          merge: 25
        """,
    )
    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_WriteRunner(),
    )
    assert code == 1
    assert not (tmp_path / "src" / "feature.py").exists()
    goals = load_goals(tmp_path / ".ai" / "goals.yaml")
    g = find_goal(goals, "G1")
    assert g is not None
    assert g.status == "blocked"
    rows = _read_evidence(tmp_path)
    assert any(r.get("phase") == "rollback" and r.get("action_taken") == "rollback" for r in rows)


def test_contract_docs_security_updates_required(tmp_path: Path) -> None:
    _init_repo(
        tmp_path,
        """
        test_command: "true"
        ai_tool: "echo {prompt}"
        merge_train:
          pre_merge_command: "true"
        """,
        """
        version: v1
        max_score: 100
        success_base_score: 10
        block_threshold: 99
        rollback_threshold: 80
        """,
    )
    (tmp_path / ".ai" / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "contracts" / "login.contract.yaml").write_text(
        textwrap.dedent(
            """\
            required_changes:
              - "src/*.py"
            required_docs:
              - "README.md"
            required_security_docs:
              - "SECURITY.md"
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai" / "goals.yaml").write_text(
        textwrap.dedent(
            """\
            goals:
              - id: G1
                title: Risk merge
                status: active
                contract_file: ".ai/contracts/login.contract.yaml"
            """
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add docs policy contract")

    code = run_auto(
        root=tmp_path,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_WriteRunner(),
    )
    assert code == 1
    rows = _read_evidence(tmp_path)
    assert any(r.get("classification") == "contract-violation" for r in rows)
