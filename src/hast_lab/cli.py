"""hast-lab CLI: scenario playground for dogfooding hast workflows."""

from __future__ import annotations

from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import threading
import time
import contextlib
from typing import Any

import click
import yaml

from hast.core.auto import run_auto
from hast.core.errors import DevfError
from hast.core.init_project import init_project
from hast.core.runner import GoalRunner, RunnerResult


@click.group()
def main() -> None:
    """hast-lab CLI."""


def _emit_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@main.command("new")
@click.argument("name")
@click.option(
    "--dir",
    "base_dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=Path.cwd,
    show_default="current directory",
    help="Parent directory where the lab project will be created.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def new_command(name: str, base_dir: Path, json_output: bool) -> None:
    """Create a new lab project scaffold for running hast scenarios."""
    safe_name = name.strip()
    if not safe_name:
        raise click.ClickException("name must be non-empty")
    project_root = (base_dir / safe_name).resolve()
    if project_root.exists() and any(project_root.iterdir()):
        raise click.ClickException(f"target directory is not empty: {project_root.as_posix()}")

    project_root.mkdir(parents=True, exist_ok=True)
    _write_project_scaffold(project_root)
    _git_init_and_commit(project_root, "init lab project scaffold")

    payload = {
        "project_root": project_root.as_posix(),
        "name": safe_name,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(f"Lab project created: {project_root.as_posix()}")
    click.echo("Next:")
    click.echo(f"  hast-lab run protocol-roundtrip --project {project_root.as_posix()}")
    click.echo(f"  hast-lab report --project {project_root.as_posix()}")


@main.command("run")
@click.argument(
    "scenario",
    type=click.Choice(["protocol-roundtrip", "no-progress"], case_sensitive=False),
)
@click.option(
    "--project",
    "project_root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    required=True,
    help="Path to lab project root.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def run_command(scenario: str, project_root: Path, json_output: bool) -> None:
    """Run a scenario in a lab project."""
    root = project_root.resolve()
    if not (root / ".ai").exists():
        raise click.ClickException(f"not a lab/hast project: {root.as_posix()}")

    scenario_token = scenario.strip().lower()
    if scenario_token == "protocol-roundtrip":
        result = _run_protocol_roundtrip(root)
    elif scenario_token == "no-progress":
        result = _run_no_progress(root)
    else:  # pragma: no cover - click choice should prevent this
        raise click.ClickException(f"unsupported scenario: {scenario}")

    run_file = _write_lab_run_record(root, scenario_token, result)
    payload = dict(result)
    payload["run_record"] = run_file.as_posix()

    if json_output:
        _emit_json(payload)
        raise SystemExit(0 if bool(result.get("success")) else 1)

    click.echo(
        f"Scenario {scenario_token}: success={result.get('success')} "
        f"exit_code={result.get('exit_code')} classification={result.get('classification')}"
    )
    click.echo(f"Run record: {run_file.as_posix()}")
    if isinstance(result.get("recommended_actions"), list):
        for action in result["recommended_actions"][:5]:
            click.echo(f"  - {action}")
    raise SystemExit(0 if bool(result.get("success")) else 1)


@main.command("report")
@click.option(
    "--project",
    "project_root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    required=True,
    help="Path to lab project root.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def report_command(project_root: Path, json_output: bool) -> None:
    """Summarize scenario run records."""
    root = project_root.resolve()
    runs_dir = root / ".lab" / "runs"
    records: list[dict[str, Any]] = []
    if runs_dir.exists():
        for path in sorted(runs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                records.append(payload)

    total = len(records)
    success = sum(1 for row in records if bool(row.get("success")))
    failed = total - success
    by_scenario: dict[str, int] = {}
    for row in records:
        key = str(row.get("scenario") or "unknown")
        by_scenario[key] = by_scenario.get(key, 0) + 1

    payload = {
        "project_root": root.as_posix(),
        "total_runs": total,
        "success_runs": success,
        "failed_runs": failed,
        "by_scenario": by_scenario,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(f"Lab report: {root.as_posix()}")
    click.echo(f"Total runs: {total} (success={success}, failed={failed})")
    if by_scenario:
        click.echo("By scenario:")
        for key, count in sorted(by_scenario.items()):
            click.echo(f"  - {key}: {count}")
    else:
        click.echo("No run records yet.")


def _write_project_scaffold(root: Path) -> None:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / ".lab" / "runs").mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "from app import VALUE\n\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    (root / ".lab" / "runs" / ".gitkeep").write_text("", encoding="utf-8")
    (root / ".lab" / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "name": root.name,
                "created_at": datetime.now().astimezone().isoformat(),
                "default_scenario": "protocol-roundtrip",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        "\n".join(
            [
                ".lab/runs/*.json",
                ".worktrees/",
                "__pycache__/",
                ".pytest_cache/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    init_project(root)
    (root / ".ai" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "test_command": "PYTHONPATH=. pytest -q",
                "ai_tool": "echo {prompt}",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / ".ai" / "goals.yaml").write_text(
        yaml.safe_dump(
            {
                "goals": [
                    {
                        "id": "G_PILOT",
                        "title": "Protocol roundtrip pilot",
                        "status": "active",
                        "phase": "implement",
                        "tool": "langgraph",
                        "allowed_changes": ["app.py"],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / ".ai" / "policies" / "protocol_adapter_policy.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "v1",
                "enabled_adapters": ["langgraph", "openhands"],
                "default_export_context_format": "pack",
                "include_context_by_default": False,
                "include_prompt_by_default": True,
                "max_context_chars": 200000,
                "require_goal_exists": True,
                "result_inbox_dir": ".ai/protocols/inbox",
                "processed_results_dir": ".ai/protocols/processed",
                "poll_interval_seconds": 1,
                "max_wait_seconds": 30,
                "require_packet_id_match": True,
                "archive_consumed_packets": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _git_init_and_commit(root: Path, message: str) -> None:
    _run_cmd(["git", "init"], root)
    _run_cmd(["git", "config", "user.name", "hast-lab"], root)
    _run_cmd(["git", "config", "user.email", "hast-lab@example.com"], root)
    _run_cmd(["git", "add", "-A"], root)
    _run_cmd(["git", "commit", "-m", message], root)


def _run_cmd(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise click.ClickException(stderr or f"command failed: {' '.join(cmd)}")


def _run_protocol_roundtrip(root: Path) -> dict[str, Any]:
    _prepare_protocol_roundtrip(root)
    goal_id = "G_PILOT"
    worker = _ProtocolMockWorker(root=root, goal_id=goal_id, write_value=2, timeout_seconds=45)
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    started = time.time()
    auto_logs = ""
    try:
        exit_code, auto_logs = _run_auto_captured(
            root=root,
            goal_id=goal_id,
            recursive=False,
            dry_run=False,
            explain=False,
            tool_name="langgraph",
            parallelism=1,
            preflight=True,
        )
    except DevfError as exc:
        exit_code = 1
        worker.error = str(exc)
    thread.join(timeout=50)
    elapsed = int((time.time() - started) * 1000)

    evidence = _latest_evidence_row(root)
    classification = str(evidence.get("classification") or "") if evidence else ""
    success = bool(evidence.get("success")) if evidence else (exit_code == 0 and worker.processed)
    actions = []
    if not success:
        actions.append("run `hast sim G_PILOT --run-tests` in the lab project")
        actions.append("run `hast doctor` in the lab project")
    else:
        actions.append("run `hast-lab report --project <path>` to view aggregate results")

    return {
        "scenario": "protocol-roundtrip",
        "project_root": root.as_posix(),
        "goal_id": goal_id,
        "exit_code": exit_code,
        "success": success,
        "classification": classification,
        "worker_processed": worker.processed,
        "worker_error": worker.error,
        "auto_logs": auto_logs[-2000:] if auto_logs else "",
        "duration_ms": elapsed,
        "recommended_actions": actions,
    }


def _run_no_progress(root: Path) -> dict[str, Any]:
    _prepare_no_progress(root)
    goal_id = "G_PILOT"
    runner = _NoopRunner()
    started = time.time()
    auto_logs = ""
    try:
        exit_code, auto_logs = _run_auto_captured(
            root=root,
            goal_id=goal_id,
            recursive=False,
            dry_run=False,
            explain=False,
            tool_name=None,
            parallelism=1,
            preflight=True,
            runner=runner,
        )
    except DevfError as exc:
        exit_code = 1
        return {
            "scenario": "no-progress",
            "project_root": root.as_posix(),
            "goal_id": goal_id,
            "exit_code": exit_code,
            "success": False,
            "classification": "error",
            "worker_processed": False,
            "worker_error": str(exc),
            "auto_logs": auto_logs[-2000:] if auto_logs else "",
            "duration_ms": int((time.time() - started) * 1000),
            "recommended_actions": [
                "run `hast doctor` in the lab project",
                "run `hast sim G_PILOT --run-tests` in the lab project",
            ],
        }

    evidence = _latest_evidence_row(root)
    classification = str(evidence.get("classification") or "") if evidence else ""
    success = bool(evidence.get("success")) if evidence else False
    attempts = int(evidence.get("attempt") or 0) if evidence else 0
    actions = [
        'run `hast explore "<unclear point>"` before retry',
        "tighten allowed_changes/acceptance and rerun",
        "try `hast retry G_PILOT --no-run` after updating goal intent",
    ]
    return {
        "scenario": "no-progress",
        "project_root": root.as_posix(),
        "goal_id": goal_id,
        "exit_code": exit_code,
        "success": success,
        "classification": classification,
        "worker_processed": False,
        "worker_error": None,
        "auto_logs": auto_logs[-2000:] if auto_logs else "",
        "attempts": attempts,
        "duration_ms": int((time.time() - started) * 1000),
        "recommended_actions": actions,
    }


def _latest_evidence_row(root: Path) -> dict[str, Any] | None:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return None
    evidence_files = sorted(runs_dir.glob("*/evidence.jsonl"))
    if not evidence_files:
        return None
    latest = evidence_files[-1]
    lines = [line.strip() for line in latest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_lab_run_record(root: Path, scenario: str, payload: dict[str, Any]) -> Path:
    ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    out = root / ".lab" / "runs" / f"{ts}_{scenario}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _prepare_protocol_roundtrip(root: Path) -> None:
    _write_lab_goal(
        root,
        tool="langgraph",
        test_command="PYTHONPATH=. pytest -q",
        max_retries=2,
    )
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_if_needed(root, "lab scenario: protocol-roundtrip reset")


def _prepare_no_progress(root: Path) -> None:
    _write_lab_goal(
        root,
        tool=None,
        test_command="PYTHONPATH=. pytest -q",
        max_retries=2,
    )
    # Make baseline green so "no file changes" surfaces as the primary failure.
    (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _commit_if_needed(root, "lab scenario: no-progress reset")


def _write_lab_goal(
    root: Path,
    *,
    tool: str | None,
    test_command: str,
    max_retries: int,
) -> None:
    config_path = root / ".ai" / "config.yaml"
    config_payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config_payload, dict):
        config_payload = {}
    config_payload["test_command"] = test_command
    config_payload["ai_tool"] = "echo {prompt}"
    config_payload["max_retries"] = max_retries
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    goal_payload: dict[str, Any] = {
        "id": "G_PILOT",
        "title": "Protocol roundtrip pilot" if tool == "langgraph" else "No progress pilot",
        "status": "active",
        "phase": "implement",
        "allowed_changes": ["app.py"],
    }
    if tool:
        goal_payload["tool"] = tool
    goals_yaml = {"goals": [goal_payload]}
    (root / ".ai" / "goals.yaml").write_text(
        yaml.safe_dump(goals_yaml, sort_keys=False),
        encoding="utf-8",
    )


def _commit_if_needed(root: Path, message: str) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise click.ClickException("failed to inspect git status")
    if not status.stdout.strip():
        return
    _run_cmd(["git", "add", "-A"], root)
    _run_cmd(["git", "commit", "-m", message], root)


def _run_auto_captured(**kwargs: Any) -> tuple[int, str]:
    """Run auto while capturing stderr so JSON mode stays parseable."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = run_auto(**kwargs)
    return result.exit_code, err.getvalue()


class _ProtocolMockWorker:
    def __init__(self, *, root: Path, goal_id: str, write_value: int, timeout_seconds: int) -> None:
        self.root = root
        self.goal_id = goal_id
        self.write_value = write_value
        self.timeout_seconds = max(1, timeout_seconds)
        self.processed = False
        self.error: str | None = None

    def run(self) -> None:
        deadline = time.time() + self.timeout_seconds
        seen: set[str] = set()
        while time.time() < deadline:
            for workspace_root, packet_path in self._iter_packets():
                key = packet_path.as_posix()
                if key in seen:
                    continue
                seen.add(key)
                packet = self._load_json(packet_path)
                if packet is None:
                    continue
                if str(packet.get("schema_version") or "") != "protocol_task.v1":
                    continue
                goal_obj = packet.get("goal")
                if not isinstance(goal_obj, dict):
                    continue
                packet_goal_id = str(goal_obj.get("goal_id") or "")
                if packet_goal_id != self.goal_id:
                    continue
                target = self._resolve_target(workspace_root, goal_obj)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"VALUE = {self.write_value}\n", encoding="utf-8")
                inbox = workspace_root / ".ai" / "protocols" / "inbox"
                inbox.mkdir(parents=True, exist_ok=True)
                result_packet = {
                    "schema_version": "protocol_result.v1",
                    "adapter": str(packet.get("adapter") or "langgraph"),
                    "packet_id": str(packet.get("packet_id") or ""),
                    "goal_id": packet_goal_id,
                    "run_id": str(packet.get("run_id") or ""),
                    "phase": str(goal_obj.get("phase") or "implement"),
                    "attempt": 1,
                    "success": True,
                    "classification": "complete",
                    "action_taken": "advance",
                    "summary": "hast-lab mock worker applied deterministic edit",
                }
                name = f"result_{result_packet['packet_id'] or int(time.time())}.json"
                (inbox / name).write_text(
                    json.dumps(result_packet, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                self.processed = True
                return
            time.sleep(0.2)
        self.error = "timeout waiting for protocol task packet"

    def _iter_packets(self) -> list[tuple[Path, Path]]:
        locations: list[tuple[Path, Path]] = []
        for workspace_root in self._workspace_roots():
            outbox = workspace_root / ".ai" / "protocols" / "outbox"
            if not outbox.exists():
                continue
            for packet_path in sorted(outbox.glob("*.json")):
                locations.append((workspace_root, packet_path))
        return locations

    def _workspace_roots(self) -> list[Path]:
        roots = [self.root]
        worktrees_root = self.root / ".worktrees"
        if not worktrees_root.exists():
            return roots
        for child in sorted(worktrees_root.iterdir()):
            if child.is_dir() and (child / ".ai").exists():
                roots.append(child)
        return roots

    def _resolve_target(self, workspace_root: Path, goal_obj: dict[str, Any]) -> Path:
        raw = goal_obj.get("allowed_changes")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    return workspace_root / item.strip()
        fallback = workspace_root / "app.py"
        if fallback.exists():
            return fallback
        return workspace_root / "src" / "app.py"

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


class _NoopRunner(GoalRunner):
    """Goal runner that intentionally produces no code changes."""

    def run(
        self,
        root: Path,
        config,
        goal,
        prompt: str,
        tool_name: str | None = None,
    ) -> RunnerResult:
        del root, config, goal, prompt, tool_name
        return RunnerResult(success=True, output="", model_used="lab:no-op")


if __name__ == "__main__":
    main()
