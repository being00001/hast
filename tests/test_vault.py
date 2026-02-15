"""Tests for `.knowledge` vault sync."""

from __future__ import annotations

import json
from pathlib import Path

from devf.core.vault import sync_vault


def _seed_vault_sources(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G_AUTH
    title: "Auth"
    status: active
    decision_file: .ai/decisions/D_AUTH.yaml
    contract_file: .ai/contracts/auth.contract.yaml
""",
        encoding="utf-8",
    )

    decisions_dir = root / ".ai" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "D_AUTH.yaml").write_text(
        """
decision:
  version: 1
  decision_id: D_AUTH
  goal_id: G_AUTH
  question: "Which auth mode?"
  status: accepted
  owner: architect
  alternatives:
    - id: A
    - id: B
  validation_matrix:
    - criterion: c
      weight: 100
      min_score: 0
  scores:
    A: { c: 1 }
    B: { c: 0 }
  selected_alternative: A
""",
        encoding="utf-8",
    )

    contracts_dir = root / ".ai" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "auth.contract.yaml").write_text("version: 1\n", encoding="utf-8")

    run_dir = root / ".ai" / "runs" / "R_1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-02-15T00:00:00+00:00",
                "goal_id": "G_AUTH",
                "classification": "complete",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_sync_vault_generates_pages_and_links(tmp_path: Path) -> None:
    _seed_vault_sources(tmp_path)

    result = sync_vault(tmp_path)

    assert result.output_dir == Path(".knowledge")
    assert (tmp_path / ".knowledge" / "Goal" / "G_AUTH.md").exists()
    assert (tmp_path / ".knowledge" / "Decision" / "D_AUTH.md").exists()
    assert (tmp_path / ".knowledge" / "Run" / "R_1.md").exists()
    assert (tmp_path / ".knowledge" / "Contract" / "C_auth_contract.md").exists()

    goal_note = (tmp_path / ".knowledge" / "Goal" / "G_AUTH.md").read_text(encoding="utf-8")
    assert "[[Decision/D_AUTH]]" in goal_note
    assert "[[Contract/C_auth_contract]]" in goal_note
    assert "[[Run/R_1]]" in goal_note

    assert result.broken_links == []
    assert result.orphan_notes == []


def test_sync_vault_detects_broken_links_and_orphans(tmp_path: Path) -> None:
    _seed_vault_sources(tmp_path)
    vault_dir = tmp_path / ".knowledge"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "custom.md").write_text("# custom\n\n[[Goal/NOPE]]\n", encoding="utf-8")

    result = sync_vault(tmp_path, check_links=True)

    assert any("custom.md -> Goal/NOPE" in item for item in result.broken_links)
    assert Path("custom.md") in result.orphan_notes
