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

from devf.core.config import Config, load_config
from devf.core.context import build_context
from devf.core.errors import DevfError
from devf.core.goals import Goal, collect_goals, load_goals, update_goal_status
from devf.core.session import generate_session_log, write_session_log
from devf.utils.codetools import complexity_check
from devf.utils.git import (
    commit_all,
    get_changed_files,
    get_head_commit,
    is_dirty,
    reset_hard,
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
            print(build_prompt(root, config, goal))
        return 0

    _acquire_lock(root)
    try:
        has_failure = False

        for goal in selected:
            base_commit = get_head_commit(root)
            max_retries = config.max_retries

            for attempt in range(1, max_retries + 1):
                prompt = build_prompt(root, config, goal)

                run_ai(root, config, goal, tool_name, prompt)
                outcome, test_output = evaluate(root, config, goal, base_commit)

                if explain:
                    _log_info(
                        f"[{goal.id}] attempt={attempt} -> {outcome.classification}: "
                        f"{outcome.reason or ''}".strip()
                    )

                if outcome.success:
                    # Auto-commit any uncommitted work
                    if is_dirty(root):
                        commit_all(root, f"devf({goal.id}): {goal.title}")
                    # Generate and commit session log
                    log_content = generate_session_log(
                        root, goal, base_commit, test_output,
                    )
                    session_dir = root / ".ai" / "sessions"
                    write_session_log(session_dir, log_content)
                    if is_dirty(root):
                        commit_all(root, f"devf({goal.id}): session log")
                    update_goal_status(root / ".ai" / "goals.yaml", goal.id, "done")
                    break
                if outcome.should_retry:
                    reset_hard(root, base_commit)
                    continue

                update_goal_status(root / ".ai" / "goals.yaml", goal.id, "blocked")
                has_failure = True
                break
            else:
                update_goal_status(root / ".ai" / "goals.yaml", goal.id, "blocked")
                has_failure = True

        return 1 if has_failure else 0
    finally:
        _release_lock(root)


def build_prompt(root: Path, config: Config, goal: Goal) -> str:
    context = build_context(root, "plain", config.max_context_bytes, goal_override=goal)

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    filename_ts = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")

    instructions: list[str] = []
    if goal.acceptance:
        instructions.append("Acceptance criteria (ALL must be met):")
        for criterion in goal.acceptance:
            instructions.append(f"  - {criterion}")
        instructions.append("")
    if goal.notes:
        instructions.append(f"Design notes: {goal.notes}")
        instructions.append("")

    instructions.extend([
        "Work completion checklist:",
        f"1. Run: {config.test_command} (fix and rerun if failing, max 3 tries).",
        f"2. Write a handoff to .ai/handoffs/{filename_ts}.md using this template:",
        "",
        "---",
        f'timestamp: "{timestamp}"',
        "status: complete",
        f'goal_id: "{goal.id}"',
        "---",
        "",
        "## Done",
        "(summarize what you accomplished)",
        "",
        "## Key Decisions",
        "(design/implementation decisions and why)",
        "",
        "## Changed Files",
        "(paste output of `git diff --stat`)",
        "",
        "## Next",
        "(what the next session should work on)",
        "",
        "## Context Files",
        "(files the next session should read first)",
        "",
        "3. Commit: {type}({goal_id}): {description}",
    ])

    if goal.expect_failure:
        instructions.append("This step is RED: tests are expected to fail.")
    if goal.allowed_changes:
        allowed = ", ".join(goal.allowed_changes)
        instructions.append(f"Only modify these files: {allowed}")
    if goal.prompt_mode == "adversarial":
        instructions.append(
            "Be adversarial: craft tests that break the code via edge cases, concurrency, "
            "or resource exhaustion."
        )

    return context + "\n\n---\n\n" + "\n".join(instructions)


def run_ai(
    root: Path,
    config: Config,
    goal: Goal,
    tool_name: str | None,
    prompt: str,
) -> None:
    tool_command = resolve_tool_command(config, goal, tool_name)
    timeout = config.timeout_minutes * 60

    prompt_file_path: str | None = None
    command = tool_command
    if "{prompt_file}" in command:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=str(root / ".ai")
        ) as handle:
            handle.write(prompt)
            prompt_file_path = handle.name
        command = command.replace("{prompt_file}", shlex.quote(prompt_file_path))
    if "{prompt}" in command:
        command = command.replace("{prompt}", shlex.quote(prompt))

    try:
        subprocess.run(
            command,
            cwd=str(root),
            shell=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DevfError("AI tool timed out") from exc
    finally:
        if prompt_file_path:
            try:
                Path(prompt_file_path).unlink()
            except OSError:
                pass


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


def resolve_tool_command(config: Config, goal: Goal, tool_name: str | None) -> str:
    name = goal.tool or tool_name
    if name:
        if name not in config.ai_tools:
            raise DevfError(f"tool not found in config.ai_tools: {name}")
        return config.ai_tools[name]
    return config.ai_tool


def _run_tests(root: Path, command: str) -> tuple[bool, str]:
    proc = subprocess.run(
        command, cwd=str(root), shell=True, check=False, capture_output=True, text=True,
    )
    output = proc.stdout
    if proc.stderr:
        output = output + "\n" + proc.stderr if output else proc.stderr
    return proc.returncode == 0, output


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
