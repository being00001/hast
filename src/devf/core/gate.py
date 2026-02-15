"""Mechanical gate checks for merge qualification."""

from __future__ import annotations

import fnmatch
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from devf.core.config import Config
from devf.core.goals import Goal
from devf.core.languages import (
    apply_pytest_reliability_flags,
    gate_commands_for_languages,
    resolve_goal_languages,
)
from devf.utils.git import get_changed_files


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    output: str
    skipped: bool = False


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: dict[str, CheckResult]
    summary: str


def run_gate(root: Path, config: Config, goal: Goal, base_commit: str) -> GateResult:
    """Run all gate checks and return aggregate result."""
    if not config.language_profiles:
        return _run_gate_legacy(root, config, goal, base_commit)

    checks: dict[str, CheckResult] = {}
    changed = get_changed_files(root, base_commit)
    languages = resolve_goal_languages(root, goal, config, changed)
    language_checks = gate_commands_for_languages(config, languages)

    for name, command in language_checks:
        check_name = name
        suffix = 2
        while check_name in checks:
            check_name = f"{name}_{suffix}"
            suffix += 1
        checks[check_name] = _run_command_check(
            check_name,
            apply_pytest_reliability_flags(command, config.gate, include_reruns=False),
            root,
        )

    if not checks:
        checks["pytest"] = _run_command_check(
            "pytest",
            apply_pytest_reliability_flags(config.test_command, config.gate, include_reruns=False),
            root,
        )

    if "python" in languages:
        if "mypy" not in checks:
            checks["mypy"] = CheckResult(name="mypy", passed=False, output="", skipped=True)
        if "ruff" not in checks:
            checks["ruff"] = CheckResult(name="ruff", passed=False, output="", skipped=True)

    # diff_size
    checks["diff_size"] = _check_diff_size(root, base_commit, config.gate.max_diff_lines)

    # scope
    checks["scope"] = _check_scope(root, goal, base_commit)
    _run_security_checks(checks, config.gate.security_commands, root)
    checks["required_checks"] = _check_required_checks(
        checks,
        config.gate.required_checks,
        config.gate.fail_on_skipped_required,
    )

    passed = all(c.passed or c.skipped for c in checks.values())
    summary = _format_summary(checks)

    return GateResult(passed=passed, checks=checks, summary=summary)


def _run_gate_legacy(root: Path, config: Config, goal: Goal, base_commit: str) -> GateResult:
    checks: dict[str, CheckResult] = {}
    checks["pytest"] = _run_command_check(
        "pytest",
        apply_pytest_reliability_flags(config.test_command, config.gate, include_reruns=False),
        root,
    )

    if config.gate.mypy_command:
        checks["mypy"] = _run_command_check("mypy", config.gate.mypy_command, root)
    else:
        checks["mypy"] = CheckResult(name="mypy", passed=False, output="", skipped=True)

    if config.gate.ruff_command:
        checks["ruff"] = _run_command_check("ruff", config.gate.ruff_command, root)
    else:
        checks["ruff"] = CheckResult(name="ruff", passed=False, output="", skipped=True)

    checks["diff_size"] = _check_diff_size(root, base_commit, config.gate.max_diff_lines)
    checks["scope"] = _check_scope(root, goal, base_commit)
    _run_security_checks(checks, config.gate.security_commands, root)
    checks["required_checks"] = _check_required_checks(
        checks,
        config.gate.required_checks,
        config.gate.fail_on_skipped_required,
    )

    passed = all(c.passed or c.skipped for c in checks.values())
    summary = _format_summary(checks)
    return GateResult(passed=passed, checks=checks, summary=summary)


def _run_command_check(name: str, command: str, root: Path) -> CheckResult:
    """Run a shell command and return a CheckResult."""
    proc = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    output = proc.stdout + proc.stderr
    return CheckResult(name=name, passed=(proc.returncode == 0), output=output.strip())


