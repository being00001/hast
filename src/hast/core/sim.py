"""Predictive preflight simulation before running auto."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import subprocess

import yaml

from hast.core.config import load_config
from hast.core.decision import load_decision_ticket
from hast.core.doctor import (
    DoctorCheck,
    auto_preflight_blockers,
    run_doctor,
)
from hast.core.errors import HastError
from hast.core.goals import Goal, find_goal, load_goals, select_active_goal


@dataclass(frozen=True)
class SimCheck:
    code: str
    status: str  # pass | warn | fail
    message: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SimAttemptSnapshot:
    attempt: int
    classification: str
    reason: str | None


@dataclass(frozen=True)
class SimTestProbe:
    ran: bool
    passed: bool | None
    exit_code: int | None
    command: str | None
    summary: str | None


@dataclass(frozen=True)
class SimReport:
    root: str
    goal_id: str | None
    status: str  # ready | risky | blocked
    ready: bool
    risk_score: int
    checks: list[SimCheck]
    recommended_actions: list[str]
    recent_attempts: list[SimAttemptSnapshot]
    test_probe: SimTestProbe


def run_simulation(
    root: Path,
    *,
    goal_id: str | None,
    run_tests: bool = False,
) -> SimReport:
    checks: list[SimCheck] = []
    actions: list[str] = []
    recent_attempts: list[SimAttemptSnapshot] = []
    test_probe = SimTestProbe(
        ran=False,
        passed=None,
        exit_code=None,
        command=None,
        summary=None,
    )

    goals = load_goals(root / ".ai" / "goals.yaml")
    goal = _resolve_goal(goals, goal_id)
    if goal is None:
        checks.append(
            SimCheck(
                code="goal_selection",
                status="fail",
                message="no active goal selected",
                details=["pass an explicit goal_id or set one goal to status: active"],
            )
        )
        actions.append("set a goal to status: active or run `hast sim <goal_id>`")
    else:
        if goal.status != "active":
            checks.append(
                SimCheck(
                    code="goal_status",
                    status="fail",
                    message=f"goal is not active (status={goal.status})",
                    details=[f"goal_id={goal.id}"],
                )
            )
            actions.append(f"reactivate goal first: `hast retry {goal.id} --no-run`")
        else:
            checks.append(
                SimCheck(
                    code="goal_status",
                    status="pass",
                    message=f"goal is active ({goal.id})",
                )
            )

        if not goal.allowed_changes:
            checks.append(
                SimCheck(
                    code="allowed_scope",
                    status="warn",
                    message="goal has no allowed_changes (wide write scope)",
                    details=["define goal.allowed_changes for safer bounded edits"],
                )
            )
            actions.append("add `allowed_changes` to goal before running auto")
        else:
            checks.append(
                SimCheck(
                    code="allowed_scope",
                    status="pass",
                    message=f"allowed_changes configured ({len(goal.allowed_changes)})",
                )
            )

        decision_ok, decision_reason = _validate_decision_prerequisites(root, goal)
        if decision_ok:
            checks.append(
                SimCheck(
                    code="decision_prereq",
                    status="pass",
                    message="decision prerequisites satisfied",
                )
            )
        else:
            checks.append(
                SimCheck(
                    code="decision_prereq",
                    status="fail",
                    message=decision_reason or "decision prerequisites not satisfied",
                )
            )
            actions.append(f"create or accept decision ticket for {goal.id} before auto")

        recent_attempts, attempt_check, attempt_actions = _analyze_recent_attempts(root, goal.id)
        checks.append(attempt_check)
        actions.extend(attempt_actions)

    doctor_report = run_doctor(root)
    blockers = auto_preflight_blockers(doctor_report)
    if blockers:
        checks.append(
            SimCheck(
                code="preflight",
                status="fail",
                message=f"doctor preflight blockers={len(blockers)}",
                details=[f"{item.code}: {item.message}" for item in blockers[:10]],
            )
        )
        actions.append("run `hast doctor` and resolve blockers before `hast auto`")
    elif doctor_report.warn_count > 0:
        checks.append(
            SimCheck(
                code="preflight",
                status="warn",
                message=f"doctor warnings={doctor_report.warn_count}",
                details=["run `hast doctor` for full warning list"],
            )
        )
    else:
        checks.append(SimCheck(code="preflight", status="pass", message="doctor preflight clean"))

    config, _warnings = load_config(root / ".ai" / "config.yaml")
    if run_tests:
        test_probe, probe_check, probe_actions = _run_test_probe(root, config.test_command)
        checks.append(probe_check)
        actions.extend(probe_actions)
    else:
        checks.append(
            SimCheck(
                code="test_probe",
                status="warn",
                message="test probe skipped",
                details=["re-run with --run-tests to include baseline test health"],
            )
        )
        actions.append("optionally run `hast sim --run-tests` for baseline health check")

    actions = _dedupe_actions(actions)
    fail_count = sum(1 for check in checks if check.status == "fail")
    warn_count = sum(1 for check in checks if check.status == "warn")
    risk_score = _compute_risk_score(
        checks=checks,
        blockers=blockers,
        recent_attempts=recent_attempts,
        test_probe=test_probe,
    )
    status = _derive_status(fail_count=fail_count, warn_count=warn_count, risk_score=risk_score)

    goal_token = goal.id if goal is not None else goal_id
    if status == "ready" and goal_token:
        actions.append(f"safe to try: `hast auto {goal_token}`")
    if status == "blocked" and goal_token:
        actions.append(f"after fixes, rerun: `hast sim {goal_token}`")

    return SimReport(
        root=root.as_posix(),
        goal_id=goal_token,
        status=status,
        ready=status == "ready",
        risk_score=risk_score,
        checks=checks,
        recommended_actions=_dedupe_actions(actions),
        recent_attempts=recent_attempts,
        test_probe=test_probe,
    )


def report_to_dict(report: SimReport) -> dict[str, object]:
    return asdict(report)


def format_sim_report(report: SimReport) -> str:
    lines = [
        "hast sim",
        f"root: {report.root}",
        f"goal: {report.goal_id or '(none)'}",
        f"status: {report.status} (risk={report.risk_score})",
        "",
        "checks:",
    ]
    for check in report.checks:
        badge = {
            "pass": "[PASS]",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }.get(check.status, "[INFO]")
        lines.append(f"- {badge} {check.code}: {check.message}")
        for detail in check.details:
            lines.append(f"  * {detail}")

    lines.extend(["", "recommended actions:"])
    if report.recommended_actions:
        for item in report.recommended_actions:
            lines.append(f"- {item}")
    else:
        lines.append("- none")

    if report.recent_attempts:
        lines.extend(["", "recent attempts:"])
        for item in report.recent_attempts:
            reason = f" | {item.reason}" if item.reason else ""
            lines.append(f"- attempt={item.attempt} class={item.classification}{reason}")
    return "\n".join(lines)


def _resolve_goal(goals: list[Goal], goal_id: str | None) -> Goal | None:
    if goal_id:
        return find_goal(goals, goal_id)
    return select_active_goal(goals, None)


def _validate_decision_prerequisites(root: Path, goal: Goal) -> tuple[bool, str | None]:
    needs_decision = bool(goal.decision_file) or goal.uncertainty == "high"
    if not needs_decision:
        return True, None
    if not goal.decision_file:
        return False, "uncertainty=high requires decision_file"

    path = root / goal.decision_file
    try:
        ticket = load_decision_ticket(path)
    except HastError as exc:
        return False, str(exc)

    ticket_goal_id = str(ticket.get("goal_id") or "").strip()
    if ticket_goal_id and ticket_goal_id != goal.id:
        return False, f"decision ticket goal_id mismatch ({ticket_goal_id} != {goal.id})"

    status = str(ticket.get("status") or "").strip().lower()
    selected = str(ticket.get("selected_alternative") or "").strip()
    if status != "accepted" or not selected:
        return (
            False,
            (
                "decision ticket must be accepted with selected_alternative "
                f"(status={status or 'n/a'})"
            ),
        )
    return True, None


def _analyze_recent_attempts(
    root: Path, goal_id: str,
) -> tuple[list[SimAttemptSnapshot], SimCheck, list[str]]:
    attempts_dir = root / ".ai" / "attempts" / goal_id
    if not attempts_dir.exists():
        return (
            [],
            SimCheck(
                code="recent_attempts",
                status="pass",
                message="no recent attempt history for this goal",
            ),
            [],
        )

    snapshots: list[SimAttemptSnapshot] = []
    for path in sorted(attempts_dir.glob("attempt_*.yaml")):
        payload = _load_attempt_payload(path)
        if payload is None:
            continue
        snapshots.append(payload)
    snapshots = sorted(snapshots, key=lambda item: item.attempt)[-3:]
    if not snapshots:
        return (
            [],
            SimCheck(code="recent_attempts", status="pass", message="no parseable recent attempts"),
            [],
        )

    classes = [item.classification for item in snapshots]
    actions: list[str] = []
    if len(snapshots) >= 2 and all(cls == "no-progress" for cls in classes):
        actions.append('run `hast explore "<unclear point>"` before retry')
        actions.append("tighten goal scope/acceptance before rerun")
        return (
            snapshots,
            SimCheck(
                code="recent_attempts",
                status="warn",
                message=f"repeated no-progress pattern ({len(snapshots)} recent)",
                details=[f"classifications={', '.join(classes)}"],
            ),
            actions,
        )

    if any(cls in {"failed-env", "failed-impl", "failed"} for cls in classes):
        actions.append("review last attempt reasons before auto rerun")
        return (
            snapshots,
            SimCheck(
                code="recent_attempts",
                status="warn",
                message="recent failures detected",
                details=[f"classifications={', '.join(classes)}"],
            ),
            actions,
        )

    return (
        snapshots,
        SimCheck(
            code="recent_attempts",
            status="pass",
            message="recent attempt trend looks stable",
        ),
        [],
    )


def _load_attempt_payload(path: Path) -> SimAttemptSnapshot | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    attempt = raw.get("attempt")
    if not isinstance(attempt, int):
        name_match = re.search(r"attempt_(\d+)\.yaml$", path.name)
        attempt = int(name_match.group(1)) if name_match else 0
    classification = str(raw.get("classification") or "").strip()
    if not classification:
        return None
    reason_raw = raw.get("reason")
    reason = str(reason_raw).strip() if isinstance(reason_raw, str) and reason_raw.strip() else None
    return SimAttemptSnapshot(attempt=attempt, classification=classification, reason=reason)


def _run_test_probe(root: Path, command: str) -> tuple[SimTestProbe, SimCheck, list[str]]:
    proc = subprocess.run(
        command,
        cwd=str(root),
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    summary = (output.strip() or "no output")[-500:]
    probe = SimTestProbe(
        ran=True,
        passed=(proc.returncode == 0),
        exit_code=proc.returncode,
        command=command,
        summary=summary,
    )
    if proc.returncode == 0:
        return (
            probe,
            SimCheck(
                code="test_probe",
                status="pass",
                message="baseline test probe passed",
                details=[f"command={command}"],
            ),
            [],
        )
    return (
        probe,
        SimCheck(
            code="test_probe",
            status="fail",
            message="baseline test probe failed",
            details=[f"command={command}", summary],
        ),
        ["fix baseline test failures before running auto"],
    )


def _compute_risk_score(
    *,
    checks: list[SimCheck],
    blockers: list[DoctorCheck],
    recent_attempts: list[SimAttemptSnapshot],
    test_probe: SimTestProbe,
) -> int:
    fail_count = sum(1 for check in checks if check.status == "fail")
    warn_count = sum(1 for check in checks if check.status == "warn")
    score = fail_count * 25 + warn_count * 8
    if blockers:
        score += 20
    if len(recent_attempts) >= 2 and all(item.classification == "no-progress" for item in recent_attempts):
        score += 15
    if test_probe.ran and test_probe.passed is False:
        score += 25
    return max(0, min(100, score))


def _derive_status(*, fail_count: int, warn_count: int, risk_score: int) -> str:
    if fail_count > 0:
        return "blocked"
    if warn_count > 0 or risk_score >= 40:
        return "risky"
    return "ready"


def _dedupe_actions(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
