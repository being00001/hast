"""Automation loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import fnmatch
import os
import sys
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Iterable

import yaml

from devf.core.attempt import (
    AttemptLog,
    clear_attempts,
    load_attempts,
    save_attempt,
)
from devf.core.config import Config, load_config
from devf.core.context import build_context
from devf.core.errors import DevfError
from devf.core.gate import run_gate
from devf.core.goals import Goal, collect_goals, load_goals, update_goal_fields, update_goal_status
from devf.core.phase import load_phase_template, next_phase, parse_plan_output, regress_phase
from devf.core.runner import GoalRunner
from devf.core.runners.local import LocalRunner
from devf.core.session import generate_session_log, write_session_log
from devf.utils.codetools import complexity_check
from devf.utils.git import (
    commit_all,
    get_changed_files,
    get_head_commit,
    is_dirty,
    reset_hard,
    worktree_create,
    worktree_merge,
    worktree_remove,
)


@dataclass(frozen=True)
class Outcome:
    success: bool
    should_retry: bool
    classification: str
    reason: str | None = None


def run_auto(
    root: Path,
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    explain: bool,
    tool_name: str | None,
    runner: GoalRunner | None = None,
) -> int:
    config, warnings = load_config(root / ".ai" / "config.yaml")
    for warning in warnings:
        _log_warning(warning)

    goals = load_goals(root / ".ai" / "goals.yaml")
    selected = collect_goals(goals, goal_id, recursive)
    if not selected:
        raise DevfError("no active goals to run")

    # dry-run: print prompt and exit, no lock or dirty check needed
    if dry_run:
        for goal in selected:
            if goal.phase:
                print(build_phase_prompt(root, config, goal, goal.phase, []))
            else:
                print(build_prompt(root, config, goal, []))
        return 0

    # Use LocalRunner by default if none provided
    if runner is None:
        runner = LocalRunner()

    _acquire_lock(root)
    try:
        has_failure = False
        cycle_count = 0
        no_progress_count = 0

        for goal in selected:
            # Circuit breaker: max cycles
            cycle_count += 1
            if cycle_count > config.circuit_breakers.max_cycles_per_session:
                _log_warning("Circuit breaker: max cycles per session reached")
                break

            wt_root = worktree_create(root, goal.id)
            base_commit = get_head_commit(wt_root)
            goals_path = root / ".ai" / "goals.yaml"

            phase = goal.phase  # None = legacy

            if phase is None:
                # Legacy behavior (no phase field)
                goal_ok = _run_legacy_goal(
                    wt_root, root, config, goal, config.max_retries,
                    runner, tool_name, explain, base_commit,
                )
            elif phase == "gate":
                # Gate: no AI, just run checks
                outcome, gate_output = evaluate_phase(wt_root, config, goal, "gate", base_commit)
                if outcome.success:
                    nxt = next_phase("gate")  # "adversarial"
                    update_goal_fields(goals_path, goal.id, {"phase": nxt})
                    goal_ok = True
                else:
                    update_goal_fields(goals_path, goal.id, {"phase": regress_phase("gate")})
                    goal_ok = False
            elif phase == "merge":
                # Merge: just do it
                if is_dirty(wt_root):
                    commit_all(wt_root, f"devf({goal.id}): pre-merge")
                worktree_merge(root, goal.id)
                update_goal_status(goals_path, goal.id, "done")
                clear_attempts(root, goal.id)
                goal_ok = True
            else:
                # plan, implement, adversarial: AI execution
                goal_ok = _run_phased_goal(
                    wt_root, root, config, goal, phase, config.max_retries,
                    runner, tool_name, explain, base_commit,
                )

            # Circuit breaker: no-progress tracking
            if not goal_ok:
                no_progress_count += 1
                worktree_remove(root, goal.id)
                if phase is not None and phase != "gate":
                    # For phased goals, don't change status to blocked
                    pass
                else:
                    update_goal_status(goals_path, goal.id, "blocked")
                has_failure = True
            else:
                no_progress_count = 0

            if no_progress_count >= config.circuit_breakers.max_consecutive_no_progress:
                _log_warning("Circuit breaker: max consecutive no-progress reached")
                break

        return 1 if has_failure else 0
    finally:
        _release_lock(root)


def _run_legacy_goal(
    wt_root: Path,
    root: Path,
    config: Config,
    goal: Goal,
    max_retries: int,
    runner: GoalRunner,
    tool_name: str | None,
    explain: bool,
    base_commit: str,
) -> bool:
    """Execute a goal without phase awareness (legacy behavior)."""
    for attempt in range(1, max_retries + 1):
        attempts_history = load_attempts(root, goal.id)
        prompt = build_prompt(wt_root, config, goal, attempts_history)

        result = runner.run(wt_root, config, goal, prompt, tool_name)
        if not result.success and result.error_message:
            _log_warning(f"Runner error: {result.error_message}")

        outcome, test_output = evaluate(wt_root, config, goal, base_commit)

        if explain:
            _log_info(
                f"[{goal.id}] attempt={attempt} -> {outcome.classification}: "
                f"{outcome.reason or ''}".strip()
            )

        if outcome.success:
            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): {goal.title}")
            log_content = generate_session_log(wt_root, goal, base_commit, test_output)
            session_dir = wt_root / ".ai" / "sessions"
            write_session_log(session_dir, log_content)
            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): session log")
            worktree_merge(root, goal.id)
            update_goal_status(root / ".ai" / "goals.yaml", goal.id, "done")
            clear_attempts(root, goal.id)
            return True

        if outcome.should_retry:
            diff_stat = _get_diff_stat(wt_root, base_commit)
            diff = _get_diff(wt_root, base_commit)
            save_attempt(
                root, goal.id, attempt, outcome.classification, outcome.reason,
                diff_stat, test_output, diff=diff,
            )
            reset_hard(wt_root, base_commit)
            continue

        # Non-retryable failure
        diff_stat = _get_diff_stat(wt_root, base_commit)
        diff = _get_diff(wt_root, base_commit)
        save_attempt(
            root, goal.id, attempt, outcome.classification, outcome.reason,
            diff_stat, test_output, diff=diff,
        )
        break

    return False


def _run_phased_goal(
    wt_root: Path,
    root: Path,
    config: Config,
    goal: Goal,
    phase: str,
    max_retries: int,
    runner: GoalRunner,
    tool_name: str | None,
    explain: bool,
    base_commit: str,
) -> bool:
    """Execute a goal with phase awareness."""
    goals_path = root / ".ai" / "goals.yaml"

    for attempt in range(1, max_retries + 1):
        attempts_history = load_attempts(root, goal.id)
        prompt = build_phase_prompt(wt_root, config, goal, phase, attempts_history)

        result = runner.run(wt_root, config, goal, prompt, tool_name)
        if not result.success and result.error_message:
            _log_warning(f"Runner error: {result.error_message}")

        outcome, test_output = evaluate_phase(wt_root, config, goal, phase, base_commit)

        if explain:
            _log_info(
                f"[{goal.id}] phase={phase} attempt={attempt} -> {outcome.classification}: "
                f"{outcome.reason or ''}".strip()
            )

        if outcome.success:
            # Handle plan phase output parsing
            if phase == "plan" and result.output:
                parsed = parse_plan_output(result.output)
                if parsed:
                    update_goal_fields(goals_path, goal.id, parsed)

            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): {phase}")

            # Generate session log
            log_content = generate_session_log(wt_root, goal, base_commit, test_output)
            session_dir = wt_root / ".ai" / "sessions"
            write_session_log(session_dir, log_content)
            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): {phase} session log")

            # Advance to next phase
            nxt = next_phase(phase)
            if nxt == "merge":
                worktree_merge(root, goal.id)
                update_goal_status(goals_path, goal.id, "done")
                clear_attempts(root, goal.id)
            elif nxt is not None:
                update_goal_fields(goals_path, goal.id, {"phase": nxt})
            return True

        if outcome.should_retry:
            diff_stat = _get_diff_stat(wt_root, base_commit)
            diff = _get_diff(wt_root, base_commit)
            save_attempt(
                root, goal.id, attempt, outcome.classification, outcome.reason,
                diff_stat, test_output, diff=diff,
            )
            reset_hard(wt_root, base_commit)
            continue

        # Non-retryable failure
        diff_stat = _get_diff_stat(wt_root, base_commit)
        diff = _get_diff(wt_root, base_commit)
        save_attempt(
            root, goal.id, attempt, outcome.classification, outcome.reason,
            diff_stat, test_output, diff=diff,
        )
        break

    return False


def build_prompt(
    root: Path,
    config: Config,
    goal: Goal,
    attempts: list[AttemptLog] | None = None,
) -> str:
    # Use 'pack' format for structured XML context
    context = build_context(root, "pack", config.max_context_bytes, goal_override=goal)

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    filename_ts = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")

    instructions: list[str] = []
    
    # 1. Contract Enforcement (Tests)
    if goal.test_files:
        test_cmd = f"pytest {' '.join(shlex.quote(t) for t in goal.test_files)}"
        proc = subprocess.run(
            test_cmd,
            cwd=str(root),
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            instructions.append("CONTRACT VIOLATION (Tests Failed):")
            instructions.append("You must pass these tests defined in the goal contract.")
            instructions.append("======================================================")
            lines = proc.stdout.splitlines() + proc.stderr.splitlines()
            if len(lines) > 30:
                instructions.extend(lines[-30:])
            else:
                instructions.extend(lines)
            instructions.append("------------------------------------------------------")
            instructions.append("")

    # 2. Previous Failures
    if attempts:
        instructions.append("PREVIOUS FAILED ATTEMPTS (Do NOT repeat these mistakes):")
        instructions.append("======================================================")
        for att in attempts:
            instructions.append(f"Attempt {att.attempt} - Result: {att.classification}")
            if att.reason:
                instructions.append(f"Reason: {att.reason}")
            if att.diff:
                instructions.append("Changes made (DO NOT repeat the same approach):")
                instructions.append(att.diff)
            elif att.diff_stat:
                instructions.append("Diff Stat:")
                instructions.append(att.diff_stat)
            if att.test_output:
                instructions.append("Test output:")
                instructions.append(att.test_output)
            instructions.append("------------------------------------------------------")
        instructions.append("")

    # 3. Work Checklist
    checklist = [
        "Work completion checklist:",
        f"1. Run tests: {config.test_command}",
    ]
    
    # Extract suggested tests from XML context
    import re
    suggested_matches = re.findall(r"<test>(.*?)</test>", context)
    if suggested_matches:
        checklist.append("   (Note: These tests are impacted by your changes: " + 
                         ", ".join(suggested_matches) + ")")

    checklist.extend([
        f"2. Write handoff to .ai/handoffs/{filename_ts}.md (Include Passing Tests section)",
        f"3. Commit: {goal.id} - describe what you fixed",
    ])
    
    instructions.extend(checklist)

    if goal.expect_failure:
        instructions.append("This step is RED: tests are expected to fail.")
    if goal.prompt_mode == "adversarial":
        instructions.append("Be adversarial: break the code via edge cases.")

    return context + "\n\n---\n\n" + "\n".join(instructions)


def build_phase_prompt(
    root: Path,
    config: Config,
    goal: Goal,
    phase: str,
    attempts: list[AttemptLog] | None = None,
) -> str:
    """Build prompt using phase template if available, else fallback to build_prompt."""
    template = load_phase_template(root, phase)
    if template is None:
        return build_prompt(root, config, goal, attempts)

    context_pack = build_context(root, "pack", config.max_context_bytes, goal_override=goal)

    template_vars: dict[str, object] = {
        "goal": goal,
        "context_pack": context_pack,
        "attempts": attempts or [],
        "test_command": config.test_command,
        "timestamp": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # Phase-specific variables
    if phase == "plan":
        template_vars["capabilities_meta"] = _read_file_safe(root / ".ai" / "capabilities.yaml", max_lines=15)
        template_vars["recent_handoff"] = _read_latest_handoff_content(root)
        template_vars["unresolved_vulns"] = _read_unresolved_vulns(root)
        template_vars["current_goals_summary"] = _read_file_safe(root / ".ai" / "goals.yaml")

    if phase == "adversarial":
        template_vars["playbook"] = _read_file_safe(root / ".adversarial" / "playbook.yaml")
        template_vars["recent_diff"] = ""  # Will be populated in run_auto context

    return template.render(template_vars)


def _read_file_safe(path: Path, max_lines: int = 0) -> str:
    """Read a file, returning empty string if it doesn't exist."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if max_lines > 0:
        lines = text.splitlines()
        text = "\n".join(lines[:max_lines])
    return text


