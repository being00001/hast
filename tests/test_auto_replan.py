"""Integration tests for auto loop post-goal replan invalidation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

from hast.core.auto import run_auto
from hast.core.goals import find_goal, load_goals
from hast.core.runner import GoalRunner, RunnerResult


class _SuccessRunner(GoalRunner):
    def run(self, root, config, goal, prompt, tool_name=None):  # type: ignore[no-untyped-def]
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "src" / "feature.py").write_text("value = 1\n", encoding="utf-8")
        return RunnerResult(success=True, output="ok")


def _read_latest_evidence_rows(root: Path) -> list[dict]:
    runs_dir = root / ".ai" / "runs"
    files = sorted(runs_dir.glob("*/evidence.jsonl"))
    assert files, "expected evidence file under .ai/runs/*/evidence.jsonl"
    lines = [line for line in files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_run_auto_applies_post_goal_replan_and_logs_evidence(tmp_project: Path) -> None:
    goals_path = tmp_project / ".ai" / "goals.yaml"
    goals_path.write_text(
        textwrap.dedent(
            """\
            goals:
              - id: G1
                title: Complete first
                status: active
                obsoletes: [G2]
              - id: G2
                title: Becomes obsolete
                status: pending
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add replan goals"],
        cwd=str(tmp_project),
        capture_output=True,
        check=True,
    )

    code = run_auto(
        root=tmp_project,
        goal_id="G1",
        recursive=False,
        dry_run=False,
        explain=False,
        tool_name=None,
        runner=_SuccessRunner(),
    )
    assert code.exit_code == 0

    goals = load_goals(goals_path)
    g1 = find_goal(goals, "G1")
    g2 = find_goal(goals, "G2")
    assert g1 is not None
    assert g1.status == "done"
    assert g2 is not None
    assert g2.status == "obsolete"

    rows = _read_latest_evidence_rows(tmp_project)
    invalidation_rows = [
        row for row in rows
        if row.get("phase") == "replan" and row.get("classification") == "goal-invalidated"
    ]
    assert invalidation_rows
    row = invalidation_rows[-1]
    assert row["goal_id"] == "G2"
    assert row["invalidation_to_status"] == "obsolete"
    assert row["invalidation_reason_code"] == "explicit_obsoleted_by_completed_goal"
    assert row["invalidated_by_goal"] == "G1"
