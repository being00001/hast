"""Parallel spike runner for decision alternatives."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

from hast.core.decision import load_decision_ticket, save_decision_ticket
from hast.core.errors import DevfError
from hast.core.spike_policy import SpikePolicy, load_spike_policy
from hast.utils.git import worktree_create, worktree_remove


@dataclass(frozen=True)
class SpikeAlternativeResult:
    alternative_id: str
    command: str
    passed: bool
    exit_code: int
    duration_ms: int
    changed_files: int
    added_lines: int
    deleted_lines: int
    diff_lines: int
    comparison_rank: int
    output_file: str
    metadata_file: str


@dataclass(frozen=True)
class SpikeRunResult:
    decision_id: str
    goal_id: str
    summary_path: Path
    spike_dir: Path
    alternatives: list[SpikeAlternativeResult]
    winner_id: str | None
    winner_reason: str
    winner_reason_code: str
    winner_reason_detail: str
    winner_vs_runner_up: dict[str, object] | None
    escalated: bool
    evidence_path: Path | None


@dataclass(frozen=True)
class _PreparedAlternative:
    alternative_id: str
    command: str
    file_slug: str
    worktree_goal_id: str
    worktree_path: Path


@dataclass(frozen=True)
class _CommandResult:
    exit_code: int
    output: str
    duration_ms: int
    changed_files: int
    added_lines: int
    deleted_lines: int
    diff_lines: int


def run_decision_spikes(
    *,
    root: Path,
    decision_file: Path,
    parallel: int = 2,
    command_template: str = "true",
    backend: str = "auto",
    actor: str = "orchestrator",
    log_evidence: bool = True,
) -> SpikeRunResult:
    """Run per-alternative spikes in isolated worktrees and persist artifacts."""
    if parallel < 1:
        raise DevfError("parallel must be >= 1")
    backend_value = backend.strip().lower()
    if backend_value not in {"auto", "thread", "ray"}:
        raise DevfError("backend must be one of: auto, thread, ray")

    ticket = load_decision_ticket(decision_file)
    policy = load_spike_policy(root)
    decision_id = str(ticket["decision_id"])
    goal_id = str(ticket["goal_id"])
    alternatives = [str(row["id"]) for row in list(ticket.get("alternatives") or [])]
    if not alternatives:
        raise DevfError("decision.alternatives must contain at least 1 item")

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%dT%H%M%S%f%z")
    spike_dir = root / ".ai" / "decisions" / "spikes" / _safe_token(decision_id) / stamp
    spike_dir.mkdir(parents=True, exist_ok=True)

    prepared: list[_PreparedAlternative] = []
    created_goal_ids: list[str] = []
    try:
        for alt_id in alternatives:
            goal_token = _safe_token(alt_id, fallback="alt")
            worktree_goal_id = f"spike-{_safe_token(decision_id)}-{goal_token}-{stamp}"
            worktree_path = worktree_create(root, worktree_goal_id)
            created_goal_ids.append(worktree_goal_id)
            command = _render_command(command_template, alt_id, decision_id, goal_id)
            prepared.append(
                _PreparedAlternative(
                    alternative_id=alt_id,
                    command=command,
                    file_slug=goal_token,
                    worktree_goal_id=worktree_goal_id,
                    worktree_path=worktree_path,
                )
            )

        command_results = _run_commands(prepared, parallel=parallel, backend=backend_value)
    finally:
        for worktree_goal_id in created_goal_ids:
            worktree_remove(root, worktree_goal_id)

    rows: list[SpikeAlternativeResult] = []
    for item in prepared:
        run_result = command_results[item.alternative_id]
        output_file = spike_dir / f"{item.file_slug}.log"
        metadata_file = spike_dir / f"{item.file_slug}.json"
        output_file.write_text(run_result.output, encoding="utf-8")
        alt_row = {
            "decision_id": decision_id,
            "goal_id": goal_id,
            "alternative_id": item.alternative_id,
            "command": item.command,
            "passed": run_result.exit_code == 0,
            "exit_code": run_result.exit_code,
            "duration_ms": run_result.duration_ms,
            "changed_files": run_result.changed_files,
            "added_lines": run_result.added_lines,
            "deleted_lines": run_result.deleted_lines,
            "diff_lines": run_result.diff_lines,
            "output_file": _relpath_or_abs(root, output_file),
            "worktree_goal_id": item.worktree_goal_id,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        metadata_file.write_text(
            json.dumps(alt_row, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        rows.append(
            SpikeAlternativeResult(
                alternative_id=item.alternative_id,
                command=item.command,
                passed=(run_result.exit_code == 0),
                exit_code=run_result.exit_code,
                duration_ms=run_result.duration_ms,
                changed_files=run_result.changed_files,
                added_lines=run_result.added_lines,
                deleted_lines=run_result.deleted_lines,
                diff_lines=run_result.diff_lines,
                comparison_rank=0,
                output_file=_relpath_or_abs(root, output_file),
                metadata_file=_relpath_or_abs(root, metadata_file),
            )
        )

    ranked = sorted(rows, key=lambda row: _comparison_sort_key(row, policy))
    rank_by_id = {row.alternative_id: idx + 1 for idx, row in enumerate(ranked)}
    rows = [
        SpikeAlternativeResult(
            alternative_id=row.alternative_id,
            command=row.command,
            passed=row.passed,
            exit_code=row.exit_code,
            duration_ms=row.duration_ms,
            changed_files=row.changed_files,
            added_lines=row.added_lines,
            deleted_lines=row.deleted_lines,
            diff_lines=row.diff_lines,
            comparison_rank=rank_by_id.get(row.alternative_id, 0),
            output_file=row.output_file,
            metadata_file=row.metadata_file,
        )
        for row in rows
    ]
    ranked = sorted(rows, key=lambda row: _comparison_sort_key(row, policy))
    winner_id = ranked[0].alternative_id if ranked and ranked[0].passed else None
    (
        winner_reason,
        winner_reason_code,
        winner_reason_detail,
        winner_vs_runner_up,
    ) = _build_winner_reason(ranked, winner_id, policy)
    escalated = winner_id is None

    summary = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "decision_id": decision_id,
        "goal_id": goal_id,
        "command_template": command_template,
        "parallel": parallel,
        "backend": backend_value,
        "policy_version": policy.version,
        "comparison_criteria": policy.comparison_criteria(),
        "winner_id": winner_id,
        "winner_reason": winner_reason,
        "winner_reason_code": winner_reason_code,
        "winner_reason_detail": winner_reason_detail,
        "winner_vs_runner_up": winner_vs_runner_up,
        "escalated": escalated,
        "alternatives": [
            {
                "alternative_id": row.alternative_id,
                "passed": row.passed,
                "exit_code": row.exit_code,
                "duration_ms": row.duration_ms,
                "changed_files": row.changed_files,
                "added_lines": row.added_lines,
                "deleted_lines": row.deleted_lines,
                "diff_lines": row.diff_lines,
                "comparison_rank": row.comparison_rank,
                "metadata_file": row.metadata_file,
                "output_file": row.output_file,
            }
            for row in sorted(rows, key=lambda item: item.comparison_rank or 9999)
        ],
    }
    summary_path = spike_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    refs = list(ticket.get("evidence_refs") or [])
    new_ref = _relpath_or_abs(root, summary_path)
    if new_ref not in refs:
        refs.append(new_ref)
    ticket["evidence_refs"] = refs
    ticket["updated_at"] = datetime.now().astimezone().isoformat()
    save_decision_ticket(decision_file, ticket)

    evidence_path: Path | None = None
    if log_evidence:
        evidence_path = append_decision_spike_evidence(
            root=root,
            decision_file=decision_file,
            decision_id=decision_id,
            goal_id=goal_id,
            winner_id=winner_id,
            winner_reason=winner_reason,
            winner_reason_code=winner_reason_code,
            winner_reason_detail=winner_reason_detail,
            winner_vs_runner_up=winner_vs_runner_up,
            escalated=escalated,
            alternatives=rows,
            summary_path=summary_path,
            actor=actor,
            policy=policy,
        )

    return SpikeRunResult(
        decision_id=decision_id,
        goal_id=goal_id,
        summary_path=summary_path,
        spike_dir=spike_dir,
        alternatives=rows,
        winner_id=winner_id,
        winner_reason=winner_reason,
        winner_reason_code=winner_reason_code,
        winner_reason_detail=winner_reason_detail,
        winner_vs_runner_up=winner_vs_runner_up,
        escalated=escalated,
        evidence_path=evidence_path,
    )


def append_decision_spike_evidence(
    *,
    root: Path,
    decision_file: Path,
    decision_id: str,
    goal_id: str,
    winner_id: str | None,
    winner_reason: str,
    winner_reason_code: str,
    winner_reason_detail: str,
    winner_vs_runner_up: dict[str, object] | None,
    escalated: bool,
    alternatives: list[SpikeAlternativeResult],
    summary_path: Path,
    actor: str,
    policy: SpikePolicy,
) -> Path:
    evidence_path = root / ".ai" / "decisions" / "evidence.jsonl"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    ranking_rows = sorted(alternatives, key=lambda alt: alt.comparison_rank or 9999)
    winner_rank = None
    if winner_id:
        for row in ranking_rows:
            if row.alternative_id == winner_id:
                winner_rank = row.comparison_rank
                break
    winner_score = (
        float(max(1, len(ranking_rows) - int(winner_rank or 0) + 1))
        if winner_rank is not None
        else 0.0
    )

    row = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event_type": "decision_spike",
        "decision_id": decision_id,
        "goal_id": goal_id,
        "decision_file": _relpath_or_abs(root, decision_file),
        "winner_id": winner_id,
        "winner_reason": winner_reason,
        "winner_reason_code": winner_reason_code,
        "winner_reason_detail": winner_reason_detail,
        "winner_vs_runner_up": winner_vs_runner_up,
        "winner_eligible": winner_id is not None,
        "winner_score": winner_score,
        "policy_version": policy.version,
        "comparison_criteria": policy.comparison_criteria(),
        "ranking": [
            {
                "alternative_id": alt.alternative_id,
                "total_score": float(max(1, len(ranking_rows) - alt.comparison_rank + 1)),
                "eligible": alt.passed,
                "failed_criteria": [] if alt.passed else ["spike_failed"],
                "diff_lines": alt.diff_lines,
                "changed_files": alt.changed_files,
                "duration_ms": alt.duration_ms,
                "comparison_rank": alt.comparison_rank,
            }
            for alt in ranking_rows
        ],
        "status": "spike_complete",
        "classification": "decision-spike-escalated" if escalated else "decision-spike-ready",
        "action_taken": "escalate" if escalated else "advance",
        "actor": actor,
        "run_id": None,
        "evidence_refs": [_relpath_or_abs(root, summary_path)],
        "schema_version": "decision_evidence.v1",
    }
    with evidence_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return evidence_path


def _run_commands(
    prepared: list[_PreparedAlternative],
    *,
    parallel: int,
    backend: str,
) -> dict[str, _CommandResult]:
    if backend == "ray":
        return _run_commands_ray(prepared, parallel=parallel)
    if backend == "thread":
        return _run_commands_thread(prepared, parallel=parallel)

    # auto mode
    try:
        import ray  # type: ignore[import-not-found]

        if ray is None:
            return _run_commands_thread(prepared, parallel=parallel)
        return _run_commands_ray(prepared, parallel=parallel)
    except Exception:
        return _run_commands_thread(prepared, parallel=parallel)


def _run_commands_thread(
    prepared: list[_PreparedAlternative],
    *,
    parallel: int,
) -> dict[str, _CommandResult]:
    if not prepared:
        return {}

    results: dict[str, _CommandResult] = {}
    workers = max(1, min(parallel, len(prepared)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_command, item.command, item.worktree_path): item
            for item in prepared
        }
        for future in as_completed(future_map):
            item = future_map[future]
            results[item.alternative_id] = future.result()
    return results


def _run_commands_ray(
    prepared: list[_PreparedAlternative],
    *,
    parallel: int,
) -> dict[str, _CommandResult]:
    try:
        import ray  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - import availability depends on env
        raise DevfError("ray backend requested but ray is not installed") from exc

    if not ray.is_initialized():  # pragma: no cover - depends on runtime
        ray.init(
            local_mode=True,
            ignore_reinit_error=True,
            include_dashboard=False,
            num_cpus=max(1, parallel),
        )

    remote_run = ray.remote(_run_command_ray_payload)
    refs = [
        remote_run.remote(item.alternative_id, item.command, str(item.worktree_path))
        for item in prepared
    ]
    payloads = ray.get(refs)
    return {
        str(payload["alternative_id"]): _CommandResult(
            exit_code=int(payload["exit_code"]),
            output=str(payload["output"]),
            duration_ms=int(payload["duration_ms"]),
            changed_files=int(payload["changed_files"]),
            added_lines=int(payload["added_lines"]),
            deleted_lines=int(payload["deleted_lines"]),
            diff_lines=int(payload["diff_lines"]),
        )
        for payload in payloads
    }


def _run_command_ray_payload(alternative_id: str, command: str, cwd: str) -> dict[str, object]:
    result = _run_command(command, Path(cwd))
    return {
        "alternative_id": alternative_id,
        "exit_code": result.exit_code,
        "output": result.output,
        "duration_ms": result.duration_ms,
        "changed_files": result.changed_files,
        "added_lines": result.added_lines,
        "deleted_lines": result.deleted_lines,
        "diff_lines": result.diff_lines,
    }


def _run_command(command: str, cwd: Path) -> _CommandResult:
    start = time.monotonic()
    proc = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    output = (proc.stdout + proc.stderr).strip()
    changed_files, added_lines, deleted_lines, diff_lines = _collect_git_diff_metrics(cwd)
    return _CommandResult(
        exit_code=proc.returncode,
        output=output,
        duration_ms=duration_ms,
        changed_files=changed_files,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        diff_lines=diff_lines,
    )


def _collect_git_diff_metrics(cwd: Path) -> tuple[int, int, int, int]:
    names_proc = subprocess.run(
        ["git", "diff", "--name-only", "--", "."],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    changed_files = len([line for line in names_proc.stdout.splitlines() if line.strip()])

    numstat_proc = subprocess.run(
        ["git", "diff", "--numstat", "--", "."],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    added_lines = 0
    deleted_lines = 0
    for line in numstat_proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_token = parts[0].strip()
        del_token = parts[1].strip()
        if add_token.isdigit():
            added_lines += int(add_token)
        if del_token.isdigit():
            deleted_lines += int(del_token)
    return changed_files, added_lines, deleted_lines, added_lines + deleted_lines


def _comparison_sort_key(
    row: SpikeAlternativeResult,
    policy: SpikePolicy,
) -> tuple[int | str, ...]:
    parts: list[int | str] = [0 if row.passed else 1]
    if policy.prefer_lower_diff_lines:
        parts.append(row.diff_lines)
    if policy.prefer_lower_changed_files:
        parts.append(row.changed_files)
    if policy.include_duration_tiebreaker:
        parts.append(row.duration_ms)
    parts.append(row.alternative_id)
    return tuple(parts)


def _build_winner_reason(
    ranked: list[SpikeAlternativeResult],
    winner_id: str | None,
    policy: SpikePolicy,
) -> tuple[str, str, str, dict[str, object] | None]:
    criteria = policy.comparison_criteria()
    criteria_text = ", ".join(criteria)
    if winner_id is None:
        if not ranked:
            code = "no_alternatives"
            detail = "No alternatives were evaluated."
            return f"why:{code}", code, detail, None
        code = "no_passing"
        detail = "No passing alternatives; escalation required."
        return f"why:{code}", code, detail, None

    winner = ranked[0]
    if len(ranked) < 2:
        code = "single_alternative"
        detail = (
            f"Selected {winner_id}: only alternative evaluated "
            f"(criteria: {criteria_text})."
        )
        return f"why:{code}", code, detail, None

    runner_up = ranked[1]
    deciding = _deciding_criterion(winner, runner_up, policy)
    deciding_code = deciding or "alternative_id"
    winner_vs_runner_up = {
        "criterion": deciding_code,
        "winner_id": winner.alternative_id,
        "runner_up_id": runner_up.alternative_id,
        "winner": _metric_snapshot(winner),
        "runner_up": _metric_snapshot(runner_up),
    }
    if deciding == "passed":
        detail = (
            f"Selected {winner_id}: passed while {runner_up.alternative_id} failed "
            f"(criteria: {criteria_text})."
        )
        return "why:passed", "passed", detail, winner_vs_runner_up
    if deciding == "diff_lines":
        detail = (
            f"Selected {winner_id}: fewer diff_lines "
            f"({winner.diff_lines} < {runner_up.diff_lines}) "
            f"(criteria: {criteria_text})."
        )
        return "why:diff_lines", "diff_lines", detail, winner_vs_runner_up
    if deciding == "changed_files":
        detail = (
            f"Selected {winner_id}: fewer changed_files "
            f"({winner.changed_files} < {runner_up.changed_files}) "
            f"(criteria: {criteria_text})."
        )
        return "why:changed_files", "changed_files", detail, winner_vs_runner_up
    if deciding == "duration_ms":
        detail = (
            f"Selected {winner_id}: lower duration_ms "
            f"({winner.duration_ms} < {runner_up.duration_ms}) "
            f"(criteria: {criteria_text})."
        )
        return "why:duration_ms", "duration_ms", detail, winner_vs_runner_up
    detail = (
        f"Selected {winner_id}: deterministic tie-break on alternative_id "
        f"(criteria: {criteria_text})."
    )
    return "why:alternative_id", "alternative_id", detail, winner_vs_runner_up


def _deciding_criterion(
    winner: SpikeAlternativeResult,
    runner_up: SpikeAlternativeResult,
    policy: SpikePolicy,
) -> str | None:
    if (0 if winner.passed else 1) != (0 if runner_up.passed else 1):
        return "passed"
    if policy.prefer_lower_diff_lines and winner.diff_lines != runner_up.diff_lines:
        return "diff_lines"
    if policy.prefer_lower_changed_files and winner.changed_files != runner_up.changed_files:
        return "changed_files"
    if policy.include_duration_tiebreaker and winner.duration_ms != runner_up.duration_ms:
        return "duration_ms"
    if winner.alternative_id != runner_up.alternative_id:
        return "alternative_id"
    return None


def _metric_snapshot(row: SpikeAlternativeResult) -> dict[str, object]:
    return {
        "alternative_id": row.alternative_id,
        "passed": row.passed,
        "exit_code": row.exit_code,
        "duration_ms": row.duration_ms,
        "changed_files": row.changed_files,
        "diff_lines": row.diff_lines,
        "comparison_rank": row.comparison_rank,
    }


def _render_command(
    command_template: str,
    alternative_id: str,
    decision_id: str,
    goal_id: str,
) -> str:
    try:
        rendered = command_template.format(
            alternative_id=alternative_id,
            decision_id=decision_id,
            goal_id=goal_id,
        )
    except KeyError as exc:
        raise DevfError(
            "invalid command template placeholder; use {alternative_id}, {decision_id}, {goal_id}"
        ) from exc
    rendered = rendered.strip()
    if not rendered:
        raise DevfError("command template rendered empty command")
    return rendered


def _safe_token(value: str, fallback: str = "item") -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-")
    if not token:
        token = fallback
    return token[:64]


def _relpath_or_abs(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
