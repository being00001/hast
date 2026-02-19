"""CLI tests for execution queue commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main


def _seed_project(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
  - id: G2
    title: Goal 2
    status: active
""",
        encoding="utf-8",
    )


def _seed_project_roles(root: Path) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    phase: implement
  - id: G2
    title: Goal 2
    status: active
    phase: adversarial
  - id: G3
    title: Goal 3
    status: active
    phase: gate
""",
        encoding="utf-8",
    )


def test_queue_claim_and_release_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    claim = runner.invoke(
        main,
        ["queue", "claim", "--worker", "worker-a", "--goal", "G1", "--json"],
    )
    assert claim.exit_code == 0
    claim_payload = json.loads(claim.output)
    assert claim_payload["goal_id"] == "G1"
    assert claim_payload["worker_id"] == "worker-a"

    release = runner.invoke(
        main,
        [
            "queue",
            "release",
            claim_payload["claim_id"],
            "--worker",
            "worker-a",
            "--goal-status",
            "done",
            "--json",
        ],
    )
    assert release.exit_code == 0
    release_payload = json.loads(release.output)
    assert release_payload["status"] == "released"
    assert release_payload["goal_status"] == "done"


def test_queue_idempotent_claim_reuse(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    first = runner.invoke(
        main,
        [
            "queue",
            "claim",
            "--worker",
            "worker-a",
            "--goal",
            "G1",
            "--idempotency-key",
            "req-1",
            "--json",
        ],
    )
    assert first.exit_code == 0
    p1 = json.loads(first.output)

    second = runner.invoke(
        main,
        [
            "queue",
            "claim",
            "--worker",
            "worker-a",
            "--idempotency-key",
            "req-1",
            "--json",
        ],
    )
    assert second.exit_code == 0
    p2 = json.loads(second.output)
    assert p2["created"] is False
    assert p2["idempotent_reused"] is True
    assert p1["claim_id"] == p2["claim_id"]


def test_queue_list_and_sweep_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    runner.invoke(
        main,
        [
            "queue",
            "claim",
            "--worker",
            "worker-a",
            "--goal",
            "G1",
            "--ttl-minutes",
            "1",
            "--json",
        ],
    )

    listed = runner.invoke(main, ["queue", "list", "--active-only", "--json"])
    assert listed.exit_code == 0
    list_payload = json.loads(listed.output)
    assert list_payload["snapshot"]["active_claims"] == 1

    swept = runner.invoke(main, ["queue", "sweep", "--json"])
    assert swept.exit_code == 0
    sweep_payload = json.loads(swept.output)
    assert "expired_claims" in sweep_payload


def test_queue_claim_with_role_filter(monkeypatch, tmp_path: Path) -> None:
    _seed_project_roles(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    runner = CliRunner()

    claim = runner.invoke(
        main,
        [
            "queue",
            "claim",
            "--worker",
            "worker-test",
            "--role",
            "test",
            "--json",
        ],
    )
    assert claim.exit_code == 0
    payload = json.loads(claim.output)
    assert payload["goal_id"] == "G2"
    assert payload["role"] == "test"
