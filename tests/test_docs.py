"""Tests for docs generation control plane."""

from __future__ import annotations

import json
import os
from pathlib import Path

from devf.core.docgen import generate_docs


def _write_goals(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G_AUTH
    title: Auth baseline
    status: active
    state: green_verified
    contract_file: .ai/contracts/auth.contract.yaml
    test_files:
      - tests/test_auth.py
    decision_file: .ai/decisions/D_AUTH.yaml
    depends_on: []
""",
        encoding="utf-8",
    )


def _write_decision(root: Path) -> None:
    decisions_dir = root / ".ai" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "D_AUTH.yaml").write_text(
        """
decision:
  version: 1
  decision_id: D_AUTH
  goal_id: G_AUTH
  question: Which auth mode?
  status: accepted
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
      contract_fit: 5
    B:
      contract_fit: 1
  selected_alternative: A
""",
        encoding="utf-8",
    )
    (decisions_dir / "evidence.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-02-14T10:00:00+00:00",
                "decision_id": "D_AUTH",
                "classification": "decision-accepted",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_run_evidence(root: Path) -> None:
    run_dir = root / ".ai" / "runs" / "20260214T120000+0000"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-02-14T12:00:00+00:00",
                        "goal_id": "G_AUTH",
                        "attempt": 1,
                        "classification": "complete",
                        "success": True,
                        "action_taken": "advance",
                        "risk_score": 25,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-02-14T12:01:00+00:00",
                        "goal_id": "G_AUTH",
                        "phase": "gate",
                        "attempt": 2,
                        "classification": "failed-gate",
                        "success": False,
                        "action_taken": "block",
                        "failure_classification": "security",
                        "risk_score": 90,
                        "gate_checks": [
                            {"name": "pytest", "status": "PASS"},
                            {"name": "gitleaks", "status": "FAIL"},
                        ],
                        "gate_failed_checks": ["gitleaks"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_generate_docs_writes_baseline_artifacts(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "app.py").write_text(
        "def login(user: str) -> bool:\n    return bool(user)\n",
        encoding="utf-8",
    )
    _write_goals(tmp_path)
    _write_decision(tmp_path)
    _write_run_evidence(tmp_path)

    result = generate_docs(tmp_path, window_days=30)

    assert len(result.generated_paths) == 4
    codemap = tmp_path / "docs" / "generated" / "codemap.md"
    traceability = tmp_path / "docs" / "generated" / "goal_traceability.md"
    decision_summary = tmp_path / "docs" / "generated" / "decision_summary.md"
    quality_report = tmp_path / "docs" / "generated" / "quality_security_report.md"
    assert codemap.exists()
    assert traceability.exists()
    assert decision_summary.exists()
    assert quality_report.exists()
    assert "src/app.py" in codemap.read_text(encoding="utf-8")
    assert "G_AUTH" in traceability.read_text(encoding="utf-8")
    assert "D_AUTH" in decision_summary.read_text(encoding="utf-8")
    assert "gitleaks" in quality_report.read_text(encoding="utf-8")


def test_generate_docs_detects_stale_generated_docs(tmp_path: Path) -> None:
    _write_goals(tmp_path)
    generated_dir = tmp_path / "docs" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stale_file = generated_dir / "codemap.md"
    stale_file.write_text("old\n", encoding="utf-8")

    stale_ts = 1_700_000_000
    fresh_ts = stale_ts + 1_000

    os.utime(stale_file, (stale_ts, stale_ts))
    os.utime(tmp_path / ".ai" / "goals.yaml", (fresh_ts, fresh_ts))

    result = generate_docs(tmp_path, window_days=30)
    stale_paths = {path.as_posix() for path in result.stale_paths}
    assert "docs/generated/codemap.md" in stale_paths


def test_generate_docs_skips_invalid_decision_yaml(tmp_path: Path) -> None:
    _write_goals(tmp_path)
    decisions_dir = tmp_path / ".ai" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "D_BROKEN.yaml").write_text("decision: [\n", encoding="utf-8")
    (decisions_dir / "D_OK.yaml").write_text(
        """
decision:
  version: 1
  decision_id: D_OK
  goal_id: G_AUTH
  question: q
  status: proposed
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: c
      weight: 100
      min_score: 0
  scores:
    A:
      c: 1
    B:
      c: 0
""",
        encoding="utf-8",
    )

    result = generate_docs(tmp_path, window_days=30)
    assert len(result.generated_paths) == 4
    summary = (tmp_path / "docs" / "generated" / "decision_summary.md").read_text(encoding="utf-8")
    assert "D_OK" in summary
    assert "D_BROKEN.yaml" in summary
