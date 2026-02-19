"""Preflight diagnostics for hast projects."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shlex
import shutil
from typing import Callable

import yaml

from hast.core.config import Config, load_config
from hast.core.errors import DevfError
from hast.core.goals import iter_goals, load_goals
from hast.core.protocol_adapters import load_protocol_adapter_policy
from hast.core.retry_policy import load_retry_policy
from hast.core.risk_policy import load_risk_policy
from hast.core.execution_queue import load_execution_queue_policy
from hast.core.observability import load_observability_policy
from hast.core.event_bus import load_event_bus_policy
from hast.core.operator_inbox import load_operator_inbox_policy
from hast.core.consumer_roles import load_consumer_role_policy
from hast.core.feedback_policy import load_feedback_policy
from hast.core.admission_policy import load_admission_policy
from hast.core.docs_policy import load_docs_policy
from hast.core.immune_policy import load_immune_policy
from hast.core.security_policy import load_security_policy
from hast.core.spike_policy import load_spike_policy
from hast.utils.git import run_git


@dataclass(frozen=True)
class DoctorCheck:
    code: str
    status: str  # pass | warn | fail
    message: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DoctorReport:
    root: str
    checks: list[DoctorCheck]
    pass_count: int
    warn_count: int
    fail_count: int
    ok: bool


AUTO_PREFLIGHT_BLOCKING_WARN_CODES = {
    "git_dirty",
    "git_worktree",
}


_REQUIRED_DIRS = (
    "decisions",
    "proposals",
    "protocols",
    "templates",
    "schemas",
    "policies",
    "sessions",
    "handoffs",
)
_REQUIRED_FILES = ("config.yaml", "goals.yaml", "rules.md")
_REQUIRED_POLICY_FILES = (
    "admission_policy.yaml",
    "consumer_role_policy.yaml",
    "docs_policy.yaml",
    "event_bus_policy.yaml",
    "execution_queue_policy.yaml",
    "feedback_policy.yaml",
    "immune_policy.yaml",
    "model_routing.yaml",
    "observability_policy.yaml",
    "operator_inbox_policy.yaml",
    "protocol_adapter_policy.yaml",
    "retry_policy.yaml",
    "risk_policy.yaml",
    "security_policy.yaml",
    "spike_policy.yaml",
    "transition_policy.yaml",
)


def run_doctor(root: Path) -> DoctorReport:
    checks: list[DoctorCheck] = []
    ai_dir = root / ".ai"
    config: Config | None = None

    if not ai_dir.exists():
        checks.append(
            DoctorCheck(
                code="ai_layout",
                status="fail",
                message="missing .ai directory",
                details=["run `hast init` from project root"],
            )
        )
        return _to_report(root, checks)

    checks.extend(_check_layout(root))
    config, config_check = _check_config(root)
    checks.append(config_check)
    checks.extend(_check_goals(root))
    checks.extend(_check_policies(root))

    if config is not None:
        checks.append(_check_command_resolution(root, config))
    else:
        checks.append(
            DoctorCheck(
                code="command_resolution",
                status="warn",
                message="skipped command resolution because config is invalid",
            )
        )

    checks.append(_check_dirty_tree(root))
    checks.append(_check_worktrees(root))
    checks.append(_check_auto_lock(root))
    return _to_report(root, checks)


def report_to_dict(report: DoctorReport) -> dict:
    return {
        "root": report.root,
        "ok": report.ok,
        "pass_count": report.pass_count,
        "warn_count": report.warn_count,
        "fail_count": report.fail_count,
        "checks": [
            {
                "code": check.code,
                "status": check.status,
                "message": check.message,
                "details": list(check.details),
            }
            for check in report.checks
        ],
    }


def format_doctor_report(report: DoctorReport) -> str:
    lines = [
        "hast doctor",
        f"root: {report.root}",
        f"summary: pass={report.pass_count} warn={report.warn_count} fail={report.fail_count}",
    ]
    if report.ok and report.warn_count == 0:
        lines.append("status: OK")
    elif report.ok:
        lines.append("status: WARN")
    else:
        lines.append("status: FAIL")

    for check in report.checks:
        badge = {
            "pass": "[PASS]",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }.get(check.status, "[INFO]")
        lines.append(f"{badge} {check.code}: {check.message}")
        for detail in check.details:
            lines.append(f"  - {detail}")
    return "\n".join(lines)


def auto_preflight_blockers(report: DoctorReport) -> list[DoctorCheck]:
    """Return checks that should block `hast auto` startup."""
    blockers: list[DoctorCheck] = []
    for check in report.checks:
        if check.status == "fail":
            blockers.append(check)
            continue
        if check.status != "warn":
            continue
        if check.code in AUTO_PREFLIGHT_BLOCKING_WARN_CODES:
            blockers.append(check)
            continue
        if check.code == "auto_lock":
            # Block when another auto loop is likely running or lock is unreadable.
            lowered = check.message.lower()
            if "auto appears running" in lowered or "unreadable" in lowered:
                blockers.append(check)
    return blockers


def format_auto_preflight_failure(blockers: list[DoctorCheck]) -> str:
    lines = [
        "auto preflight failed (risk state detected).",
        "Run `hast doctor` for full diagnostics.",
    ]
    for check in blockers:
        lines.append(f"- {check.code}: {check.message}")
        for detail in check.details[:5]:
            lines.append(f"  * {detail}")
    return "\n".join(lines)


def _check_layout(root: Path) -> list[DoctorCheck]:
    ai_dir = root / ".ai"
    missing_dirs = [name for name in _REQUIRED_DIRS if not (ai_dir / name).is_dir()]
    missing_files = [name for name in _REQUIRED_FILES if not (ai_dir / name).exists()]
    checks: list[DoctorCheck] = []

    if missing_dirs:
        checks.append(
            DoctorCheck(
                code="layout_dirs",
                status="warn",
                message="missing recommended .ai directories",
                details=missing_dirs[:10],
            )
        )
    else:
        checks.append(
            DoctorCheck(
                code="layout_dirs",
                status="pass",
                message="required .ai directories are present",
            )
        )

    if missing_files:
        checks.append(
            DoctorCheck(
                code="layout_files",
                status="fail",
                message="missing required .ai files",
                details=missing_files[:10],
            )
        )
    else:
        checks.append(
            DoctorCheck(
                code="layout_files",
                status="pass",
                message="required .ai files are present",
            )
        )
    return checks


def _check_config(root: Path) -> tuple[Config | None, DoctorCheck]:
    config_path = root / ".ai" / "config.yaml"
    if not config_path.exists():
        return (
            None,
            DoctorCheck(
                code="config",
                status="fail",
                message="config missing: .ai/config.yaml",
            ),
        )

    try:
        config, warnings = load_config(config_path)
    except DevfError as exc:
        return (
            None,
            DoctorCheck(
                code="config",
                status="fail",
                message=f"invalid config: {exc}",
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return (
            None,
            DoctorCheck(
                code="config",
                status="fail",
                message=f"failed to parse config: {exc}",
            ),
        )

    if warnings:
        return (
            config,
            DoctorCheck(
                code="config",
                status="warn",
                message="config loaded with warnings",
                details=warnings[:10],
            ),
        )
    return (
        config,
        DoctorCheck(
            code="config",
            status="pass",
            message="config is valid",
        ),
    )


def _check_goals(root: Path) -> list[DoctorCheck]:
    goals_path = root / ".ai" / "goals.yaml"
    if not goals_path.exists():
        return [
            DoctorCheck(
                code="goals",
                status="fail",
                message="goals missing: .ai/goals.yaml",
            )
        ]

    try:
        goals = load_goals(goals_path)
    except DevfError as exc:
        return [
            DoctorCheck(
                code="goals",
                status="fail",
                message=f"invalid goals: {exc}",
            )
        ]
    except Exception as exc:  # pragma: no cover - defensive
        return [
            DoctorCheck(
                code="goals",
                status="fail",
                message=f"failed to parse goals: {exc}",
            )
        ]

    total = 0
    active = 0
    for node in iter_goals(goals):
        total += 1
        if node.goal.status == "active":
            active += 1

    if total == 0:
        return [
            DoctorCheck(
                code="goals",
                status="warn",
                message="no goals defined",
                details=["add at least one active goal to .ai/goals.yaml"],
            )
        ]
    if active == 0:
        return [
            DoctorCheck(
                code="goals",
                status="warn",
                message=f"{total} goals parsed, but no active goal",
                details=["set one goal to status: active"],
            )
        ]
    return [
        DoctorCheck(
            code="goals",
            status="pass",
            message=f"goals parsed: total={total}, active={active}",
        )
    ]


def _check_policies(root: Path) -> list[DoctorCheck]:
    policies_dir = root / ".ai" / "policies"
    missing = [name for name in _REQUIRED_POLICY_FILES if not (policies_dir / name).exists()]

    checks: list[DoctorCheck] = []
    if missing:
        checks.append(
            DoctorCheck(
                code="policy_files",
                status="warn",
                message="missing recommended policy files",
                details=missing[:10],
            )
        )
    else:
        checks.append(
            DoctorCheck(
                code="policy_files",
                status="pass",
                message="policy files are present",
            )
        )

    loaders: list[tuple[str, Callable[[Path], object]]] = [
        ("retry_policy", load_retry_policy),
        ("risk_policy", load_risk_policy),
        ("feedback_policy", load_feedback_policy),
        ("admission_policy", load_admission_policy),
        ("docs_policy", load_docs_policy),
        ("immune_policy", load_immune_policy),
        ("security_policy", load_security_policy),
        ("spike_policy", load_spike_policy),
        ("execution_queue_policy", load_execution_queue_policy),
        ("observability_policy", load_observability_policy),
        ("event_bus_policy", load_event_bus_policy),
        ("operator_inbox_policy", load_operator_inbox_policy),
        ("consumer_role_policy", load_consumer_role_policy),
        ("protocol_adapter_policy", load_protocol_adapter_policy),
    ]
    loader_errors: list[str] = []
    for name, loader in loaders:
        try:
            loader(root)
        except Exception as exc:
            loader_errors.append(f"{name}: {exc}")

    if loader_errors:
        checks.append(
            DoctorCheck(
                code="policy_parse",
                status="fail",
                message="policy parse failed",
                details=loader_errors[:10],
            )
        )
    else:
        checks.append(
            DoctorCheck(
                code="policy_parse",
                status="pass",
                message="policy loaders parsed successfully",
            )
        )
    return checks


def _check_command_resolution(root: Path, config: Config) -> DoctorCheck:
    commands: list[tuple[str, str]] = [
        ("test_command", config.test_command),
        ("ai_tool", config.ai_tool),
    ]
    for name in sorted(config.ai_tools.keys()):
        commands.append((f"ai_tools.{name}", config.ai_tools[name]))

    unresolved: list[str] = []
    parse_errors: list[str] = []

    for label, command in commands:
        try:
            executable = _extract_executable(command)
        except ValueError as exc:
            parse_errors.append(f"{label}: {exc}")
            continue
        if not executable:
            parse_errors.append(f"{label}: empty command")
            continue
        if "{" in executable or "}" in executable:
            # Template placeholders as first token are uncommon but valid in wrappers.
            continue
        if executable.startswith("$("):
            continue
        if "/" in executable:
            path = Path(executable)
            if not path.is_absolute():
                path = root / path
            if path.exists():
                continue
            unresolved.append(f"{label}: {executable}")
            continue
        if shutil.which(executable) is None:
            unresolved.append(f"{label}: {executable}")

    if parse_errors:
        return DoctorCheck(
            code="command_resolution",
            status="fail",
            message="invalid command syntax in config",
            details=parse_errors[:10],
        )
    if unresolved:
        return DoctorCheck(
            code="command_resolution",
            status="warn",
            message="some configured commands are not resolvable in PATH",
            details=unresolved[:10],
        )
    return DoctorCheck(
        code="command_resolution",
        status="pass",
        message="configured commands are resolvable",
    )


def _check_dirty_tree(root: Path) -> DoctorCheck:
    result = run_git(["status", "--porcelain"], root, check=False)
    if result.returncode != 0:
        return DoctorCheck(
            code="git_dirty",
            status="warn",
            message="git status unavailable",
            details=[result.stderr.strip() or "not a git repository"],
        )

    blocking: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if code == "??" and path.startswith(".ai/"):
            continue
        if path:
            blocking.append(path)

    if blocking:
        return DoctorCheck(
            code="git_dirty",
            status="warn",
            message="working tree is dirty outside .ai operational artifacts",
            details=sorted(set(blocking))[:10],
        )
    return DoctorCheck(
        code="git_dirty",
        status="pass",
        message="working tree is clean for auto startup checks",
    )


def _check_worktrees(root: Path) -> DoctorCheck:
    result = run_git(["worktree", "list", "--porcelain"], root, check=False)
    if result.returncode != 0:
        return DoctorCheck(
            code="git_worktree",
            status="warn",
            message="git worktree list unavailable",
            details=[result.stderr.strip() or "worktree command failed"],
        )

    prunable = [line.strip() for line in result.stdout.splitlines() if line.startswith("prunable ")]
    active_goals = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("branch refs/heads/goal/")
    ]
    if prunable:
        return DoctorCheck(
            code="git_worktree",
            status="warn",
            message="stale worktree metadata detected",
            details=prunable[:10] + ["run `git worktree prune`"],
        )
    return DoctorCheck(
        code="git_worktree",
        status="pass",
        message=f"goal worktrees healthy (active={len(active_goals)})",
    )


def _check_auto_lock(root: Path) -> DoctorCheck:
    lock_path = root / ".ai" / "auto.lock"
    if not lock_path.exists():
        return DoctorCheck(code="auto_lock", status="pass", message="no active auto lock")

    try:
        payload = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return DoctorCheck(
            code="auto_lock",
            status="warn",
            message="auto lock exists but is unreadable",
            details=[str(exc)],
        )
    pid = payload.get("pid")
    started_at = payload.get("started_at")
    if isinstance(pid, int) and _pid_alive(pid):
        return DoctorCheck(
            code="auto_lock",
            status="warn",
            message=f"auto appears running (pid={pid})",
            details=[f"started_at={started_at}" if isinstance(started_at, str) else "started_at=unknown"],
        )
    return DoctorCheck(
        code="auto_lock",
        status="warn",
        message="stale auto lock detected",
        details=["remove .ai/auto.lock if no auto loop is running"],
    )


def _extract_executable(command: str) -> str | None:
    tokens = shlex.split(command)
    for token in tokens:
        if _looks_like_env_assignment(token):
            continue
        return token
    return None


def _looks_like_env_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    key, _value = token.split("=", 1)
    if not key:
        return False
    if key[0].isdigit():
        return False
    return all(ch == "_" or ch.isalnum() for ch in key)


def _to_report(root: Path, checks: list[DoctorCheck]) -> DoctorReport:
    pass_count = sum(1 for check in checks if check.status == "pass")
    warn_count = sum(1 for check in checks if check.status == "warn")
    fail_count = sum(1 for check in checks if check.status == "fail")
    return DoctorReport(
        root=root.as_posix(),
        checks=checks,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        ok=fail_count == 0,
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