def _read_latest_handoff_content(root: Path) -> str:
    """Read the most recent handoff file content."""
    handoff_dir = root / ".ai" / "handoffs"
    if not handoff_dir.exists():
        return ""
    files = sorted(handoff_dir.glob("*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text(encoding="utf-8")


def _read_unresolved_vulns(root: Path) -> str:
    """Read unresolved vulnerability reports."""
    reports_dir = root / ".reports" / "adversarial"
    if not reports_dir.exists():
        return ""
    reports = sorted(reports_dir.glob("*.md"))
    if not reports:
        return ""
    lines = []
    for report in reports[-5:]:
        content = report.read_text(encoding="utf-8")
        lines.append(f"--- {report.name} ---")
        lines.extend(content.splitlines()[:5])
    return "\n".join(lines)


def evaluate_phase(
    root: Path,
    config: Config,
    goal: Goal,
    phase: str,
    base_commit: str,
) -> tuple[Outcome, str]:
    """Phase-aware evaluation. Gate phase uses mechanical checks."""
    if phase == "gate":
        gate_result = run_gate(root, config, goal, base_commit)
        return (
            Outcome(
                success=gate_result.passed,
                should_retry=not gate_result.passed,
                classification="gate-pass" if gate_result.passed else "gate-fail",
                reason=gate_result.summary if not gate_result.passed else None,
            ),
            gate_result.summary,
        )

    # plan, implement, adversarial — use standard evaluate
    return evaluate(root, config, goal, base_commit)


def evaluate(
    root: Path,
    config: Config,
    goal: Goal,
    base_commit: str,
) -> tuple[Outcome, str]:
    changed_files = get_changed_files(root, base_commit)
    has_changes = bool(changed_files)

    if goal.allowed_changes and has_changes:
        if not _changes_allowed(changed_files, goal.allowed_changes):
            return (
                Outcome(
                    success=False,
                    should_retry=True,
                    classification="failed",
                    reason="changes outside allowed scope",
                ),
                "",
            )

    if not has_changes:
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification="no-progress",
                reason="no file changes",
            ),
            "",
        )

    test_ok, test_output = _run_tests(root, config.test_command)

    if goal.expect_failure:
        if not test_ok:
            return (
                Outcome(
                    success=True,
                    should_retry=False,
                    classification="complete (expected failure)",
                ),
                test_output,
            )
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification="failed",
                reason="tests passed but failure expected",
            ),
            test_output,
        )

    if not test_ok:
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification="failed",
                reason="tests failed",
            ),
            test_output,
        )

    # Complexity guard: warn on threshold violations (does not fail)
    warnings = complexity_check(changed_files, root)
    for w in warnings:
        _log_warning(f"[complexity] {w}")

    return (
        Outcome(success=True, should_retry=False, classification="complete"),
        test_output,
    )


