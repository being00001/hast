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
from devf.core.goals import Goal, collect_goals, load_goals, update_goal_status
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
            # dry-run doesn't load actual attempts since they might not exist
            print(build_prompt(root, config, goal, []))
        return 0

    # Use LocalRunner by default if none provided
    if runner is None:
        runner = LocalRunner()

    _acquire_lock(root)
    try:
        has_failure = False

        for goal in selected:
            # Create isolated worktree for this goal
            wt_root = worktree_create(root, goal.id)
            base_commit = get_head_commit(wt_root)
            max_retries = config.max_retries

            goal_ok = False
            for attempt in range(1, max_retries + 1):
                attempts_history = load_attempts(root, goal.id)
                prompt = build_prompt(wt_root, config, goal, attempts_history)

                # Execute via runner
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
                    # Auto-commit any uncommitted work in worktree
                    if is_dirty(wt_root):
                        commit_all(wt_root, f"devf({goal.id}): {goal.title}")
                    # Generate and commit session log
                    log_content = generate_session_log(
                        wt_root, goal, base_commit, test_output,
                    )
                    session_dir = wt_root / ".ai" / "sessions"
                    write_session_log(session_dir, log_content)
                    if is_dirty(wt_root):
                        commit_all(wt_root, f"devf({goal.id}): session log")
                    # Merge goal branch into main and clean up worktree
                    worktree_merge(root, goal.id)
                    update_goal_status(root / ".ai" / "goals.yaml", goal.id, "done")
                    clear_attempts(root, goal.id)
                    goal_ok = True
                    break
                if outcome.should_retry:
                    diff_stat = _get_diff_stat(wt_root, base_commit)
                    save_attempt(
                        root,
                        goal.id,
                        attempt,
                        outcome.classification,
                        outcome.reason,
                        diff_stat,
                        test_output,
                    )
                    reset_hard(wt_root, base_commit)
                    continue

                # Non-retryable failure
                # Save attempt even if we stop, so user can debug or next run sees it
                diff_stat = _get_diff_stat(wt_root, base_commit)
                save_attempt(
                    root,
                    goal.id,
                    attempt,
                    outcome.classification,
                    outcome.reason,
                    diff_stat,
                    test_output,
                )
                break

            if not goal_ok:
                worktree_remove(root, goal.id)
                update_goal_status(root / ".ai" / "goals.yaml", goal.id, "blocked")
                has_failure = True

        return 1 if has_failure else 0
    finally:
        _release_lock(root)


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
            instructions.append("Diff Stat:")
            instructions.append(att.diff_stat)
            # Show very concise test failure
            lines = att.test_output.splitlines()
            last_line = lines[-1] if lines else "No output"
            instructions.append(f"Last Error: {last_line}")
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


def _changes_allowed(files: Iterable[str], patterns: Iterable[str]) -> bool:
    for path in files:
        if path.startswith(".ai/"):
            continue  # devf metadata always allowed
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