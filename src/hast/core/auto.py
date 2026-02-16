"""Automation loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import fnmatch
import os
import re
import sys
from pathlib import Path
import shlex
import subprocess
import threading
from typing import Iterable

import yaml

from hast.core.auto_summary import build_auto_summary
from hast.core.attempt import (
    AttemptLog,
    clear_attempts,
    load_attempts,
    save_attempt,
)
from hast.core.config import Config, load_config
from hast.core.contract import (
    AcceptanceContract,
    contract_prompt_lines,
    load_acceptance_contract,
    validate_forbidden_patterns,
    validate_required_patterns,
)
from hast.core.decision import load_decision_ticket
from hast.core.doctor import (
    auto_preflight_blockers,
    format_auto_preflight_failure,
    run_doctor,
)
from hast.core.context import build_context
from hast.core.evidence import hash_text, new_run_id, write_evidence_row
from hast.core.errors import DevfError
from hast.core.feedback_infer import infer_and_store_feedback_notes
from hast.core.feedback_policy import load_feedback_policy
from hast.core.gate import run_gate
from hast.core.goals import (
    Goal,
    collect_goals,
    find_goal,
    load_goals,
    update_goal_fields,
    update_goal_status,
)
from hast.core.languages import (
    apply_pytest_reliability_flags,
    assertion_patterns as language_assertion_patterns,
    build_targeted_test_commands,
    collect_test_files,
    resolve_goal_languages,
    trivial_assertions as language_trivial_assertions,
)
from hast.core.immune_policy import evaluate_immune_changes
from hast.core.phase import load_phase_template, next_phase, parse_plan_output, regress_phase
from hast.core.policies import AutoPolicies, load_auto_policies
from hast.core.result import AutoResult, GoalResult
from hast.core.runner import GoalRunner, RunnerResult
from hast.core.retry_policy import (
    ADVANCE_ACTION,
    BLOCK_ACTION,
    RETRY_ACTION,
    decide_retry_action,
)
from hast.core.replan import InvalidationEvent, apply_post_goal_replan
from hast.core.risk_policy import compute_risk_score
from hast.core.runners.local import LocalRunner
from hast.core.runners.llm import LLMRunner
from hast.core.runners.protocol import ProtocolRunner
from hast.core.scheduler import build_execution_batches
from hast.core.session import generate_session_log, write_session_log
from hast.core.state_policy import decide_goal_state
from hast.core.triage import classify_failure
from hast.utils.codetools import complexity_check
from hast.utils.file_parser import parse_file_changes, apply_file_changes
from hast.utils.git import (
    commit_all,
    get_changed_files,
    get_head_commit,
    is_dirty,
    run_git,
    reset_hard,
    worktree_create,
    worktree_merge,
    worktree_remove,
)
from hast.core.protocol_adapters import SUPPORTED_PROTOCOL_ADAPTERS


@dataclass(frozen=True)
class Outcome:
    success: bool
    should_retry: bool
    classification: str
    reason: str | None = None


@dataclass(frozen=True)
class RedGateResult:
    passed: bool
    reason: str
    test_output: str = ""
    test_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyDecision:
    policy_version: str
    failure_classification: str | None
    action_taken: str
    risk_score: int


@dataclass(frozen=True)
class SecuritySignals:
    failed_checks: list[str] = field(default_factory=list)
    missing_tool_checks: list[str] = field(default_factory=list)
    ignored_checks: list[str] = field(default_factory=list)
    expired_ignore_rules: list[str] = field(default_factory=list)


_ROOT_LOCK = threading.RLock()


def _resolve_runner(
    config: Config,
    tool_name: str | None,
    runner: GoalRunner | None,
) -> GoalRunner:
    if runner is not None:
        return runner

    tool_token = tool_name.strip().lower() if isinstance(tool_name, str) and tool_name.strip() else None
    if tool_token in SUPPORTED_PROTOCOL_ADAPTERS:
        return ProtocolRunner()
    if config.roles.worker or config.roles.architect:
        return LLMRunner()
    return LocalRunner()


def run_auto(
    root: Path,
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    explain: bool,
    tool_name: str | None,
    dry_run_full: bool = False,
    runner: GoalRunner | None = None,
    parallelism: int = 1,
    preflight: bool = True,
    run_id: str | None = None,
) -> AutoResult:
    config, warnings = load_config(root=root)
    for warning in warnings:
        _log_warning(warning)

    goals = load_goals(root / ".ai" / "goals.yaml")
    selected = collect_goals(goals, goal_id, recursive)
    if not selected:
        raise DevfError("no active goals to run")
    batches = build_execution_batches(goals, selected)

    # dry-run: summary by default; optional full prompt dump; no lock/dirty checks.
    if dry_run:
        if dry_run_full:
            for goal in selected:
                if goal.spec_file:
                     print(f"BDD Mode: {goal.spec_file}")
                elif goal.phase:
                    print(build_phase_prompt(root, config, goal, goal.phase, []))
                else:
                    print(build_prompt(root, config, goal, []))
        else:
            print(_build_dry_run_summary(config, selected))
        return AutoResult(exit_code=0, run_id=run_id or "dry-run")

    if preflight:
        report = run_doctor(root)
        blockers = auto_preflight_blockers(report)
        if blockers:
            raise DevfError(format_auto_preflight_failure(blockers))

    # Select runner
    # If explicit runner provided (e.g. from test), use it.
    # Otherwise resolve by tool route (protocol > llm > local).
    runner = _resolve_runner(config, tool_name, runner)

    if run_id is None:
        run_id = new_run_id()
    policies = load_auto_policies(root)
    feedback_policy = load_feedback_policy(root)
    worker_count = max(1, parallelism)

    _acquire_lock(root)
    exit_code = 0
    try:
        has_failure = False
        cycle_count = 0
        no_progress_count = 0
        root_lock = _ROOT_LOCK
        stop_session = False

        for batch in batches:
            if stop_session:
                break

            for chunk in _chunked(batch, worker_count):
                prepared: list[tuple[Goal, Path, str]] = []
                for goal in chunk:
                    cycle_count += 1
                    if cycle_count > config.circuit_breakers.max_cycles_per_session:
                        _log_warning("Circuit breaker: max cycles per session reached")
                        stop_session = True
                        break
                    with root_lock:
                        wt_root = worktree_create(root, goal.id)
                    base_commit = get_head_commit(wt_root)
                    prepared.append((goal, wt_root, base_commit))

                if not prepared:
                    continue

                results: list[tuple[Goal, bool, str | None]] = []
                if len(prepared) == 1:
                    goal, wt_root, base_commit = prepared[0]
                    ok, phase = _execute_goal_once(
                        wt_root,
                        root,
                        config,
                        goal,
                        runner,
                        tool_name,
                        explain,
                        base_commit,
                        run_id,
                        policies,
                        root_lock,
                    )
                    results.append((goal, ok, phase))
                else:
                    with ThreadPoolExecutor(max_workers=min(worker_count, len(prepared))) as executor:
                        future_map = {
                            executor.submit(
                                _execute_goal_once,
                                wt_root,
                                root,
                                config,
                                goal,
                                runner,
                                tool_name,
                                explain,
                                base_commit,
                                run_id,
                                policies,
                                root_lock,
                            ): goal
                            for goal, wt_root, base_commit in prepared
                        }
                        for future in as_completed(future_map):
                            goal = future_map[future]
                            ok, phase = future.result()
                            results.append((goal, ok, phase))

                goals_path = root / ".ai" / "goals.yaml"
                for goal, goal_ok, phase in results:
                    if not goal_ok:
                        no_progress_count += 1
                        _safe_worktree_remove(root, goal.id, root_lock)
                        if phase is None or phase == "gate":
                            _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
                        has_failure = True
                    else:
                        no_progress_count = 0

                if no_progress_count >= config.circuit_breakers.max_consecutive_no_progress:
                    _log_warning("Circuit breaker: max consecutive no-progress reached")
                    stop_session = True
                    break

        exit_code = 1 if has_failure else 0
    finally:
        _release_lock(root)

    if feedback_policy.enabled:
        try:
            infer_and_store_feedback_notes(root, run_id, feedback_policy)
        except Exception as exc:  # pragma: no cover
            _log_warning(f"failed to infer feedback notes: {exc}")

    summary = build_auto_summary(root, run_id, exit_code)
    return AutoResult(
        exit_code=exit_code,
        run_id=run_id,
        goals=[
            GoalResult(
                id=g["id"],
                success=g.get("success", False),
                classification=g.get("classification"),
                phase=g.get("phase"),
                action_taken=g.get("action_taken"),
                risk_score=g.get("risk_score"),
            )
            for g in summary.get("goals_processed", [])
        ],
        changed_files=summary.get("changed_files", []),
        evidence_summary=summary.get("evidence_summary", {}),
        errors=[],
    )


def _execute_goal_once(
    wt_root: Path,
    root: Path,
    config: Config,
    goal: Goal,
    runner: GoalRunner,
    tool_name: str | None,
    explain: bool,
    base_commit: str,
    run_id: str,
    policies: AutoPolicies,
    root_lock: threading.RLock,
) -> tuple[bool, str | None]:
    goals_path = root / ".ai" / "goals.yaml"
    phase = goal.phase
    goal_ok = False

    decision_ready, decision_reason = _validate_goal_decision_prerequisites(root, goal)
    if not decision_ready:
        reason = decision_reason or "decision prerequisites not satisfied"
        outcome = Outcome(
            success=False,
            should_retry=False,
            classification="decision-pending",
            reason=reason,
        )
        outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            phase,
            1,
            outcome,
            reason,
            wt_root,
            base_commit,
            config.max_retries,
            policies,
        )
        _record_evidence(
            root,
            run_id,
            goal.id,
            phase,
            1,
            outcome,
            wt_root,
            base_commit,
            reason,
            policy_decision=policy_decision,
        )
        _emit_failure_assist(
            goal=goal,
            phase=phase,
            attempt=1,
            max_retries=1,
            outcome=outcome,
            test_output=reason,
        )
        _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
        return False, phase

    if goal.spec_file:
        goal_ok = _run_bdd_goal(
            wt_root, root, config, goal, config.max_retries,
            runner, tool_name, explain, base_commit, run_id, policies, root_lock,
        )
    elif phase is None:
        goal_ok = _run_legacy_goal(
            wt_root, root, config, goal, config.max_retries,
            runner, tool_name, explain, base_commit, run_id, policies, root_lock,
        )
    elif phase == "gate":
        outcome, gate_output = evaluate_phase(wt_root, config, goal, "gate", base_commit)
        outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "gate",
            1,
            outcome,
            gate_output,
            wt_root,
            base_commit,
            config.max_retries,
            policies,
        )
        _record_evidence(
            root, run_id, goal.id, "gate", 1, outcome, wt_root, base_commit, gate_output,
            policy_decision=policy_decision,
        )
        if outcome.success:
            nxt = next_phase("gate", phases=goal.phases)
            if nxt == "merge":
                goal_ok = _merge_goal_with_controls(
                    root=root,
                    wt_root=wt_root,
                    config=config,
                    goal=goal,
                    run_id=run_id,
                    attempt=1,
                    base_commit=base_commit,
                    policies=policies,
                    root_lock=root_lock,
                )
                if not goal_ok:
                    return False, phase
            else:
                _safe_update_goal_fields(goals_path, goal.id, {"phase": nxt}, root_lock)
            goal_ok = True
        else:
            _safe_update_goal_fields(goals_path, goal.id, {"phase": regress_phase("gate")}, root_lock)
            goal_ok = False
    elif phase == "merge":
        goal_ok = _merge_goal_with_controls(
            root=root,
            wt_root=wt_root,
            config=config,
            goal=goal,
            run_id=run_id,
            attempt=1,
            base_commit=base_commit,
            policies=policies,
            root_lock=root_lock,
        )
    else:
        goal_ok = _run_phased_goal(
            wt_root, root, config, goal, phase, config.max_retries,
            runner, tool_name, explain, base_commit, run_id, policies, root_lock,
        )

    return goal_ok, phase


def _chunked(goals: list[Goal], size: int) -> list[list[Goal]]:
    chunks: list[list[Goal]] = []
    for i in range(0, len(goals), size):
        chunks.append(goals[i:i + size])
    return chunks


def _build_dry_run_summary(config: Config, selected: list[Goal]) -> str:
    lines = [
        "hast auto dry-run summary",
        f"selected_goals: {len(selected)}",
        f"test_command: {config.test_command}",
        "mode: summary (use --dry-run-full for full prompts)",
        "",
    ]
    for idx, goal in enumerate(selected, start=1):
        phase = goal.phase or ("bdd" if goal.spec_file else "legacy")
        lines.append(f"{idx}. {goal.id} phase={phase} status={goal.status}")
        lines.append(f"   title: {goal.title}")
        if goal.allowed_changes:
            preview = ", ".join(goal.allowed_changes[:3])
            if len(goal.allowed_changes) > 3:
                preview += ", ..."
            lines.append(f"   allowed_changes: {preview}")
        if goal.test_files:
            preview = ", ".join(goal.test_files[:3])
            if len(goal.test_files) > 3:
                preview += ", ..."
            lines.append(f"   test_files: {preview}")
    return "\n".join(lines)


def _safe_update_goal_status(path: Path, goal_id: str, status: str, lock: threading.RLock) -> None:
    with lock:
        update_goal_status(path, goal_id, status)


def _safe_update_goal_fields(
    path: Path, goal_id: str, fields: dict[str, object], lock: threading.RLock,
) -> None:
    with lock:
        update_goal_fields(path, goal_id, fields)


def _safe_worktree_merge(root: Path, goal_id: str, lock: threading.RLock) -> None:
    with lock:
        worktree_merge(root, goal_id)


def _safe_worktree_remove(root: Path, goal_id: str, lock: threading.RLock) -> None:
    with lock:
        worktree_remove(root, goal_id)


def _safe_apply_post_goal_replan(
    root: Path,
    completed_goal_id: str,
    lock: threading.RLock,
) -> list[InvalidationEvent]:
    with lock:
        return apply_post_goal_replan(root, completed_goal_id)


def _merge_goal_with_controls(
    root: Path,
    wt_root: Path,
    config: Config,
    goal: Goal,
    run_id: str,
    attempt: int,
    base_commit: str,
    policies: AutoPolicies,
    root_lock: threading.RLock,
    runner_result: RunnerResult | None = None,
) -> bool:
    goals_path = root / ".ai" / "goals.yaml"
    changed_files = get_changed_files(wt_root, base_commit)
    merge_decision = _success_policy_decision(policies, "merge", changed_files)

    if merge_decision.risk_score >= policies.risk.block_threshold:
        _record_evidence(
            root,
            run_id,
            goal.id,
            "merge",
            attempt,
            Outcome(
                success=False,
                should_retry=False,
                classification="risk-blocked",
                reason=(
                    f"risk_score {merge_decision.risk_score} >= "
                    f"block_threshold {policies.risk.block_threshold}"
                ),
            ),
            wt_root,
            base_commit,
            "",
            policy_decision=PolicyDecision(
                policy_version=policies.version,
                failure_classification="risk-threshold",
                action_taken=BLOCK_ACTION,
                risk_score=merge_decision.risk_score,
            ),
            runner_result=runner_result,
        )
        _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
        _safe_update_goal_fields(goals_path, goal.id, {"state": "review_ready"}, root_lock)
        return False

    pre_merge_cmd = (config.merge_train.pre_merge_command or config.test_command).strip()
    pre_merge_ok, pre_merge_output = _run_tests(wt_root, pre_merge_cmd, config)
    if not pre_merge_ok:
        _record_evidence(
            root,
            run_id,
            goal.id,
            "merge-train",
            attempt,
            Outcome(
                success=False,
                should_retry=False,
                classification="merge-train-fail",
                reason=f"pre-merge command failed: {pre_merge_cmd}",
            ),
            wt_root,
            base_commit,
            pre_merge_output,
            policy_decision=PolicyDecision(
                policy_version=policies.version,
                failure_classification=classify_failure("failed", "pre-merge command failed", pre_merge_output),
                action_taken=BLOCK_ACTION,
                risk_score=merge_decision.risk_score,
            ),
            runner_result=runner_result,
        )
        _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
        _safe_update_goal_fields(goals_path, goal.id, {"state": "review_ready"}, root_lock)
        return False

    if is_dirty(wt_root):
        commit_all(wt_root, f"hast({goal.id}): pre-merge")

    _record_evidence(
        root,
        run_id,
        goal.id,
        "merge",
        attempt,
        Outcome(success=True, should_retry=False, classification="merged"),
        wt_root,
        base_commit,
        "",
        policy_decision=merge_decision,
        runner_result=runner_result,
    )

    try:
        _safe_worktree_merge(root, goal.id, root_lock)
    except DevfError as exc:
        _record_evidence(
            root,
            run_id,
            goal.id,
            "merge",
            attempt,
            Outcome(
                success=False,
                should_retry=False,
                classification="merge-fail",
                reason=str(exc),
            ),
            wt_root,
            base_commit,
            "",
            policy_decision=PolicyDecision(
                policy_version=policies.version,
                failure_classification="dep-build",
                action_taken=BLOCK_ACTION,
                risk_score=merge_decision.risk_score,
            ),
        )
        _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
        _safe_update_goal_fields(goals_path, goal.id, {"state": "review_ready"}, root_lock)
        return False

    post_merge_cmd = (config.merge_train.post_merge_command or "").strip()
    if post_merge_cmd:
        post_ok, post_output = _run_tests(root, post_merge_cmd, config)
        if not post_ok:
            failure_class = classify_failure("failed", "post-merge command failed", post_output)
            if (
                config.merge_train.auto_rollback
                and merge_decision.risk_score >= policies.risk.rollback_threshold
            ):
                rollback_ok = True
                rollback_reason: str | None = None
                try:
                    run_git(["revert", "--no-edit", "-m", "1", "HEAD"], root)
                except DevfError as exc:
                    rollback_ok = False
                    rollback_reason = str(exc)

                action = "rollback" if rollback_ok else BLOCK_ACTION
                classification = (
                    "post-merge-fail-rolled-back"
                    if rollback_ok else "post-merge-fail-rollback-failed"
                )
                reason = f"post-merge command failed: {post_merge_cmd}"
                if rollback_reason:
                    reason += f"; rollback failed: {rollback_reason}"
                _record_evidence(
                    root,
                    run_id,
                    goal.id,
                    "rollback",
                    attempt,
                    Outcome(
                        success=False,
                        should_retry=False,
                        classification=classification,
                        reason=reason,
                    ),
                    root,
                    base_commit,
                    post_output,
                    policy_decision=PolicyDecision(
                        policy_version=policies.version,
                        failure_classification=failure_class,
                        action_taken=action,
                        risk_score=merge_decision.risk_score,
                    ),
                )
            else:
                _record_evidence(
                    root,
                    run_id,
                    goal.id,
                    "merge-train",
                    attempt,
                    Outcome(
                        success=False,
                        should_retry=False,
                        classification="post-merge-fail",
                        reason=f"post-merge command failed: {post_merge_cmd}",
                    ),
                    root,
                    base_commit,
                    post_output,
                    policy_decision=PolicyDecision(
                        policy_version=policies.version,
                        failure_classification=failure_class,
                        action_taken=BLOCK_ACTION,
                        risk_score=merge_decision.risk_score,
                    ),
                )

            _safe_update_goal_status(goals_path, goal.id, "blocked", root_lock)
            _safe_update_goal_fields(goals_path, goal.id, {"state": "review_ready"}, root_lock)
            return False

    _safe_update_goal_status(goals_path, goal.id, "done", root_lock)
    _safe_update_goal_fields(goals_path, goal.id, {"state": "merged"}, root_lock)
    clear_attempts(root, goal.id)

    invalidation_events = _safe_apply_post_goal_replan(root, goal.id, root_lock)
    for event in invalidation_events:
        _record_goal_invalidation_evidence(root, run_id, event)

    return True


def _run_bdd_goal(
    wt_root: Path,
    root: Path,
    config: Config,
    goal: Goal,
    max_retries: int,
    runner: GoalRunner,
    tool_name: str | None,
    explain: bool,
    base_commit: str,
    run_id: str,
    policies: AutoPolicies,
    root_lock: threading.RLock,
) -> bool:
    """Execute BDD workflow: Spec -> Test Gen (RED) -> Implement (GREEN)."""
    spec_path = wt_root / str(goal.spec_file)
    if not spec_path.exists():
        _log_warning(f"Spec file not found: {goal.spec_file}")
        return False

    spec_content = spec_path.read_text(encoding="utf-8")
    contract, contract_error = _load_goal_contract(wt_root, goal)
    if contract_error:
        _log_warning(contract_error)
        failed_outcome = Outcome(
            success=False,
            should_retry=False,
            classification="contract-invalid",
            reason=contract_error,
        )
        failed_outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            "",
            wt_root,
            base_commit,
            max_retries,
            policies,
        )
        _record_evidence(
            root,
            run_id,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            wt_root,
            base_commit,
            "",
            policy_decision=policy_decision,
        )
        save_attempt(
            root, goal.id, 0, "contract-invalid", contract_error,
            _get_diff_stat(wt_root, base_commit), "", diff=_get_diff(wt_root, base_commit),
        )
        return False

    contract_text = ""
    if contract:
        contract_lines = contract_prompt_lines(contract)
        contract_lines.append("Never modify the contract file during execution.")
        if goal.contract_file:
            contract_lines.append(f"Contract file: {goal.contract_file}")
        contract_text = "\n".join(contract_lines)
    goal_languages = resolve_goal_languages(wt_root, goal, config)
    if goal_languages == ["rust"]:
        red_task = (
            "Generate Rust tests for the feature. Prefer integration tests under tests/*.rs "
            "and keep source implementation unchanged in RED stage."
        )
        red_instruction_1 = (
            f"1. Create Rust test files (e.g. tests/{goal.id.lower()}_feature.rs) "
            "covering the scenarios."
        )
    else:
        red_task = "Generate pytest-bdd step definitions for the following feature file."
        red_instruction_1 = (
            f"1. Create a python test file (e.g. tests/step_defs/test_{goal.id}.py) "
            "using pytest-bdd scenarios."
        )

    prompt_gen_tests = f"""
    GOAL: {goal.title}
    TASK: {red_task}

    FEATURE FILE ({goal.spec_file}):
    {spec_content}

    INSTRUCTIONS:
    {red_instruction_1}
    2. Do NOT implement the logic in src/ yet.
    3. Ensure the tests fail (RED state) or simply raise NotImplementedError.
    4. Output the file content in markdown code block with filename.

    {contract_text}
    """

    test_tool_name = tool_name or ("tester" if config.roles.tester else "worker")
    result_tests = runner.run(wt_root, config, goal, prompt_gen_tests, tool_name=test_tool_name)
    if not result_tests.success and result_tests.error_message:
        _log_warning(f"Runner error (RED stage): {result_tests.error_message}")

    if result_tests.success and result_tests.output:
        changes = parse_file_changes(result_tests.output)
        if changes:
            ok, reason = _validate_planned_changes(
                root,
                goal,
                changes,
                stage="bdd-red",
                contract_file=goal.contract_file,
                attempt=0,
            )
            if not ok:
                _log_warning(f"Apply blocked (RED stage): {reason}")
                failed_outcome = Outcome(
                    success=False,
                    should_retry=False,
                    classification="phase-violation",
                    reason=reason,
                )
                failed_outcome, policy_decision = _apply_policy_decision(
                    root,
                    goal.id,
                    "bdd-red",
                    0,
                    failed_outcome,
                    "",
                    wt_root,
                    base_commit,
                    max_retries,
                    policies,
                )
                _record_evidence(
                    root,
                    run_id,
                    goal.id,
                    "bdd-red",
                    0,
                    failed_outcome,
                    wt_root,
                    base_commit,
                    "",
                    policy_decision=policy_decision,
                    runner_result=result_tests,
                )
                return False
            applied = apply_file_changes(wt_root, changes)
            if explain:
                _log_info(f"Generated tests: {applied}")

    red_changed_files = get_changed_files(wt_root, base_commit)
    immune_check = evaluate_immune_changes(
        root,
        red_changed_files,
        metadata={
            "goal_id": goal.id,
            "phase": "bdd-red",
            "attempt": 0,
            "check": "applied",
        },
    )
    if not immune_check.allowed:
        failed_outcome = Outcome(
            success=False,
            should_retry=False,
            classification="immune-blocked",
            reason=immune_check.reason,
        )
        failed_outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            "",
            wt_root,
            base_commit,
            max_retries,
            policies,
        )
        _record_evidence(
            root,
            run_id,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            wt_root,
            base_commit,
            "",
            policy_decision=policy_decision,
        )
        return False

    red_gate = _verify_bdd_red_stage(
        wt_root,
        base_commit,
        goal.contract_file,
        contract,
        config=config,
        languages=goal_languages,
    )
    if not red_gate.passed:
        _log_warning(f"RED gate failed: {red_gate.reason}")
        failed_outcome = Outcome(
            success=False,
            should_retry=False,
            classification="red-gate-fail",
            reason=red_gate.reason,
        )
        failed_outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            red_gate.test_output,
            wt_root,
            base_commit,
            max_retries,
            policies,
        )
        _record_evidence(
            root,
            run_id,
            goal.id,
            "bdd-red",
            0,
            failed_outcome,
            wt_root,
            base_commit,
            red_gate.test_output,
            policy_decision=policy_decision,
            runner_result=result_tests,
        )
        save_attempt(
            root, goal.id, 0, "red-gate-fail", red_gate.reason,
            _get_diff_stat(wt_root, base_commit), red_gate.test_output,
            diff=_get_diff(wt_root, base_commit),
        )
        return False

    if is_dirty(wt_root):
        commit_all(wt_root, f"hast({goal.id}): red baseline")
    red_base_commit = get_head_commit(wt_root)
    test_output = red_gate.test_output

    if explain:
        _log_info("RED gate passed: failing tests verified.")

    for attempt in range(1, max_retries + 1):
        context = build_context(wt_root, "pack", config.max_context_bytes, goal_override=goal)
        prompt_impl = f"""
        {context}

        GOAL: {goal.title}
        TASK: Implement the logic in src/ to pass the tests.

        FEATURE FILE: {spec_content}

        CURRENT TEST OUTPUT (FAILURES):
        {test_output}

        INSTRUCTIONS:
        1. Modify source code in src/ to satisfy the BDD scenarios.
        2. Do NOT modify the feature file or step definitions (unless they are buggy).
        3. Output changed files in markdown code blocks.
        4. Never modify the contract file.

        {contract_text}
        """

        impl_tool_name = tool_name or "worker"
        result_impl = runner.run(wt_root, config, goal, prompt_impl, tool_name=impl_tool_name)
        if not result_impl.success and result_impl.error_message:
            _log_warning(f"Runner error (GREEN stage): {result_impl.error_message}")

        if result_impl.success and result_impl.output:
            changes = parse_file_changes(result_impl.output)
            if changes:
                ok, reason = _validate_planned_changes(
                    root,
                    goal,
                    changes,
                    stage="bdd-green",
                    contract_file=goal.contract_file,
                    attempt=attempt,
                )
                if not ok:
                    immune_blocked = bool(reason and reason.startswith("immune policy violation"))
                    outcome = Outcome(
                        success=False,
                        should_retry=not immune_blocked,
                        classification="immune-blocked" if immune_blocked else "phase-violation",
                        reason=reason,
                    )
                    test_output = ""
                    outcome, policy_decision = _apply_policy_decision(
                        root,
                        goal.id,
                        "bdd-green",
                        attempt,
                        outcome,
                        test_output,
                        wt_root,
                        red_base_commit,
                        max_retries,
                        policies,
                    )
                    _record_evidence(
                        root,
                        run_id,
                        goal.id,
                        "bdd-green",
                        attempt,
                        outcome,
                        wt_root,
                        red_base_commit,
                        test_output,
                        policy_decision=policy_decision,
                        runner_result=result_impl,
                    )
                    if outcome.should_retry:
                        save_attempt(
                            root, goal.id, attempt, outcome.classification, outcome.reason,
                            _get_diff_stat(wt_root, red_base_commit), "",
                            diff=_get_diff(wt_root, red_base_commit),
                        )
                        reset_hard(wt_root, red_base_commit)
                        continue
                    return False
                apply_file_changes(wt_root, changes)

        changed_files = get_changed_files(wt_root, red_base_commit)
        immune_check = evaluate_immune_changes(
            root,
            changed_files,
            metadata={
                "goal_id": goal.id,
                "phase": "bdd-green",
                "attempt": attempt,
                "check": "applied",
            },
        )
        if not immune_check.allowed:
            outcome = Outcome(
                success=False,
                should_retry=False,
                classification="immune-blocked",
                reason=immune_check.reason,
            )
            test_output = ""
        else:
            scope_ok, scope_reason = _validate_bdd_impl_scope(changed_files, goal.contract_file)
            if not scope_ok:
                outcome = Outcome(
                    success=False,
                    should_retry=True,
                    classification="phase-violation",
                    reason=scope_reason,
                )
                test_output = ""
            else:
                if contract:
                    change_ok, change_reason = _validate_contract_change_rules(
                        changed_files, contract, goal.contract_file,
                    )
                    if not change_ok:
                        outcome = Outcome(
                            success=False,
                            should_retry=True,
                            classification="contract-violation",
                            reason=change_reason,
                        )
                        test_output = ""
                        if explain:
                            _log_info(f"Attempt {attempt}: {outcome.classification}")
                        diff_stat = _get_diff_stat(wt_root, red_base_commit)
                        diff = _get_diff(wt_root, red_base_commit)
                        save_attempt(
                            root, goal.id, attempt, outcome.classification, outcome.reason,
                            diff_stat, test_output, diff=diff,
                        )
                        reset_hard(wt_root, red_base_commit)
                        continue

                test_ok, test_output = _run_tests(wt_root, config.test_command, config)
                if test_ok:
                    pass_ok, pass_output, pass_reason = _run_contract_pass_tests(
                        wt_root,
                        contract,
                        config=config,
                        languages=goal_languages,
                    )
                    if not pass_ok:
                        outcome = Outcome(
                            success=False,
                            should_retry=True,
                            classification="contract-violation",
                            reason=pass_reason,
                        )
                        test_output = pass_output
                    else:
                        outcome = Outcome(
                            success=True,
                            should_retry=False,
                            classification="complete",
                            reason="tests passed",
                        )
                else:
                    triage_class, triage_reason = _triage_test_failure(test_output)
                    outcome = Outcome(
                        success=False,
                        should_retry=True,
                        classification=triage_class,
                        reason=triage_reason,
                    )

        if explain:
            _log_info(f"Attempt {attempt}: {outcome.classification}")

        outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "bdd-green",
            attempt,
            outcome,
            test_output,
            wt_root,
            red_base_commit,
            max_retries,
            policies,
        )

        _record_evidence(
            root,
            run_id,
            goal.id,
            "bdd-green",
            attempt,
            outcome,
            wt_root,
            red_base_commit,
            test_output,
            policy_decision=policy_decision,
            runner_result=result_impl,
        )

        if outcome.success:
            merged = _merge_goal_with_controls(
                root=root,
                wt_root=wt_root,
                config=config,
                goal=goal,
                run_id=run_id,
                attempt=attempt,
                base_commit=red_base_commit,
                policies=policies,
                root_lock=root_lock,
                runner_result=result_impl,
            )
            if merged:
                return True
            return False

        if outcome.should_retry:
            diff_stat = _get_diff_stat(wt_root, red_base_commit)
            diff = _get_diff(wt_root, red_base_commit)
            save_attempt(
                root, goal.id, attempt, outcome.classification, outcome.reason,
                diff_stat, test_output, diff=diff,
            )
            reset_hard(wt_root, red_base_commit)
            continue

        break

    return False

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
    run_id: str,
    policies: AutoPolicies,
    root_lock: threading.RLock,
) -> bool:
    """Execute a goal without phase awareness (legacy behavior)."""
    for attempt in range(1, max_retries + 1):
        attempts_history = load_attempts(root, goal.id)
        prompt = build_prompt(wt_root, config, goal, attempts_history)

        result = runner.run(wt_root, config, goal, prompt, tool_name)
        
        # If LLMRunner, parse changes
        if isinstance(runner, LLMRunner) and result.success and result.output:
             changes = parse_file_changes(result.output)
             if changes:
                 ok, reason = _validate_planned_changes(
                     root,
                     goal,
                     changes,
                     stage="legacy",
                     attempt=attempt,
                 )
                 if not ok:
                     immune_blocked = bool(reason and reason.startswith("immune policy violation"))
                     outcome = Outcome(
                         success=False,
                         should_retry=not immune_blocked,
                         classification="immune-blocked" if immune_blocked else "phase-violation",
                         reason=reason,
                     )
                     test_output = ""
                     outcome, policy_decision = _apply_policy_decision(
                         root,
                         goal.id,
                         "legacy",
                         attempt,
                         outcome,
                         test_output,
                         wt_root,
                         base_commit,
                         max_retries,
                         policies,
                     )
                     _record_evidence(
                         root,
                         run_id,
                         goal.id,
                         "legacy",
                         attempt,
                         outcome,
                         wt_root,
                         base_commit,
                         test_output,
                         policy_decision=policy_decision,
                         runner_result=result,
                     )
                     if outcome.should_retry:
                         save_attempt(
                             root, goal.id, attempt, outcome.classification, outcome.reason,
                             _get_diff_stat(wt_root, base_commit), "",
                             diff=_get_diff(wt_root, base_commit),
                         )
                         reset_hard(wt_root, base_commit)
                         continue
                     return False
                 apply_file_changes(wt_root, changes)

        if not result.success and result.error_message:
            _log_warning(f"Runner error: {result.error_message}")

        outcome, test_output = evaluate(wt_root, config, goal, base_commit, policy_root=root)

        if explain:
            _log_info(
                f"[{goal.id}] attempt={attempt} -> {outcome.classification}: "
                f"{outcome.reason or ''}".strip()
            )

        outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            "legacy",
            attempt,
            outcome,
            test_output,
            wt_root,
            base_commit,
            max_retries,
            policies,
        )

        _record_evidence(
            root,
            run_id,
            goal.id,
            "legacy",
            attempt,
            outcome,
            wt_root,
            base_commit,
            test_output,
            policy_decision=policy_decision,
            runner_result=result,
        )
        _emit_failure_assist(
            goal=goal,
            phase="legacy",
            attempt=attempt,
            max_retries=max_retries,
            outcome=outcome,
            test_output=test_output,
        )

        if outcome.success:
            return _merge_goal_with_controls(
                root=root,
                wt_root=wt_root,
                config=config,
                goal=goal,
                run_id=run_id,
                attempt=attempt,
                base_commit=base_commit,
                policies=policies,
                root_lock=root_lock,
                runner_result=result,
            )

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
    run_id: str,
    policies: AutoPolicies,
    root_lock: threading.RLock,
) -> bool:
    """Execute a goal with phase awareness."""
    goals_path = root / ".ai" / "goals.yaml"

    for attempt in range(1, max_retries + 1):
        attempts_history = load_attempts(root, goal.id)
        prompt = build_phase_prompt(wt_root, config, goal, phase, attempts_history)

        result = runner.run(wt_root, config, goal, prompt, tool_name)
        
        # If LLMRunner, parse changes
        if isinstance(runner, LLMRunner) and result.success and result.output:
             changes = parse_file_changes(result.output)
             if changes:
                 ok, reason = _validate_planned_changes(
                     root,
                     goal,
                     changes,
                     stage=phase,
                     attempt=attempt,
                 )
                 if not ok:
                     immune_blocked = bool(reason and reason.startswith("immune policy violation"))
                     outcome = Outcome(
                         success=False,
                         should_retry=not immune_blocked,
                         classification="immune-blocked" if immune_blocked else "phase-violation",
                         reason=reason,
                     )
                     test_output = ""
                     outcome, policy_decision = _apply_policy_decision(
                         root,
                         goal.id,
                         phase,
                         attempt,
                         outcome,
                         test_output,
                         wt_root,
                         base_commit,
                         max_retries,
                         policies,
                     )
                     _record_evidence(
                         root,
                         run_id,
                         goal.id,
                         phase,
                         attempt,
                         outcome,
                         wt_root,
                         base_commit,
                         test_output,
                         policy_decision=policy_decision,
                         runner_result=result,
                     )
                     if outcome.should_retry:
                         save_attempt(
                             root, goal.id, attempt, outcome.classification, outcome.reason,
                             _get_diff_stat(wt_root, base_commit), "",
                             diff=_get_diff(wt_root, base_commit),
                         )
                         reset_hard(wt_root, base_commit)
                         continue
                     return False
                 apply_file_changes(wt_root, changes)
        
        if not result.success and result.error_message:
            _log_warning(f"Runner error: {result.error_message}")

        outcome, test_output = evaluate_phase(
            wt_root,
            config,
            goal,
            phase,
            base_commit,
            policy_root=root,
        )

        if explain:
            _log_info(
                f"[{goal.id}] phase={phase} attempt={attempt} -> {outcome.classification}: "
                f"{outcome.reason or ''}".strip()
            )

        outcome, policy_decision = _apply_policy_decision(
            root,
            goal.id,
            phase,
            attempt,
            outcome,
            test_output,
            wt_root,
            base_commit,
            max_retries,
            policies,
        )

        _record_evidence(
            root,
            run_id,
            goal.id,
            phase,
            attempt,
            outcome,
            wt_root,
            base_commit,
            test_output,
            policy_decision=policy_decision,
            runner_result=result,
        )
        _emit_failure_assist(
            goal=goal,
            phase=phase,
            attempt=attempt,
            max_retries=max_retries,
            outcome=outcome,
            test_output=test_output,
        )

        if outcome.success:
            # Handle plan phase output parsing
            if phase == "plan" and result.output:
                parsed = parse_plan_output(result.output)
                if parsed:
                    _safe_update_goal_fields(goals_path, goal.id, parsed, root_lock)

            if is_dirty(wt_root):
                commit_all(wt_root, f"hast({goal.id}): {phase}")

            # Generate session log
            log_content = generate_session_log(wt_root, goal, base_commit, test_output)
            session_dir = wt_root / ".ai" / "sessions"
            write_session_log(session_dir, log_content, suffix=goal.id)
            if is_dirty(wt_root):
                commit_all(wt_root, f"hast({goal.id}): {phase} session log")

            # Advance to next phase
            nxt = next_phase(phase, phases=goal.phases)
            if nxt == "merge":
                return _merge_goal_with_controls(
                    root=root,
                    wt_root=wt_root,
                    config=config,
                    goal=goal,
                    run_id=run_id,
                    attempt=attempt,
                    base_commit=base_commit,
                    policies=policies,
                    root_lock=root_lock,
                    runner_result=result,
                )
            elif nxt is not None:
                _safe_update_goal_fields(goals_path, goal.id, {"phase": nxt}, root_lock)
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


def _emit_failure_assist(
    *,
    goal: Goal,
    phase: str | None,
    attempt: int,
    max_retries: int,
    outcome: Outcome,
    test_output: str,
) -> None:
    if not _should_emit_failure_assist(outcome, attempt, max_retries):
        return
    suggestions = _build_failure_assist_suggestions(goal, outcome, test_output)
    if not suggestions:
        return

    phase_label = phase or "legacy"
    _log_warning(
        f"[{goal.id}] failure assist ({phase_label}): "
        f"classification={outcome.classification}"
    )
    for suggestion in suggestions[:4]:
        _log_warning(f"  suggestion: {suggestion}")


def _should_emit_failure_assist(outcome: Outcome, attempt: int, max_retries: int) -> bool:
    if outcome.success:
        return False
    if not outcome.should_retry:
        return True
    return attempt >= max_retries


def _build_failure_assist_suggestions(
    goal: Goal,
    outcome: Outcome,
    test_output: str,
) -> list[str]:
    reason = outcome.reason or ""
    normalized = f"{outcome.classification}\n{reason}\n{test_output[:2000]}".lower()
    suggestions: list[str] = []

    decision_signal = (
        outcome.classification == "decision-pending"
        or "decision_file" in normalized
        or "uncertainty=high" in normalized
        or goal.uncertainty == "high"
    )
    if decision_signal:
        suggestions.append(
            f"Create decision ticket first: hast decision new {goal.id} "
            '--question "..." --alternatives A,B'
        )
        if not goal.decision_file:
            suggestions.append(
                "Set goal.decision_file and keep uncertainty=high until decision is accepted."
            )

    interface_signal = any(
        token in normalized
        for token in (
            "missing param",
            "missing argument",
            "unexpected keyword",
            "attributeerror",
            "signature",
            "interface",
            "contract",
            "api",
        )
    )
    if interface_signal:
        suggestions.append(
            "Add a prerequisite interface goal and wire depends_on before retrying this goal."
        )
        suggestions.append('Run design scan: hast explore "<interface change question>"')

    if outcome.classification == "no-progress" or "no file changes" in normalized:
        suggestions.append(
            'Run design scan before retry: hast explore "<what is unclear?>"'
        )
        suggestions.append(
            "If ambiguity remains, set blocked_by='DECISION: ...' and request a decision ticket."
        )

    if "outside allowed scope" in normalized or "out-of-scope" in normalized:
        suggestions.append(
            "Adjust goal.allowed_changes or config always_allow_changes, then run hast retry <goal_id>."
        )

    if any(token in normalized for token in ("tests failed", "contract-violation", "phase-violation")):
        suggestions.append(
            "If test failures indicate unclear expected behavior, create a decision ticket before next retry."
        )

    # Preserve order, remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for item in suggestions:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def build_prompt(
    root: Path,
    config: Config,
    goal: Goal,
    attempts: list[AttemptLog] | None = None,
) -> str:
    # Use 'pack' format for structured XML context
    context = build_context(root, "pack", config.max_context_bytes, goal_override=goal)

    filename_ts = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")

    instructions: list[str] = []

    # Contract guidance (if configured)
    contract, contract_error = _load_goal_contract(root, goal)
    if contract_error:
        instructions.append(f"CONTRACT ERROR: {contract_error}")
    elif contract:
        instructions.extend(contract_prompt_lines(contract))
        instructions.append("Never modify the contract file.")
        if goal.contract_file:
            instructions.append(f"Contract file: {goal.contract_file}")
        instructions.append("")
    
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
    instructions.extend(
        [
            "",
            "NON-INTERACTIVE CONTRACT:",
            "- Do not ask clarification questions.",
            "- If ambiguous, choose the safest reversible assumption and proceed.",
            "- Output concrete file changes now, then list assumptions in summary.",
        ]
    )

    if goal.expect_failure:
        instructions.append("This step is RED: tests are expected to fail.")
    if goal.prompt_mode == "adversarial":
        instructions.append("Be adversarial: break the code via edge cases.")
    
    # Add BDD Instruction if needed, though usually implicit in goal instructions
    
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
        "contract_lines": [],
    }

    contract, _ = _load_goal_contract(root, goal)
    if contract:
        template_vars["contract_lines"] = contract_prompt_lines(contract)

    # Phase-specific variables
    if phase == "plan":
        template_vars["capabilities_meta"] = _read_file_safe(root / ".ai" / "capabilities.yaml", max_lines=15)
        template_vars["recent_handoff"] = _read_latest_handoff_content(root)
        template_vars["unresolved_vulns"] = _read_unresolved_vulns(root)
        template_vars["current_goals_summary"] = _read_file_safe(root / ".ai" / "goals.yaml")

    if phase == "adversarial":
        template_vars["playbook"] = _read_file_safe(root / ".adversarial" / "playbook.yaml")
        template_vars["recent_diff"] = ""  # Will be populated in run_auto context

    return template.render(template_vars) + (
        "\n\nNON-INTERACTIVE CONTRACT:\n"
        "- Do not ask clarification questions.\n"
        "- If ambiguous, choose the safest reversible assumption and proceed.\n"
        "- Output concrete file changes and list assumptions in summary.\n"
    )


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
    policy_root: Path | None = None,
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
    return evaluate(root, config, goal, base_commit, policy_root=policy_root)


def evaluate(
    root: Path,
    config: Config,
    goal: Goal,
    base_commit: str,
    policy_root: Path | None = None,
) -> tuple[Outcome, str]:
    contract, contract_error = _load_goal_contract(root, goal)
    if contract_error:
        return (
            Outcome(
                success=False,
                should_retry=False,
                classification="contract-invalid",
                reason=contract_error,
            ),
            "",
        )

    changed_files = get_changed_files(root, base_commit)
    has_changes = bool(changed_files)
    languages = resolve_goal_languages(root, goal, config, changed_files)

    role_ok, role_reason = _validate_role_scope(goal, changed_files)
    if not role_ok:
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification="phase-violation",
                reason=role_reason,
            ),
            "",
        )

    if contract:
        change_ok, change_reason = _validate_contract_change_rules(
            changed_files, contract, goal.contract_file,
        )
        if not change_ok:
            return (
                Outcome(
                    success=False,
                    should_retry=True,
                    classification="contract-violation",
                    reason=change_reason,
                ),
                "",
            )

    if goal.allowed_changes and has_changes:
        violations = _out_of_scope_files(
            changed_files,
            goal.allowed_changes,
            always_allow=config.always_allow_changes,
        )
        if violations:
            return (
                Outcome(
                    success=False,
                    should_retry=True,
                    classification="failed",
                    reason="changes outside allowed scope: " + ", ".join(violations[:5]),
                ),
                "",
            )

    immune_root = policy_root or root
    immune_check = evaluate_immune_changes(
        immune_root,
        changed_files,
        metadata={
            "goal_id": goal.id,
            "phase": goal.phase or "legacy",
            "check": "evaluate",
        },
    )
    if not immune_check.allowed:
        return (
            Outcome(
                success=False,
                should_retry=False,
                classification="immune-blocked",
                reason=immune_check.reason,
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

    test_ok, test_output = _run_tests(root, config.test_command, config)

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
        triage_class, triage_reason = _triage_test_failure(test_output)
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification=triage_class,
                reason=triage_reason,
            ),
            test_output,
        )

    pass_ok, pass_output, pass_reason = _run_contract_pass_tests(
        root,
        contract,
        config=config,
        languages=languages,
    )
    if not pass_ok:
        return (
            Outcome(
                success=False,
                should_retry=True,
                classification="contract-violation",
                reason=pass_reason,
            ),
            pass_output,
        )

    # Complexity guard: warn on threshold violations (does not fail)
    warnings = complexity_check(changed_files, root)
    for w in warnings:
        _log_warning(f"[complexity] {w}")

    return (
        Outcome(success=True, should_retry=False, classification="complete"),
        test_output,
    )


def _run_tests(root: Path, command: str, config: Config | None = None) -> tuple[bool, str]:
    effective_command = command
    if config is not None:
        effective_command = apply_pytest_reliability_flags(
            command,
            config.gate,
            include_reruns=False,
        )

    proc = subprocess.run(
        effective_command,
        cwd=str(root),
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    output = proc.stdout
    if proc.stderr:
        output = output + "\n" + proc.stderr if output else proc.stderr
    if proc.returncode == 0:
        return True, output

    if (
        config is None
        or config.gate.pytest_reruns_on_flaky <= 0
        or not _looks_like_flaky_failure(output)
    ):
        return False, output

    rerun_command = apply_pytest_reliability_flags(
        command,
        config.gate,
        include_reruns=True,
    )
    rerun_proc = subprocess.run(
        rerun_command,
        cwd=str(root),
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    rerun_output = rerun_proc.stdout
    if rerun_proc.stderr:
        rerun_output = rerun_output + "\n" + rerun_proc.stderr if rerun_output else rerun_proc.stderr
    combined_output = (
        output
        + "\n\n[hast] flaky rerun triggered\n"
        + rerun_output
    )
    return rerun_proc.returncode == 0, combined_output


def _record_evidence(
    root: Path,
    run_id: str,
    goal_id: str,
    phase: str | None,
    attempt: int,
    outcome: Outcome,
    wt_root: Path,
    base_commit: str,
    test_output: str,
    policy_decision: PolicyDecision | None = None,
    runner_result: RunnerResult | None = None,
) -> None:
    try:
        state_from, state_to = _update_goal_state_for_evidence(root, goal_id, phase, outcome)
        changed_files = get_changed_files(wt_root, base_commit)
        row = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "run_id": run_id,
            "goal_id": goal_id,
            "phase": phase,
            "attempt": attempt,
            "success": outcome.success,
            "should_retry": outcome.should_retry,
            "classification": outcome.classification,
            "reason": outcome.reason,
            "changed_files": changed_files,
            "diff_stat": _get_diff_stat(wt_root, base_commit),
            "test_output_hash": hash_text(test_output or ""),
            "test_output_preview": (test_output or "")[-600:],
            "state_from": state_from,
            "state_to": state_to,
            "state_changed": state_from != state_to,
            "policy_version": policy_decision.policy_version if policy_decision else None,
            "failure_classification": (
                policy_decision.failure_classification if policy_decision else None
            ),
            "action_taken": policy_decision.action_taken if policy_decision else None,
            "risk_score": policy_decision.risk_score if policy_decision else None,
            "model_used": runner_result.model_used if runner_result else None,
            "latency_ms": runner_result.latency_ms if runner_result else None,
            "cost_tokens_prompt": runner_result.cost_tokens_prompt if runner_result else None,
            "cost_tokens_completion": runner_result.cost_tokens_completion if runner_result else None,
            "cost_estimate_usd": runner_result.cost_estimate_usd if runner_result else None,
        }
        if phase == "gate":
            gate_checks = _parse_gate_checks_from_summary(test_output or "")
            row["gate_checks"] = gate_checks
            row["gate_failed_checks"] = [
                check["name"] for check in gate_checks if check.get("status") == "FAIL"
            ]
            security = _extract_security_signals_from_summary(test_output or "")
            row["security_failed_checks"] = security.failed_checks
            row["security_missing_tool_checks"] = security.missing_tool_checks
            row["security_ignored_checks"] = security.ignored_checks
            row["security_expired_ignore_rules"] = security.expired_ignore_rules
        write_evidence_row(root, run_id, row)
    except Exception as exc:  # pragma: no cover - evidence must be non-blocking
        _log_warning(f"failed to write evidence: {exc}")


def _record_goal_invalidation_evidence(
    root: Path,
    run_id: str,
    event: InvalidationEvent,
) -> None:
    try:
        row = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "run_id": run_id,
            "goal_id": event.goal_id,
            "phase": "replan",
            "attempt": 0,
            "success": True,
            "should_retry": False,
            "classification": "goal-invalidated",
            "reason": (
                f"{event.goal_id} -> {event.to_status} "
                f"by {event.invalidated_by} ({event.reason_code})"
            ),
            "changed_files": [],
            "diff_stat": "",
            "test_output_hash": hash_text(""),
            "test_output_preview": "",
            "state_from": event.state_from,
            "state_to": event.state_to,
            "state_changed": event.state_from != event.state_to,
            "policy_version": None,
            "failure_classification": None,
            "action_taken": "advance",
            "risk_score": None,
            "model_used": None,
            "latency_ms": None,
            "cost_tokens_prompt": None,
            "cost_tokens_completion": None,
            "cost_estimate_usd": None,
            "invalidation_from_status": event.from_status,
            "invalidation_to_status": event.to_status,
            "invalidation_reason_code": event.reason_code,
            "invalidated_by_goal": event.invalidated_by,
        }
        write_evidence_row(root, run_id, row)
    except Exception as exc:  # pragma: no cover - evidence must be non-blocking
        _log_warning(f"failed to write invalidation evidence: {exc}")


def _parse_gate_checks_from_summary(summary: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"^\s{2}([^:]+):\s+(PASS|FAIL|SKIP)\s*$")
    for raw_line in summary.splitlines():
        line = raw_line.rstrip()
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            {
                "name": match.group(1).strip(),
                "status": match.group(2),
            }
        )
    return rows


def _extract_security_signals_from_summary(summary: str) -> SecuritySignals:
    check_line = re.compile(r"^\s{2}([^:]+):\s+(PASS|FAIL|SKIP)\s*$")
    failed_checks: list[str] = []
    missing_tool_checks: list[str] = []
    ignored_checks: list[str] = []
    expired_ignore_rules: list[str] = []

    current_check: str | None = None
    current_status: str | None = None

    for raw_line in summary.splitlines():
        line = raw_line.rstrip()
        check_match = check_line.match(line)
        if check_match:
            current_check = check_match.group(1).strip()
            current_status = check_match.group(2)
            if _is_security_check(current_check) and current_status == "FAIL":
                failed_checks.append(current_check)
            continue

        if current_check is None or current_status is None or not _is_security_check(current_check):
            continue
        if not line.startswith("    "):
            continue

        lower = line.lower()
        if "missing security tool" in lower:
            missing_tool_checks.append(current_check)
        if "[security-ignore]" in line:
            ignored_checks.append(current_check)
        if "[security-ignore-expired]" in line:
            rule_id = _extract_security_rule_id(line)
            if rule_id:
                expired_ignore_rules.append(rule_id)

    ignored = set(ignored_checks)
    if ignored:
        failed_checks = [name for name in failed_checks if name not in ignored]
        missing_tool_checks = [name for name in missing_tool_checks if name not in ignored]

    return SecuritySignals(
        failed_checks=_unique_preserve_order(failed_checks),
        missing_tool_checks=_unique_preserve_order(missing_tool_checks),
        ignored_checks=_unique_preserve_order(ignored_checks),
        expired_ignore_rules=_unique_preserve_order(expired_ignore_rules),
    )


def _security_force_block_reason(policies: AutoPolicies, signals: SecuritySignals) -> str | None:
    if signals.failed_checks and policies.risk.security_force_block_on_failed_checks:
        return "security-check-failed (" + ", ".join(signals.failed_checks[:3]) + ")"
    if signals.missing_tool_checks and policies.risk.security_force_block_on_missing_tools:
        return "security-tool-missing (" + ", ".join(signals.missing_tool_checks[:3]) + ")"
    return None


def _is_security_check(check_name: str) -> bool:
    base = re.sub(r"_\d+$", "", check_name)
    if base in {"gitleaks", "semgrep", "trivy", "grype", "dependency_scan"}:
        return True
    return base.startswith("security_check_")


def _extract_security_rule_id(line: str) -> str | None:
    match = re.search(r"rule=([A-Za-z0-9_.:-]+)", line)
    return match.group(1) if match else None


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _update_goal_state_for_evidence(
    root: Path,
    goal_id: str,
    phase: str | None,
    outcome: Outcome,
) -> tuple[str | None, str | None]:
    goals_path = root / ".ai" / "goals.yaml"
    if not goals_path.exists():
        return None, None

    with _ROOT_LOCK:
        goals = load_goals(goals_path)
        goal = find_goal(goals, goal_id)
        if goal is None:
            return None, None

        state_from = goal.state
        state_to = decide_goal_state(state_from, phase, outcome.success, outcome.classification)
        if state_to != state_from and state_to is not None:
            update_goal_fields(goals_path, goal_id, {"state": state_to})
        return state_from, state_to


def _apply_policy_decision(
    root: Path,
    goal_id: str,
    phase: str | None,
    attempt: int,
    outcome: Outcome,
    test_output: str,
    wt_root: Path,
    base_commit: str,
    max_retries: int,
    policies: AutoPolicies,
) -> tuple[Outcome, PolicyDecision]:
    changed_files = get_changed_files(wt_root, base_commit)
    security_signals = (
        _extract_security_signals_from_summary(test_output)
        if phase == "gate"
        else SecuritySignals()
    )

    if outcome.success:
        success_block_reason = None
        if security_signals.missing_tool_checks and policies.risk.security_force_block_on_missing_tools:
            success_block_reason = _security_force_block_reason(policies, security_signals)
        if success_block_reason:
            risk_score = compute_risk_score(
                policies.risk,
                phase,
                changed_files,
                "security",
                security_failed_checks=len(security_signals.failed_checks),
                security_missing_tools=len(security_signals.missing_tool_checks),
                security_expired_ignores=len(security_signals.expired_ignore_rules),
            )
            blocked_classification = "gate-fail" if phase == "gate" else "failed"
            blocked_outcome = Outcome(
                success=False,
                should_retry=False,
                classification=blocked_classification,
                reason=(
                    "policy action=block classification=security; "
                    + success_block_reason
                ),
            )
            return (
                blocked_outcome,
                PolicyDecision(
                    policy_version=policies.version,
                    failure_classification="security",
                    action_taken=BLOCK_ACTION,
                    risk_score=risk_score,
                ),
            )
        return outcome, _success_policy_decision(
            policies,
            phase,
            changed_files,
            security_signals=security_signals,
        )

    failure_classification = classify_failure(
        outcome.classification,
        outcome.reason,
        test_output,
    )
    if security_signals.failed_checks:
        failure_classification = "security"

    risk_score = compute_risk_score(
        policies.risk,
        phase,
        changed_files,
        failure_classification,
        security_failed_checks=len(security_signals.failed_checks),
        security_missing_tools=len(security_signals.missing_tool_checks),
        security_expired_ignores=len(security_signals.expired_ignore_rules),
    )

    force_block_reason = _security_force_block_reason(policies, security_signals)
    if force_block_reason:
        reason = outcome.reason or ""
        suffix = f"policy action=block classification={failure_classification}; {force_block_reason}"
        reason = suffix if not reason else f"{reason}; {suffix}"
        blocked_outcome = Outcome(
            success=outcome.success,
            should_retry=False,
            classification=outcome.classification,
            reason=reason,
        )
        return (
            blocked_outcome,
            PolicyDecision(
                policy_version=policies.version,
                failure_classification=failure_classification,
                action_taken=BLOCK_ACTION,
                risk_score=risk_score,
            ),
        )

    if not outcome.should_retry:
        return (
            outcome,
            PolicyDecision(
                policy_version=policies.version,
                failure_classification=failure_classification,
                action_taken=BLOCK_ACTION,
                risk_score=risk_score,
            ),
        )

    prior_failures = [
        classify_failure(log.classification, log.reason, log.test_output)
        for log in load_attempts(root, goal_id)
    ]
    action = decide_retry_action(
        policy=policies.retry,
        failure_classification=failure_classification,
        prior_failure_classifications=prior_failures,
        attempt=attempt,
        fallback_max_retries=max_retries,
    )
    should_retry = action == RETRY_ACTION
    reason = outcome.reason
    if not should_retry and action != RETRY_ACTION:
        suffix = f"policy action={action} classification={failure_classification}"
        reason = f"{reason}; {suffix}" if reason else suffix

    decided_outcome = Outcome(
        success=outcome.success,
        should_retry=should_retry,
        classification=outcome.classification,
        reason=reason,
    )
    return (
        decided_outcome,
        PolicyDecision(
            policy_version=policies.version,
            failure_classification=failure_classification,
            action_taken=action,
            risk_score=risk_score,
        ),
    )


def _success_policy_decision(
    policies: AutoPolicies,
    phase: str | None,
    changed_files: list[str],
    security_signals: SecuritySignals | None = None,
) -> PolicyDecision:
    signals = security_signals or SecuritySignals()
    return PolicyDecision(
        policy_version=policies.version,
        failure_classification=None,
        action_taken=ADVANCE_ACTION,
        risk_score=compute_risk_score(
            policies.risk,
            phase,
            changed_files,
            None,
            security_failed_checks=len(signals.failed_checks),
            security_missing_tools=len(signals.missing_tool_checks),
            security_expired_ignores=len(signals.expired_ignore_rules),
        ),
    )


def _verify_bdd_red_stage(
    root: Path,
    base_commit: str,
    contract_file: str | None = None,
    contract: AcceptanceContract | None = None,
    config: Config | None = None,
    languages: list[str] | None = None,
) -> RedGateResult:
    changed_files = get_changed_files(root, base_commit)
    if contract_file and contract_file in changed_files:
        return RedGateResult(
            passed=False,
            reason=f"contract file modified during RED stage: {contract_file}",
        )

    if config and config.language_profiles:
        resolved_languages = languages or ["python"]
        test_files = collect_test_files(changed_files, config, resolved_languages)
        if not test_files:
            return RedGateResult(
                passed=False,
                reason=(
                    "no new or modified test files were generated in RED stage for languages: "
                    + ", ".join(resolved_languages)
                ),
            )
    else:
        test_files = [path for path in changed_files if _is_python_test_file(path)]

    if not test_files:
        return RedGateResult(
            passed=False,
            reason="no new or modified Python test files were generated in RED stage",
        )

    src_changes = [path for path in changed_files if path.startswith("src/")]
    if src_changes:
        return RedGateResult(
            passed=False,
            reason="source files changed during RED stage: " + ", ".join(src_changes[:5]),
        )

    if not _has_assertions(root, test_files, config=config, languages=languages):
        return RedGateResult(
            passed=False,
            reason="generated tests contain no assertions",
        )

    if not _has_nontrivial_assertions(root, test_files, config=config, languages=languages):
        return RedGateResult(
            passed=False,
            reason="generated assertions are trivial (e.g. assert True)",
        )

    if contract:
        ok, reason = validate_required_patterns(
            test_files, contract.required_test_files, "red test files",
        )
        if not ok:
            return RedGateResult(passed=False, reason=reason or "missing required test files")
        ok, reason = _validate_required_assertions(root, test_files, contract.required_assertions)
        if not ok:
            return RedGateResult(passed=False, reason=reason or "missing required assertions")

    test_ok, test_output = _run_targeted_tests(
        root,
        test_files,
        config=config,
        languages=languages,
    )
    if test_ok:
        return RedGateResult(
            passed=False,
            reason="generated tests already pass; RED must fail before implementation",
            test_output=test_output,
            test_files=test_files,
        )

    if contract and contract.must_fail_tests:
        fail_ok, fail_output, fail_reason = _run_contract_fail_tests(
            root,
            contract,
            config=config,
            languages=languages,
        )
        if not fail_ok:
            return RedGateResult(
                passed=False,
                reason=fail_reason or "contract must_fail_tests not satisfied",
                test_output=fail_output,
                test_files=test_files,
            )

    return RedGateResult(
        passed=True,
        reason="red verified",
        test_output=test_output,
        test_files=test_files,
    )


def _run_targeted_pytest(
    root: Path,
    test_files: list[str],
    config: Config | None = None,
) -> tuple[bool, str]:
    command = "pytest -q " + " ".join(shlex.quote(path) for path in test_files)
    return _run_tests(root, command, config)


def _run_targeted_tests(
    root: Path,
    test_files: list[str],
    config: Config | None,
    languages: list[str] | None,
) -> tuple[bool, str]:
    if not config or not config.language_profiles:
        return _run_targeted_pytest(root, test_files, config)

    resolved_languages = languages or ["python"]
    commands = build_targeted_test_commands(config, resolved_languages, test_files)
    if not commands:
        return _run_targeted_pytest(root, test_files, config)

    outputs: list[str] = []
    for _, command in commands:
        ok, output = _run_tests(root, command, config)
        outputs.append(output)
        if not ok:
            return False, "\n".join(p for p in outputs if p.strip())

    combined = "\n".join(p for p in outputs if p.strip())
    return True, combined


def _validate_bdd_impl_scope(
    changed_files: list[str],
    contract_file: str | None = None,
) -> tuple[bool, str | None]:
    disallowed = [
        path for path in changed_files
        if _is_real_change_file(path) and (path.startswith("tests/") or path.endswith(".feature"))
    ]
    if contract_file and contract_file in changed_files:
        disallowed.append(contract_file)
    if disallowed:
        return (
            False,
            "implementation modified protected files (test/spec/contract): " + ", ".join(disallowed[:5]),
        )
    return True, None


def _validate_role_scope(goal: Goal, changed_files: list[str]) -> tuple[bool, str | None]:
    """Enforce coarse write-scope restrictions by role."""
    role = goal.owner_agent
    if role is None:
        return True, None

    real_changes = [path for path in changed_files if _is_real_change_file(path)]
    if role == "tester":
        disallowed = [path for path in real_changes if path.startswith("src/")]
        if disallowed:
            return False, "tester role cannot modify src/: " + ", ".join(disallowed[:5])
    elif role == "worker":
        disallowed = [
            path for path in real_changes
            if path.startswith("tests/") or path.endswith(".feature")
        ]
        if disallowed:
            return False, "worker role cannot modify tests/spec files: " + ", ".join(disallowed[:5])
    elif role == "architect":
        disallowed = [
            path for path in real_changes
            if path.startswith("src/") or path.startswith("tests/")
        ]
        if disallowed:
            return False, "architect role cannot modify src/tests directly: " + ", ".join(disallowed[:5])
    return True, None


def _validate_planned_changes(
    root: Path,
    goal: Goal,
    changes: dict[str, str] | list[object],
    stage: str | None,
    contract_file: str | None = None,
    attempt: int | None = None,
) -> tuple[bool, str | None]:
    """Block disallowed file writes before applying parsed changes."""
    changed_files: list[str]
    if isinstance(changes, dict):
        changed_files = sorted(changes.keys())
    elif isinstance(changes, list):
        changed_files = []
        for item in changes:
            path = getattr(item, "path", None)
            if isinstance(path, str) and path:
                changed_files.append(path)
        changed_files = sorted(set(changed_files))
    else:
        return False, "invalid planned changes payload"

    if not changed_files:
        return True, None

    if stage == "bdd-red":
        disallowed = [path for path in changed_files if path.startswith("src/")]
        if disallowed:
            return False, "RED stage cannot modify source files: " + ", ".join(disallowed[:5])
        if contract_file and contract_file in changed_files:
            return False, f"contract file cannot be modified in RED stage: {contract_file}"

    if stage == "bdd-green":
        ok, reason = _validate_bdd_impl_scope(changed_files, contract_file)
        if not ok:
            return False, reason

    ok, reason = _validate_role_scope(goal, changed_files)
    if not ok:
        return False, reason

    immune_check = evaluate_immune_changes(
        root,
        changed_files,
        metadata={
            "goal_id": goal.id,
            "phase": stage or "legacy",
            "attempt": attempt,
            "check": "planned",
        },
    )
    if not immune_check.allowed:
        return False, immune_check.reason

    return True, None


def _is_real_change_file(path: str) -> bool:
    if path.startswith(".ai/"):
        return False
    if "__pycache__/" in path or path.endswith(".pyc"):
        return False
    return True


def _is_python_test_file(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    if path.startswith("tests/"):
        return True
    return "/tests/" in path


def _has_assertions(
    root: Path,
    test_files: list[str],
    config: Config | None = None,
    languages: list[str] | None = None,
) -> bool:
    patterns = ["assert ", "pytest.raises("]
    if config and config.language_profiles and languages:
        patterns = language_assertion_patterns(config, languages) or patterns

    for rel in test_files:
        fp = root / rel
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        if any(pattern in text for pattern in patterns):
            return True
    return False


def _has_nontrivial_assertions(
    root: Path,
    test_files: list[str],
    config: Config | None = None,
    languages: list[str] | None = None,
) -> bool:
    trivial_patterns = [
        "assert True",
        "assert 1 == 1",
        "assert 0 == 0",
    ]
    assertion_tokens = ["assert ", "pytest.raises("]
    if config and config.language_profiles and languages:
        assertion_tokens = language_assertion_patterns(config, languages) or assertion_tokens
        trivial_patterns = language_trivial_assertions(config, languages) or trivial_patterns

    for rel in test_files:
        fp = root / rel
        if not fp.exists():
            continue
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not any(token in line for token in assertion_tokens):
                continue
            if not any(pattern in line for pattern in trivial_patterns):
                return True
    return False


def _validate_required_assertions(
    root: Path,
    test_files: list[str],
    required_assertions: list[str],
) -> tuple[bool, str | None]:
    if not required_assertions:
        return True, None

    contents: list[str] = []
    for rel in test_files:
        fp = root / rel
        if fp.exists():
            contents.append(fp.read_text(encoding="utf-8", errors="ignore"))
    merged = "\n".join(contents)

    for snippet in required_assertions:
        if snippet not in merged:
            return False, f"required assertion missing in RED tests: {snippet}"
    return True, None


def _load_goal_contract(root: Path, goal: Goal) -> tuple[AcceptanceContract | None, str | None]:
    if not goal.contract_file:
        return None, None
    try:
        contract = load_acceptance_contract(root, goal.contract_file)
    except DevfError as exc:
        return None, str(exc)
    return contract, None


def _validate_goal_decision_prerequisites(goal_root: Path, goal: Goal) -> tuple[bool, str | None]:
    needs_decision = bool(goal.decision_file) or goal.uncertainty == "high"
    if not needs_decision:
        return True, None

    if not goal.decision_file:
        return False, "uncertainty=high requires decision_file"

    decision_path = goal_root / goal.decision_file
    try:
        ticket = load_decision_ticket(decision_path)
    except DevfError as exc:
        return False, str(exc)

    ticket_goal_id = ticket.get("goal_id")
    if isinstance(ticket_goal_id, str) and ticket_goal_id and ticket_goal_id != goal.id:
        return (
            False,
            (
                "decision ticket goal_id mismatch: "
                f"{ticket_goal_id} != {goal.id}"
            ),
        )

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


def _validate_contract_change_rules(
    changed_files: list[str],
    contract: AcceptanceContract,
    contract_file: str | None,
) -> tuple[bool, str | None]:
    if contract_file and contract_file in changed_files:
        return False, f"contract file modified: {contract_file}"

    relevant_files = [path for path in changed_files if _is_real_change_file(path)]

    ok, reason = validate_required_patterns(
        relevant_files, contract.required_changes, "changed files",
    )
    if not ok:
        return False, reason
    ok, reason = validate_required_patterns(
        relevant_files, contract.required_docs, "changed files (docs)",
    )
    if not ok:
        return False, reason
    ok, reason = validate_required_patterns(
        relevant_files, contract.required_security_docs, "changed files (security docs)",
    )
    if not ok:
        return False, reason
    ok, reason = validate_forbidden_patterns(
        relevant_files, contract.forbidden_changes, "changed files",
    )
    if not ok:
        return False, reason
    return True, None


def _run_contract_pass_tests(
    root: Path,
    contract: AcceptanceContract | None,
    config: Config | None = None,
    languages: list[str] | None = None,
) -> tuple[bool, str, str | None]:
    if not contract or not contract.must_pass_tests:
        return True, "", None
    ok, output = _run_targeted_tests(root, contract.must_pass_tests, config, languages)
    if ok:
        return True, output, None
    return False, output, "contract must_pass_tests failed"


def _run_contract_fail_tests(
    root: Path,
    contract: AcceptanceContract,
    config: Config | None = None,
    languages: list[str] | None = None,
) -> tuple[bool, str, str | None]:
    if not contract.must_fail_tests:
        return True, "", None
    ok, output = _run_targeted_tests(root, contract.must_fail_tests, config, languages)
    if ok:
        return False, output, "contract must_fail_tests unexpectedly passed in RED"
    return True, output, None


def _triage_test_failure(test_output: str) -> tuple[str, str]:
    text = test_output.lower()
    if not text.strip():
        return "failed-unknown", "tests failed"
    if "modulenotfounderror" in text or "importerror" in text or "no module named" in text:
        return "failed-env", "tests failed (environment/dependency issue)"
    if "syntaxerror" in text or "indentationerror" in text:
        return "failed-syntax", "tests failed (syntax error)"
    if _looks_like_flaky_failure(text) or ("rerun" in text and "timeout" in text):
        return "failed-flaky", "tests failed (possible flake/timeout)"
    if "assertionerror" in text or "=== failures ===" in text or " failed " in text:
        return "failed-impl", "tests failed (implementation mismatch)"
    return "failed-unknown", "tests failed (unclassified)"


def _looks_like_flaky_failure(text: str) -> bool:
    lowered = text.lower()
    flaky_signals = (
        "timeout",
        "flaky",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "rerun",
    )
    return any(signal in lowered for signal in flaky_signals)


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


def _changes_allowed(
    files: Iterable[str],
    patterns: Iterable[str],
    always_allow: Iterable[str] = (),
) -> bool:
    return not _out_of_scope_files(files, patterns, always_allow=always_allow)


def _out_of_scope_files(
    files: Iterable[str],
    patterns: Iterable[str],
    always_allow: Iterable[str] = (),
) -> list[str]:
    out_of_scope: list[str] = []
    for path in files:
        if path.startswith(".ai/"):
            continue  # hast metadata always allowed
        if "__pycache__/" in path or path.endswith(".pyc"):
            continue  # compiled bytecode is never a real change
        if any(fnmatch.fnmatch(path, pattern) for pattern in always_allow):
            continue  # always-allow list (e.g. generated files by local hooks)
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            out_of_scope.append(path)
    return sorted(out_of_scope)


def _list_blocking_dirty_paths(root: Path) -> list[str]:
    """Return dirty paths that should block auto-run startup.

    Untracked `.ai/**` artifacts are operational metadata and do not block.
    """
    status_output = run_git(["status", "--porcelain"], root, check=True).stdout
    blocking: set[str] = set()
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if code == "??" and path.startswith(".ai/"):
            continue
        if path:
            blocking.add(path)
    return sorted(blocking)


def _lock_path(root: Path) -> Path:
    return root / ".ai" / "auto.lock"


def _acquire_lock(root: Path) -> None:
    lock_path = _lock_path(root)
    if lock_path.exists():
        lock_info = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
        pid = lock_info.get("pid")
        base_commit = lock_info.get("base_commit")
        if isinstance(pid, int) and _pid_alive(pid):
            raise DevfError("hast auto is already running")
        if isinstance(base_commit, str) and _list_blocking_dirty_paths(root):
            try:
                reset_hard(root, base_commit)
            except Exception as exc:
                raise DevfError("failed to recover dirty state") from exc
        lock_path.unlink(missing_ok=True)

    blocking_dirty = _list_blocking_dirty_paths(root)
    if blocking_dirty:
        raise DevfError(
            "working tree is dirty outside .ai/ operational artifacts; "
            f"first entries: {', '.join(blocking_dirty[:5])}"
        )

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