def _run_tests(root: Path, command: str) -> tuple[bool, str]:
    proc = subprocess.run(
        command, cwd=str(root), shell=True, check=False, capture_output=True, text=True,
    )
    output = proc.stdout
    if proc.stderr:
        output = output + "\n" + proc.stderr if output else proc.stderr
    return proc.returncode == 0, output


def _get_diff_stat(root: Path, base_commit: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "--stat", base_commit],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def _get_diff(root: Path, base_commit: str) -> str:
    proc = subprocess.run(
        ["git", "diff", base_commit],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def _changes_allowed(files: Iterable[str], patterns: Iterable[str]) -> bool:
    for path in files:
        if path.startswith(".ai/"):
            continue  # devf metadata always allowed
        if "__pycache__/" in path or path.endswith(".pyc"):
            continue  # compiled bytecode is never a real change
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            return False
    return True


def _lock_path(root: Path) -> Path:
    return root / ".ai" / "auto.lock"


def _acquire_lock(root: Path) -> None:
    lock_path = _lock_path(root)
    if lock_path.exists():
        lock_info = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        pid = lock_info.get("pid")
        base_commit = lock_info.get("base_commit")
        if isinstance(pid, int) and _pid_alive(pid):
            raise DevfError("devf auto is already running")
        if isinstance(base_commit, str) and is_dirty(root):
            try:
                reset_hard(root, base_commit)
            except Exception as exc:
                raise DevfError("failed to recover dirty state") from exc
        lock_path.unlink(missing_ok=True)

    if is_dirty(root):
        raise DevfError("working tree is dirty; commit or stash changes before devf auto")

    base_commit = get_head_commit(root)
    lock_info = {
        "pid": os.getpid(),
        "started_at": datetime.now().astimezone().isoformat(),
        "base_commit": base_commit,
    }
    lock_path.write_text(yaml.safe_dump(lock_info, sort_keys=False), encoding="utf-8")


def _release_lock(root: Path) -> None:
    lock_path = _lock_path(root)
    if lock_path.exists():
        try:
            lock_path.unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _log_warning(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _log_info(message: str) -> None:
    print(message, file=sys.stderr)