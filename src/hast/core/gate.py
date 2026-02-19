"""Mechanical gate checks for merge qualification."""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from hast.core.config import Config
from hast.core.goals import Goal
from hast.core.languages import (
    apply_pytest_reliability_flags,
    gate_commands_for_languages,
    resolve_goal_languages,
)
from hast.core.security_policy import SecurityIgnoreRule, SecurityPolicy, load_security_policy
from hast.utils.git import get_changed_files


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    output: str
    skipped: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: dict[str, CheckResult]
    summary: str


@dataclass(frozen=True)
class _SecurityCheckSpec:
    name: str
    command: str | None
    missing_tool: str | None = None


def run_gate(root: Path, config: Config, goal: Goal, base_commit: str) -> GateResult:
    """Run all gate checks and return aggregate result."""
    if not config.language_profiles:
        return _run_gate_legacy(root, config, goal, base_commit)

    checks: dict[str, CheckResult] = {}
    security_policy = load_security_policy(root)
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

    _run_mutation_checks(checks, config, goal, languages, root)

    if "python" in languages:
        if "mypy" not in checks:
            checks["mypy"] = CheckResult(name="mypy", passed=False, output="", skipped=True)
        if "ruff" not in checks:
            checks["ruff"] = CheckResult(name="ruff", passed=False, output="", skipped=True)

    # diff_size
    checks["diff_size"] = _check_diff_size(root, base_commit, config.gate.max_diff_lines)

    # scope
    checks["scope"] = _check_scope(
        root,
        goal,
        base_commit,
        always_allow=config.always_allow_changes,
    )
    _run_security_checks(checks, config.gate.security_commands, root, security_policy)
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
    security_policy = load_security_policy(root)
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

    _run_mutation_checks(checks, config, goal, ["python"], root)

    checks["diff_size"] = _check_diff_size(root, base_commit, config.gate.max_diff_lines)
    checks["scope"] = _check_scope(
        root,
        goal,
        base_commit,
        always_allow=config.always_allow_changes,
    )
    _run_security_checks(checks, config.gate.security_commands, root, security_policy)
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


def _run_mutation_checks(
    checks: dict[str, CheckResult],
    config: Config,
    goal: Goal,
    languages: list[str],
    root: Path,
) -> None:
    targets = [lang for lang in languages if lang in {"python", "rust"}]
    if not targets or not config.gate.mutation_enabled:
        return

    if any(not check.passed and not check.skipped for check in checks.values()):
        for lang in targets:
            name = f"mutation_{lang}"
            checks[name] = CheckResult(
                name=name,
                passed=False,
                output="skipped: prerequisite checks failed",
                skipped=True,
            )
        return

    if config.gate.mutation_high_risk_only and goal.uncertainty != "high":
        for lang in targets:
            name = f"mutation_{lang}"
            checks[name] = CheckResult(
                name=name,
                passed=False,
                output="skipped: mutation checks run only for uncertainty=high goals",
                skipped=True,
            )
        return

    for lang in targets:
        check_name = f"mutation_{lang}"
        if lang == "python":
            command = config.gate.mutation_python_command.strip()
            min_score = config.gate.min_mutation_score_python
        else:
            command = config.gate.mutation_rust_command.strip()
            min_score = config.gate.min_mutation_score_rust

        if not command:
            checks[check_name] = CheckResult(
                name=check_name,
                passed=False,
                output="skipped: mutation command not configured",
                skipped=True,
            )
            continue

        checks[check_name] = _run_mutation_command(check_name, command, min_score, root)


def _run_mutation_command(name: str, command: str, min_score: int, root: Path) -> CheckResult:
    proc = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    output = (proc.stdout + proc.stderr).strip()
    score = _extract_mutation_score(output)

    if proc.returncode != 0:
        rendered = output or "mutation command failed"
        return CheckResult(name=name, passed=False, output=rendered)

    if score is None:
        detail = "mutation score not found in output"
        rendered = detail if not output else f"{detail}\n{output}"
        return CheckResult(name=name, passed=False, output=rendered)

    passed = score >= float(min_score)
    detail = f"mutation_score={score:.1f} min_required={min_score}"
    if output:
        detail = f"{detail}\n{output}"
    return CheckResult(name=name, passed=passed, output=detail)


