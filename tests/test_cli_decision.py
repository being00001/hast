"""CLI tests for decision workflow commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from click.testing import CliRunner
import yaml

from hast.cli import main


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=True,
    )


def _init_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def test_decision_new_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "new",
            "G_LOGIN",
            "--question",
            "Which login strategy should we choose?",
            "--alternatives",
            "A,B,C",
            "--decision-id",
            "D_LOGIN_FLOW",
        ],
    )
    assert result.exit_code == 0
    assert "Decision ticket created:" in result.output
    fp = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    assert fp.exists()


def test_decision_new_command_json(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "new",
            "G_LOGIN",
            "--question",
            "Which login strategy should we choose?",
            "--alternatives",
            "A,B,C",
            "--decision-id",
            "D_LOGIN_FLOW",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["decision_id"] == "D_LOGIN_FLOW"
    assert payload["goal_id"] == "G_LOGIN"


def test_decision_evaluate_accept_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 50
      min_score: 3
    - criterion: regression_risk
      weight: 50
      min_score: 3
  scores:
    A:
      contract_fit: 4
      regression_risk: 4
    B:
      contract_fit: 2
      regression_risk: 2
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "evaluate",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--accept",
            "--run-id",
            "20260214T230000+0000",
        ],
    )
    assert result.exit_code == 0
    assert "Winner: A" in result.output
    assert "Decision updated: status=accepted selected=A" in result.output

    data = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision = data["decision"]
    assert decision["status"] == "accepted"
    assert decision["selected_alternative"] == "A"

    evidence_path = tmp_path / ".ai" / "decisions" / "evidence.jsonl"
    assert evidence_path.exists()
    row = json.loads(evidence_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["decision_id"] == "D_LOGIN_FLOW"
    assert row["classification"] == "decision-accepted"
    assert row["run_id"] == "20260214T230000+0000"


def test_decision_evaluate_accept_command_json(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 4
    B:
      contract_fit: 2
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "evaluate",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--accept",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["winner_id"] == "A"
    assert payload["status"] == "accepted"


def test_decision_spike_command(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 0
    B:
      contract_fit: 0
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
        ],
    )
    assert result.exit_code == 0
    assert "Spike summary:" in result.output
    assert "(winner=A, escalated=False)" in result.output
    assert "Winner reason: why:alternative_id" in result.output
    assert "escalated=False" in result.output
    assert "A: PASS rank=" in result.output
    assert "B: PASS rank=" in result.output
    assert "rank=1" in result.output
    assert "rank=2" in result.output

    spikes_root = tmp_path / ".ai" / "decisions" / "spikes" / "D_LOGIN_FLOW"
    summaries = list(spikes_root.glob("*/summary.json"))
    assert summaries


def test_decision_spike_command_json(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 0
    B:
      contract_fit: 0
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["winner_id"] == "A"
    assert payload["winner_reason"] == "why:alternative_id"
    assert payload["winner_reason_code"] == "alternative_id"
    assert "deterministic tie-break on alternative_id" in payload["winner_reason_detail"]
    assert payload["winner_vs_runner_up"]["criterion"] == "alternative_id"
    assert len(payload["alternatives"]) == 2
    assert payload["alternatives"][0]["comparison_rank"] == 1
    assert payload["alternatives"][0]["diff_lines"] == 0
    assert payload["alternatives"][0]["changed_files"] == 0


def test_decision_spike_command_explain(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 0
    B:
      contract_fit: 0
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
            "--explain",
        ],
    )
    assert result.exit_code == 0
    assert "Winner reason: why:alternative_id" in result.output
    assert "Winner detail: Selected A: deterministic tie-break on alternative_id" in result.output
    assert "Winner compare: criterion=alternative_id winner=A runner_up=B" in result.output


def test_decision_spike_command_accept_if_passes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 4
    B:
      contract_fit: 3
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
            "--accept",
            "--accept-if-reason",
            "alternative_id",
            "--accept-max-diff-lines",
            "0",
            "--accept-max-changed-files",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "Decision updated: status=accepted selected=A" in result.output

    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))["decision"]
    assert decision["status"] == "accepted"
    assert decision["selected_alternative"] == "A"


def test_decision_spike_command_accept_if_blocks(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 4
    B:
      contract_fit: 3
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
            "--accept",
            "--accept-if-reason",
            "diff_lines",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["accepted"] is False
    assert payload["accept_if_guard_enabled"] is True
    assert payload["accept_if_guard_passed"] is False
    assert any("winner_reason_code=alternative_id" in row for row in payload["accept_if_guard_failures"])

    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))["decision"]
    assert decision["status"] == "proposed"
    assert decision.get("selected_alternative") is None


def test_decision_spike_command_accept_if_requires_accept(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".ai" / "decisions").mkdir(parents=True, exist_ok=True)
    _init_repo(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    decision_path = tmp_path / ".ai" / "decisions" / "D_LOGIN_FLOW.yaml"
    decision_path.write_text(
        """decision:
  version: 1
  decision_id: D_LOGIN_FLOW
  goal_id: G_LOGIN
  question: Which strategy?
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: contract_fit
      weight: 100
      min_score: 0
  scores:
    A:
      contract_fit: 0
    B:
      contract_fit: 0
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "decision",
            "spike",
            ".ai/decisions/D_LOGIN_FLOW.yaml",
            "--parallel",
            "2",
            "--command",
            "echo spike-{alternative_id}",
            "--backend",
            "thread",
            "--accept-if-reason",
            "alternative_id",
        ],
    )
    assert result.exit_code != 0
    assert "--accept-if-* options require --accept" in result.output
