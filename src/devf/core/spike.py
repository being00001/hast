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

from devf.core.decision import load_decision_ticket, save_decision_ticket
from devf.core.errors import DevfError
from devf.utils.git import worktree_create, worktree_remove


@dataclass(frozen=True)
class SpikeAlternativeResult:
    alternative_id: str
    command: str
    passed: bool
    exit_code: int
    duration_ms: int
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
                output_file=_relpath_or_abs(root, output_file),
                metadata_file=_relpath_or_abs(root, metadata_file),
            )
        )

    ranked = sorted(rows, key=lambda row: (0 if row.passed else 1, row.alternative_id))
    winner_id = ranked[0].alternative_id if ranked and ranked[0].passed else None
    escalated = winner_id is None

    summary = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "decision_id": decision_id,
        "goal_id": goal_id,
        "command_template": command_template,
        "parallel": parallel,
        "backend": backend_value,
        "winner_id": winner_id,
        "escalated": escalated,
        "alternatives": [
            {
                "alternative_id": row.alternative_id,
                "passed": row.passed,
                "exit_code": row.exit_code,
                "duration_ms": row.duration_ms,
                "metadata_file": row.metadata_file,
                "output_file": row.output_file,
            }
            for row in rows
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
            escalated=escalated,
            alternatives=rows,
            summary_path=summary_path,
            actor=actor,
        )

    return SpikeRunResult(
        decision_id=decision_id,
        goal_id=goal_id,
        summary_path=summary_path,
        spike_dir=spike_dir,
        alternatives=rows,
        winner_id=winner_id,
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
    escalated: bool,
    alternatives: list[SpikeAlternativeResult],
    summary_path: Path,
    actor: str,
) -> Path:
    evidence_path = root / ".ai" / "decisions" / "evidence.jsonl"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event_type": "decision_spike",
        "decision_id": decision_id,
        "goal_id": goal_id,
        "decision_file": _relpath_or_abs(root, decision_file),
        "winner_id": winner_id,
        "winner_eligible": winner_id is not None,
        "winner_score": 0.0,
        "ranking": [
            {
                "alternative_id": alt.alternative_id,
                "total_score": 0.0,
                "eligible": alt.passed,
                "failed_criteria": [] if alt.passed else ["spike_failed"],
            }
            for alt in alternatives
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
    return _CommandResult(exit_code=proc.returncode, output=output, duration_ms=duration_ms)


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