def _extract_mutation_score(output: str) -> float | None:
    if not output.strip():
        return None
    lowered = output.lower()

    for pattern in (
        r"mutation\s*score\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*%?",
        r"\"mutation_score\"\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        r"score\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    ):
        match = re.search(pattern, lowered)
        if match:
            return float(match.group(1))

    killed = re.search(r"killed\s*[:=]?\s*([0-9]+)\s*/\s*([0-9]+)", lowered)
    if killed:
        num = int(killed.group(1))
        den = int(killed.group(2))
        if den > 0:
            return (100.0 * num) / den

    survived = re.search(r"survived\s*[:=]?\s*([0-9]+)\s*/\s*([0-9]+)", lowered)
    if survived:
        num = int(survived.group(1))
        den = int(survived.group(2))
        if den > 0:
            killed_ratio = max(0.0, float(den - num))
            return (100.0 * killed_ratio) / den

    return None


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


def _check_scope(
    root: Path,
    goal: Goal,
    base_commit: str,
    always_allow: list[str] | None = None,
) -> CheckResult:
    """Check that changed files are within allowed_changes patterns."""
    if not goal.allowed_changes:
        return CheckResult(name="scope", passed=True, output="no scope restriction")

    changed = get_changed_files(root, base_commit)
    always_allow_patterns = always_allow or []

    # Filter out ignored paths
    filtered: list[str] = []
    for f in changed:
        if f.startswith(".ai/"):
            continue
        if "__pycache__/" in f:
            continue
        if f.endswith(".pyc"):
            continue
        if any(fnmatch.fnmatch(f, pattern) for pattern in always_allow_patterns):
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

        # Include details for failures and security-ignore metadata.
        include_output = (
            (not check.passed and not check.skipped and bool(check.output))
            or ("[security-ignore]" in check.output)
            or ("[security-ignore-expired]" in check.output)
            or ("missing security tool" in check.output.lower())
        )
        if include_output:
            output_lines = check.output.splitlines()[:5]
            for ol in output_lines:
                lines.append(f"    {ol}")

    return "\n".join(lines)


def _run_security_checks(
    checks: dict[str, CheckResult],
    security_commands: list[str],
    root: Path,
    policy: SecurityPolicy,
) -> None:
    specs = _build_security_specs(security_commands, policy)
    for spec in specs:
        check_name = _dedupe_check_name(checks, spec.name)
        base_check = _base_security_check_name(check_name)

        if spec.command is None:
            message = f"missing security tool: {spec.missing_tool or check_name}"
            missing_result = CheckResult(
                name=check_name,
                passed=False,
                output=message if policy.fail_on_missing_tools else f"skipped: {message}",
                skipped=not policy.fail_on_missing_tools,
                metadata={"missing_tool": spec.missing_tool or check_name},
            )
            checks[check_name] = _maybe_apply_security_ignore(
                root=root,
                policy=policy,
                check_name=check_name,
                base_check_name=base_check,
                status_before="FAIL" if policy.fail_on_missing_tools else "SKIP",
                result=missing_result,
            )
            continue
        raw_result = _run_command_check(check_name, spec.command, root)
        status_before = "PASS" if raw_result.passed else "FAIL"
        checks[check_name] = _maybe_apply_security_ignore(
            root=root,
            policy=policy,
            check_name=check_name,
            base_check_name=base_check,
            status_before=status_before,
            result=raw_result,
        )


def _maybe_apply_security_ignore(
    *,
    root: Path,
    policy: SecurityPolicy,
    check_name: str,
    base_check_name: str,
    status_before: str,
    result: CheckResult,
) -> CheckResult:
    if status_before == "PASS":
        return result

    applied_rule = _match_ignore_rule(
        policy.ignore_rules,
        base_check_name=base_check_name,
        output=result.output,
        now=date.today(),
        include_expired=False,
    )
    if applied_rule is not None:
        expires_on = applied_rule.expires_on.isoformat() if applied_rule.expires_on else "never"
        reason = applied_rule.reason or "unspecified"
        line = (
            f"[security-ignore] rule={applied_rule.rule_id} "
            f"check={check_name} expires_on={expires_on} reason={reason}"
        )
        _append_security_audit(
            root=root,
            policy=policy,
            event_type="security-ignore-applied",
            check_name=check_name,
            status_before=status_before,
            status_after="PASS",
            rule=applied_rule,
        )
        output = line if not result.output else f"{line}\n{result.output}"
        metadata = dict(result.metadata)
        metadata["ignore_rule_id"] = applied_rule.rule_id
        metadata["ignore_expires_on"] = expires_on
        return CheckResult(
            name=result.name,
            passed=True,
            output=output,
            skipped=False,
            metadata=metadata,
        )

    expired_rule = _match_ignore_rule(
        policy.ignore_rules,
        base_check_name=base_check_name,
        output=result.output,
        now=date.today(),
        include_expired=True,
    )
    if expired_rule is not None:
        expires_on = expired_rule.expires_on.isoformat() if expired_rule.expires_on else "unknown"
        line = (
            f"[security-ignore-expired] rule={expired_rule.rule_id} "
            f"check={check_name} expires_on={expires_on}"
        )
        _append_security_audit(
            root=root,
            policy=policy,
            event_type="security-ignore-expired",
            check_name=check_name,
            status_before=status_before,
            status_after=status_before,
            rule=expired_rule,
        )
        output = line if not result.output else f"{line}\n{result.output}"
        return CheckResult(
            name=result.name,
            passed=result.passed,
            output=output,
            skipped=result.skipped,
            metadata=result.metadata,
        )
    return result