def _check_diff_size(root: Path, base_commit: str, max_lines: int) -> CheckResult:
    """Count +/- lines in git diff and check against max_lines."""
    proc = subprocess.run(
        ["git", "diff", base_commit],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    count = 0
    for line in proc.stdout.splitlines():
        if (line.startswith("+") or line.startswith("-")) and not (
            line.startswith("---") or line.startswith("+++")
        ):
            count += 1

    passed = count <= max_lines
    output = f"{count} lines changed (max {max_lines})"
    return CheckResult(name="diff_size", passed=passed, output=output)


def _check_scope(root: Path, goal: Goal, base_commit: str) -> CheckResult:
    """Check that changed files are within allowed_changes patterns."""
    if not goal.allowed_changes:
        return CheckResult(name="scope", passed=True, output="no scope restriction")

    changed = get_changed_files(root, base_commit)

    # Filter out ignored paths
    filtered: list[str] = []
    for f in changed:
        if f.startswith(".ai/"):
            continue
        if "__pycache__/" in f:
            continue
        if f.endswith(".pyc"):
            continue
        filtered.append(f)

    violations: list[str] = []
    for f in filtered:
        if not any(fnmatch.fnmatch(f, pat) for pat in goal.allowed_changes):
            violations.append(f)

    if violations:
        output = "out-of-scope files:\n" + "\n".join(f"  {v}" for v in violations)
        return CheckResult(name="scope", passed=False, output=output)

    return CheckResult(name="scope", passed=True, output="all files in scope")


def _format_summary(checks: dict[str, CheckResult]) -> str:
    """Format gate results as a human-readable summary."""
    lines = ["Gate results:"]
    for name, check in checks.items():
        if check.skipped:
            status = "SKIP"
        elif check.passed:
            status = "PASS"
        else:
            status = "FAIL"
        lines.append(f"  {name}: {status}")

        # For failures, include first 5 lines of output
        if not check.passed and not check.skipped and check.output:
            output_lines = check.output.splitlines()[:5]
            for ol in output_lines:
                lines.append(f"    {ol}")

    return "\n".join(lines)


def _run_security_checks(
    checks: dict[str, CheckResult],
    security_commands: list[str],
    root: Path,
) -> None:
    for idx, command in enumerate(security_commands, start=1):
        base_name = _guess_security_check_name(command, idx)
        check_name = base_name
        suffix = 2
        while check_name in checks:
            check_name = f"{base_name}_{suffix}"
            suffix += 1
        checks[check_name] = _run_command_check(check_name, command, root)


def _guess_security_check_name(command: str, idx: int) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    first = tokens[0].lower() if tokens else ""
    lowered = command.lower()

    if "gitleaks" in lowered or first == "gitleaks":
        return "gitleaks"
    if "semgrep" in lowered or first == "semgrep":
        return "semgrep"
    if "trivy" in lowered or first == "trivy":
        return "trivy"
    if "grype" in lowered or first == "grype":
        return "grype"
    if "bandit" in lowered or first == "bandit":
        return "bandit"
    return f"security_check_{idx}"


def _check_required_checks(
    checks: dict[str, CheckResult],
    required_checks: list[str],
    fail_on_skipped_required: bool,
) -> CheckResult:
    if not required_checks:
        return CheckResult(
            name="required_checks",
            passed=True,
            output="no required checks configured",
        )

    missing: list[str] = []
    skipped: list[str] = []
    for check_name in required_checks:
        check = checks.get(check_name)
        if check is None:
            missing.append(check_name)
            continue
        if check.skipped and fail_on_skipped_required:
            skipped.append(check_name)

    if not missing and not skipped:
        return CheckResult(
            name="required_checks",
            passed=True,
            output=f"all required checks present: {', '.join(required_checks)}",
        )

    details: list[str] = []
    if missing:
        details.append(f"missing={','.join(missing)}")
    if skipped:
        details.append(f"skipped={','.join(skipped)}")
    output = "required checks unmet: " + "; ".join(details)
    return CheckResult(name="required_checks", passed=False, output=output)
