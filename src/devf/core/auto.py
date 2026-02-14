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

from devf.core.attempt import (
    AttemptLog,
    clear_attempts,
    load_attempts,
    save_attempt,
)
from devf.core.config import Config, load_config
from devf.core.contract import (
    AcceptanceContract,
    contract_prompt_lines,
    load_acceptance_contract,
    validate_forbidden_patterns,
    validate_required_patterns,
)
from devf.core.decision import load_decision_ticket
from devf.core.context import build_context
from devf.core.evidence import hash_text, new_run_id, write_evidence_row
from devf.core.errors import DevfError
from devf.core.feedback_infer import infer_and_store_feedback_notes
from devf.core.feedback_policy import load_feedback_policy
from devf.core.gate import run_gate
from devf.core.goals import (
    Goal,
    collect_goals,
    find_goal,
    load_goals,
    update_goal_fields,
    update_goal_status,
)
from devf.core.languages import (
    assertion_patterns as language_assertion_patterns,
    build_targeted_test_commands,
    collect_test_files,
    resolve_goal_languages,
    trivial_assertions as language_trivial_assertions,
)
from devf.core.phase import load_phase_template, next_phase, parse_plan_output, regress_phase
from devf.core.policies import AutoPolicies, load_auto_policies
from devf.core.runner import GoalRunner, RunnerResult
from devf.core.retry_policy import (
    ADVANCE_ACTION,
    BLOCK_ACTION,
    RETRY_ACTION,
    decide_retry_action,
)
from devf.core.replan import InvalidationEvent, apply_post_goal_replan
from devf.core.risk_policy import compute_risk_score
from devf.core.runners.local import LocalRunner
from devf.core.runners.llm import LLMRunner
from devf.core.scheduler import build_execution_batches
from devf.core.session import generate_session_log, write_session_log
from devf.core.state_policy import decide_goal_state
from devf.core.triage import classify_failure
from devf.utils.codetools import complexity_check
from devf.utils.file_parser import parse_file_changes, apply_file_changes
from devf.utils.git import (
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


_ROOT_LOCK = threading.RLock()


def run_auto(
    root: Path,
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    explain: bool,
    tool_name: str | None,
    runner: GoalRunner | None = None,
    parallelism: int = 1,
) -> int:
    config, warnings = load_config(root / ".ai" / "config.yaml")
    for warning in warnings:
        _log_warning(warning)

    goals = load_goals(root / ".ai" / "goals.yaml")
    selected = collect_goals(goals, goal_id, recursive)
    if not selected:
        raise DevfError("no active goals to run")
    batches = build_execution_batches(goals, selected)

    # dry-run: print prompt and exit, no lock or dirty check needed
    if dry_run:
        for goal in selected:
            if goal.spec_file:
                 print(f"BDD Mode: {goal.spec_file}")
            elif goal.phase:
                print(build_phase_prompt(root, config, goal, goal.phase, []))
            else:
                print(build_prompt(root, config, goal, []))
        return 0

    # Select runner
    # If explicit runner provided (e.g. from test), use it.
    # If config.roles is set, prefer LLMRunner.
    # Else fallback to LocalRunner.
    if runner is None:
        if config.roles.worker or config.roles.architect:
            runner = LLMRunner()
        else:
            runner = LocalRunner()

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
        except Exception as exc:  # pragma: no cover - post-run feedback should be non-blocking
            _log_warning(f"failed to infer feedback notes: {exc}")
    return exit_code


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
    pre_merge_ok, pre_merge_output = _run_tests(wt_root, pre_merge_cmd)
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
        commit_all(wt_root, f"devf({goal.id}): pre-merge")

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
        post_ok, post_output = _run_tests(root, post_merge_cmd)
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
            ok, reason = _validate_planned_changes(goal, changes, stage="bdd-red", contract_file=goal.contract_file)
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
        commit_all(wt_root, f"devf({goal.id}): red baseline")
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
                    goal, changes, stage="bdd-green", contract_file=goal.contract_file,
                )
                if not ok:
                    outcome = Outcome(
                        success=False,
                        should_retry=True,
                        classification="phase-violation",
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

            test_ok, test_output = _run_tests(wt_root, config.test_command)
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
                 ok, reason = _validate_planned_changes(goal, changes, stage="legacy")
                 if not ok:
                     outcome = Outcome(
                         success=False,
                         should_retry=True,
                         classification="phase-violation",
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

        outcome, test_output = evaluate(wt_root, config, goal, base_commit)

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
                 ok, reason = _validate_planned_changes(goal, changes, stage=phase)
                 if not ok:
                     outcome = Outcome(
                         success=False,
                         should_retry=True,
                         classification="phase-violation",
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

        outcome, test_output = evaluate_phase(wt_root, config, goal, phase, base_commit)

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

        if outcome.success:
            # Handle plan phase output parsing
            if phase == "plan" and result.output:
                parsed = parse_plan_output(result.output)
                if parsed:
                    _safe_update_goal_fields(goals_path, goal.id, parsed, root_lock)

            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): {phase}")

            # Generate session log
            log_content = generate_session_log(wt_root, goal, base_commit, test_output)
            session_dir = wt_root / ".ai" / "sessions"
            write_session_log(session_dir, log_content, suffix=goal.id)
            if is_dirty(wt_root):
                commit_all(wt_root, f"devf({goal.id}): {phase} session log")

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


def _run_tests(root: Path, command: str) -> tuple[bool, str]:
    proc = subprocess.run(
        command, cwd=str(root), shell=True, check=False, capture_output=True, text=True,
    )
    output = proc.stdout
    if proc.stderr:
        output = output + "\n" + proc.stderr if output else proc.stderr
    return proc.returncode == 0, output


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

    if outcome.success:
        return outcome, _success_policy_decision(policies, phase, changed_files)

    failure_classification = classify_failure(
        outcome.classification,
        outcome.reason,
        test_output,
    )
    risk_score = compute_risk_score(
        policies.risk,
        phase,
        changed_files,
        failure_classification,
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
) -> PolicyDecision:
    return PolicyDecision(
        policy_version=policies.version,
        failure_classification=None,
        action_taken=ADVANCE_ACTION,
        risk_score=compute_risk_score(policies.risk, phase, changed_files, None),
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


def _run_targeted_pytest(root: Path, test_files: list[str]) -> tuple[bool, str]:
    command = "pytest -q " + " ".join(shlex.quote(path) for path in test_files)
    return _run_tests(root, command)


def _run_targeted_tests(
    root: Path,
    test_files: list[str],
    config: Config | None,
    languages: list[str] | None,
) -> tuple[bool, str]:
    if not config or not config.language_profiles:
        return _run_targeted_pytest(root, test_files)

    resolved_languages = languages or ["python"]
    commands = build_targeted_test_commands(config, resolved_languages, test_files)
    if not commands:
        return _run_targeted_pytest(root, test_files)

    outputs: list[str] = []
    for _, command in commands:
        ok, output = _run_tests(root, command)
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
    goal: Goal,
    changes: dict[str, str] | list[object],
    stage: str | None,
    contract_file: str | None = None,
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
    if "timeout" in text or "flaky" in text:
        return "failed-flaky", "tests failed (possible flake/timeout)"
    if "assertionerror" in text or "=== failures ===" in text or " failed " in text:
        return "failed-impl", "tests failed (implementation mismatch)"
    return "failed-unknown", "tests failed (unclassified)"


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
