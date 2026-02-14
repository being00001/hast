"""Mechanical gate checks for merge qualification."""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path

from devf.core.config import Config
from devf.core.goals import Goal
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
    checks: dict[str, CheckResult] = {}

    # pytest
    checks["pytest"] = _run_command_check("pytest", config.test_command, root)

    # mypy
    if config.gate.mypy_command:
        checks["mypy"] = _run_command_check("mypy", config.gate.mypy_command, root)
    else:
        checks["mypy"] = CheckResult(name="mypy", passed=False, output="", skipped=True)

    # ruff
    if config.gate.ruff_command:
        checks["ruff"] = _run_command_check("ruff", config.gate.ruff_command, root)
    else:
        checks["ruff"] = CheckResult(name="ruff", passed=False, output="", skipped=True)

    # diff_size
    checks["diff_size"] = _check_diff_size(root, base_commit, config.gate.max_diff_lines)

    # scope
    checks["scope"] = _check_scope(root, goal, base_commit)

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
