"""Tests for predictive simulation module."""

from __future__ import annotations

from pathlib import Path

from hast.core.doctor import DoctorCheck, DoctorReport
from hast.core.sim import run_simulation


def _doctor_ok(root: Path) -> DoctorReport:
    return DoctorReport(
        root=root.as_posix(),
        checks=[DoctorCheck(code="preflight", status="pass", message="ok")],
        pass_count=1,
        warn_count=0,
        fail_count=0,
        ok=True,
    )


def test_simulation_ready_with_active_goal(tmp_project: Path, monkeypatch) -> None:
    (tmp_project / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    allowed_changes:
      - src/app.py
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("hast.core.sim.run_doctor", lambda _root: _doctor_ok(tmp_project))
    monkeypatch.setattr("hast.core.sim.auto_preflight_blockers", lambda _report: [])

    report = run_simulation(tmp_project, goal_id=None, run_tests=False)
    assert report.goal_id == "G1"
    assert report.status == "risky"
    # risky because test probe is intentionally skipped in default mode
    assert any(check.code == "test_probe" and check.status == "warn" for check in report.checks)


def test_simulation_blocks_when_no_active_goal(tmp_project: Path, monkeypatch) -> None:
    (tmp_project / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    monkeypatch.setattr("hast.core.sim.run_doctor", lambda _root: _doctor_ok(tmp_project))
    monkeypatch.setattr("hast.core.sim.auto_preflight_blockers", lambda _report: [])

    report = run_simulation(tmp_project, goal_id=None, run_tests=False)
    assert report.status == "blocked"
    assert any(check.code == "goal_selection" and check.status == "fail" for check in report.checks)


def test_simulation_warns_on_repeated_no_progress(tmp_project: Path, monkeypatch) -> None:
    (tmp_project / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    allowed_changes:
      - src/app.py
""",
        encoding="utf-8",
    )
    attempts_dir = tmp_project / ".ai" / "attempts" / "G1"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    for idx in (1, 2, 3):
        (attempts_dir / f"attempt_{idx}.yaml").write_text(
            f"attempt: {idx}\nclassification: no-progress\nreason: no file changes\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("hast.core.sim.run_doctor", lambda _root: _doctor_ok(tmp_project))
    monkeypatch.setattr("hast.core.sim.auto_preflight_blockers", lambda _report: [])

    report = run_simulation(tmp_project, goal_id="G1", run_tests=False)
    assert report.status == "risky"
    assert any(check.code == "recent_attempts" and check.status == "warn" for check in report.checks)
    assert any("hast explore" in action for action in report.recommended_actions)


def test_simulation_blocks_high_uncertainty_without_decision(tmp_project: Path, monkeypatch) -> None:
    (tmp_project / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G1
    title: Goal 1
    status: active
    uncertainty: high
    allowed_changes:
      - src/app.py
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("hast.core.sim.run_doctor", lambda _root: _doctor_ok(tmp_project))
    monkeypatch.setattr("hast.core.sim.auto_preflight_blockers", lambda _report: [])

    report = run_simulation(tmp_project, goal_id="G1", run_tests=False)
    assert report.status == "blocked"
    assert any(check.code == "decision_prereq" and check.status == "fail" for check in report.checks)