def _match_ignore_rule(
    rules: list[SecurityIgnoreRule],
    *,
    base_check_name: str,
    output: str,
    now: date,
    include_expired: bool,
) -> SecurityIgnoreRule | None:
    for rule in rules:
        if rule.checks and base_check_name not in rule.checks:
            continue
        try:
            matched = bool(re.search(rule.pattern, output, flags=re.IGNORECASE))
        except re.error:
            continue
        if not matched:
            continue

        expired = bool(rule.expires_on and rule.expires_on < now)
        if include_expired:
            if expired:
                return rule
            continue
        if not expired:
            return rule
    return None


def _append_security_audit(
    *,
    root: Path,
    policy: SecurityPolicy,
    event_type: str,
    check_name: str,
    status_before: str,
    status_after: str,
    rule: SecurityIgnoreRule,
) -> None:
    if not policy.audit_file:
        return
    path = root / policy.audit_file
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "policy_version": policy.version,
        "check_name": check_name,
        "status_before": status_before,
        "status_after": status_after,
        "rule_id": rule.rule_id,
        "reason": rule.reason,
        "expires_on": rule.expires_on.isoformat() if rule.expires_on else None,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _base_security_check_name(check_name: str) -> str:
    return re.sub(r"_\d+$", "", check_name)


def _build_security_specs(
    security_commands: list[str],
    policy: SecurityPolicy,
) -> list[_SecurityCheckSpec]:
    specs: list[_SecurityCheckSpec] = []

    for idx, command in enumerate(security_commands, start=1):
        specs.append(
            _SecurityCheckSpec(
                name=_guess_security_check_name(command, idx),
                command=command,
            )
        )

    if not policy.enabled:
        return specs

    if policy.gitleaks_enabled:
        specs.append(_tool_spec("gitleaks", policy.gitleaks_command))
    if policy.semgrep_enabled:
        specs.append(_tool_spec("semgrep", policy.semgrep_command))

    dep_specs: list[_SecurityCheckSpec] = []
    if policy.trivy_enabled:
        dep_specs.append(_tool_spec("trivy", policy.trivy_command))
    if policy.grype_enabled:
        dep_specs.append(_tool_spec("grype", policy.grype_command))

    if policy.dependency_scanner_mode == "all":
        specs.extend(dep_specs)
    elif dep_specs:
        selected = next((item for item in dep_specs if item.command is not None), None)
        if selected is None:
            specs.append(
                _SecurityCheckSpec(
                    name="dependency_scan",
                    command=None,
                    missing_tool="trivy|grype",
                )
            )
        else:
            specs.append(
                _SecurityCheckSpec(
                    name="dependency_scan",
                    command=selected.command,
                    missing_tool=selected.missing_tool,
                )
            )

    return specs


def _tool_spec(name: str, command: str) -> _SecurityCheckSpec:
    tool = _extract_first_token(command)
    if tool and shutil.which(tool):
        return _SecurityCheckSpec(name=name, command=command, missing_tool=tool)
    return _SecurityCheckSpec(name=name, command=None, missing_tool=tool or name)


def _extract_first_token(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return tokens[0] if tokens else ""


def _dedupe_check_name(checks: dict[str, CheckResult], base_name: str) -> str:
    check_name = base_name
    suffix = 2
    while check_name in checks:
        check_name = f"{base_name}_{suffix}"
        suffix += 1
    return check_name


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
