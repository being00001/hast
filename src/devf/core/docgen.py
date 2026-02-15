"""Documentation control plane generators."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml

from devf.core.analysis import build_symbol_map, format_symbol_map
from devf.core.goals import Goal, iter_goals, load_goals
from devf.core.mermaid import render_mermaid_docs
from devf.core.metrics import build_metrics_report


@dataclass(frozen=True)
class DocsGenerateResult:
    generated_at: str
    output_dir: Path
    generated_paths: list[Path]
    stale_paths: list[Path]
    stale_source_paths: list[Path]
    mermaid_scanned_files: int = 0
    mermaid_diagrams_found: int = 0
    mermaid_rendered: int = 0
    mermaid_failed: int = 0
    mermaid_output_dir: Path | None = None
    mermaid_index_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def generate_docs(
    root: Path,
    *,
    window_days: int = 14,
    render_mermaid: bool = True,
) -> DocsGenerateResult:
    output_dir = root / "docs" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "codemap": output_dir / "codemap.md",
        "traceability": output_dir / "goal_traceability.md",
        "decision_summary": output_dir / "decision_summary.md",
        "quality_security": output_dir / "quality_security_report.md",
    }
    stale_paths, stale_source_paths = _detect_stale_docs(root, list(outputs.values()))
    generated_at = datetime.now().astimezone().isoformat()

    outputs["codemap"].write_text(_render_codemap(root, generated_at), encoding="utf-8")
    outputs["traceability"].write_text(_render_goal_traceability(root, generated_at), encoding="utf-8")
    outputs["decision_summary"].write_text(
        _render_decision_summary(root, generated_at), encoding="utf-8"
    )
    outputs["quality_security"].write_text(
        _render_quality_security(root, generated_at, window_days=window_days),
        encoding="utf-8",
    )

    generated_paths = [
        path.relative_to(root) for path in sorted(outputs.values(), key=lambda item: item.name)
    ]
    warnings: list[str] = []
    mermaid_scanned_files = 0
    mermaid_diagrams_found = 0
    mermaid_rendered = 0
    mermaid_failed = 0
    mermaid_output_dir: Path | None = None
    mermaid_index_path: Path | None = None

    if render_mermaid:
        mermaid_result = render_mermaid_docs(root)
        mermaid_scanned_files = mermaid_result.scanned_files
        mermaid_diagrams_found = mermaid_result.diagrams_found
        mermaid_rendered = mermaid_result.rendered
        mermaid_failed = mermaid_result.failed
        mermaid_output_dir = mermaid_result.output_dir
        mermaid_index_path = mermaid_result.index_path
        warnings.extend(mermaid_result.warnings)

    return DocsGenerateResult(
        generated_at=generated_at,
        output_dir=output_dir.relative_to(root),
        generated_paths=generated_paths,
        stale_paths=stale_paths,
        stale_source_paths=stale_source_paths,
        mermaid_scanned_files=mermaid_scanned_files,
        mermaid_diagrams_found=mermaid_diagrams_found,
        mermaid_rendered=mermaid_rendered,
        mermaid_failed=mermaid_failed,
        mermaid_output_dir=mermaid_output_dir,
        mermaid_index_path=mermaid_index_path,
        warnings=warnings,
    )


def _render_codemap(root: Path, generated_at: str) -> str:
    symbol_map = build_symbol_map(root)
    body = format_symbol_map(symbol_map).strip()
    if not body:
        body = "# Codebase Map\n(no symbols detected)"
    return (
        "# Generated Codemap\n\n"
        f"- generated_at: `{generated_at}`\n"
        "- source: AST scan of repository\n\n"
        "```text\n"
        f"{body}\n"
        "```\n"
    )


def _render_goal_traceability(root: Path, generated_at: str) -> str:
    goals_path = root / ".ai" / "goals.yaml"
    goals = load_goals(goals_path) if goals_path.exists() else []

    lines = [
        "# Goal Traceability",
        "",
        f"- generated_at: `{generated_at}`",
        "",
        "| goal_id | status | state | contract | tests | decision | depends_on | commit |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for node in iter_goals(goals):
        goal = node.goal
        contract = goal.contract_file or "-"
        tests = ", ".join(goal.test_files) if goal.test_files else "-"
        decision = goal.decision_file or "-"
        depends_on = ", ".join(goal.depends_on) if goal.depends_on else "-"
        commit = _goal_commit_hint(root, goal)
        lines.append(
            f"| {goal.id} | {goal.status} | {goal.state or '-'} | {contract} | "
            f"{tests} | {decision} | {depends_on} | {commit} |"
        )
    if not goals:
        lines.append("| - | - | - | - | - | - | - | - |")
    return "\n".join(lines) + "\n"


def _goal_commit_hint(root: Path, goal: Goal) -> str:
    related_paths: list[str] = []
    for item in (goal.spec_file, goal.contract_file, goal.decision_file):
        if item:
            related_paths.append(item)
    related_paths.extend(goal.test_files)
    if not related_paths:
        return "-"

    cmd = [
        "git",
        "log",
        "-1",
        "--date=short",
        "--pretty=format:%h %ad %s",
        "--",
        *related_paths,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return "-"
    text = (proc.stdout or "").strip()
    return text if text else "-"


def _render_decision_summary(root: Path, generated_at: str) -> str:
    decisions_dir = root / ".ai" / "decisions"
    rows: list[dict] = []
    skipped_files: list[str] = []
    if decisions_dir.exists():
        for file_path in sorted(decisions_dir.glob("*.yaml")):
            data = _safe_read_yaml_mapping(file_path)
            if data is None:
                skipped_files.append(file_path.name)
                continue
            payload = data.get("decision", data)
            if not isinstance(payload, dict):
                skipped_files.append(file_path.name)
                continue
            rows.append(
                {
                    "decision_id": str(payload.get("decision_id") or file_path.stem),
                    "goal_id": str(payload.get("goal_id") or "-"),
                    "status": str(payload.get("status") or "-"),
                    "owner": str(payload.get("owner") or "-"),
                    "selected": str(payload.get("selected_alternative") or "-"),
                    "updated_at": str(payload.get("updated_at") or payload.get("created_at") or "-"),
                }
            )

    status_counts = Counter(row["status"] for row in rows)
    evidence_counts = _decision_evidence_counts(root)

    lines = [
        "# Decision Summary",
        "",
        f"- generated_at: `{generated_at}`",
        f"- decision_files: `{len(rows)}`",
        f"- accepted: `{status_counts.get('accepted', 0)}`",
        f"- proposed: `{status_counts.get('proposed', 0)}`",
        "",
        "## Decision Files",
        "",
        "| decision_id | goal_id | status | owner | selected | updated_at |",
        "|---|---|---|---|---|---|",
    ]
    if rows:
        for row in rows:
            lines.append(
                f"| {row['decision_id']} | {row['goal_id']} | {row['status']} | "
                f"{row['owner']} | {row['selected']} | {row['updated_at']} |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Evidence Events",
            "",
            f"- decision-accepted: `{evidence_counts.get('decision-accepted', 0)}`",
            f"- decision-blocked: `{evidence_counts.get('decision-blocked', 0)}`",
            f"- decision-spike: `{evidence_counts.get('decision-spike', 0)}`",
        ]
    )
    if skipped_files:
        lines.extend(
            [
                "",
                "## Skipped Files",
                "",
                "- The following decision files were ignored due to parse/shape errors:",
            ]
        )
        for name in skipped_files:
            lines.append(f"- {name}")
    return "\n".join(lines) + "\n"


def _decision_evidence_counts(root: Path) -> Counter[str]:
    path = root / ".ai" / "decisions" / "evidence.jsonl"
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        classification = row.get("classification")
        if isinstance(classification, str) and classification:
            counts[classification] += 1
    return counts


def _render_quality_security(root: Path, generated_at: str, *, window_days: int) -> str:
    report = build_metrics_report(root, window_days)
    recent_rows = _load_recent_run_rows(root, window_days)
    gate_fail_counts = _collect_gate_fail_counts(recent_rows)

    lines = [
        "# Quality & Security Report",
        "",
        f"- generated_at: `{generated_at}`",
        f"- window_days: `{window_days}`",
        "",
        "## Core Metrics",
        "",
        f"- evidence_rows: `{report.total_rows}`",
        f"- goals_seen: `{report.goals_seen}`",
        f"- success_rows: `{report.success_rows}`",
        f"- failure_rows: `{report.failure_rows}`",
        f"- avg_risk_score: `{report.avg_risk_score}`",
        "",
        "## Failure Classifications",
        "",
    ]
    if report.failure_class_counts:
        for key, value in sorted(report.failure_class_counts.items()):
            lines.append(f"- {key}: `{value}`")
    else:
        lines.append("- (none)")
    lines.extend(["", "## Gate Failed Checks", ""])
    if gate_fail_counts:
        for name, count in sorted(gate_fail_counts.items()):
            lines.append(f"- {name}: `{count}`")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _load_recent_run_rows(root: Path, window_days: int) -> list[dict]:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return []

    threshold = datetime.now().astimezone() - timedelta(days=window_days)
    rows: list[dict] = []
    for evidence_file in sorted(runs_dir.glob("*/evidence.jsonl")):
        for line in evidence_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ts_raw = row.get("timestamp")
            if not isinstance(ts_raw, str):
                continue
            ts = _parse_iso(ts_raw)
            if ts is None or ts < threshold:
                continue
            rows.append(row)
    return rows


def _collect_gate_fail_counts(rows: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        checks = row.get("gate_failed_checks")
        if not isinstance(checks, list):
            continue
        for item in checks:
            if isinstance(item, str) and item.strip():
                counts[item.strip()] += 1
    return counts


def _detect_stale_docs(root: Path, outputs: list[Path]) -> tuple[list[Path], list[Path]]:
    sources = _collect_stale_source_candidates(root)
    if not sources:
        return [], []

    latest_source_mtime = _latest_mtime(sources)
    if latest_source_mtime is None:
        return [], []

    existing_outputs: list[Path] = [output for output in outputs if output.exists()]
    if not existing_outputs:
        return [], []

    stale: list[Path] = []
    for output in existing_outputs:
        if output.stat().st_mtime < latest_source_mtime:
            stale.append(output.relative_to(root))

    if not stale:
        return [], []

    oldest_output_mtime = min(output.stat().st_mtime for output in existing_outputs)
    stale_sources: list[Path] = []
    for source in sources:
        try:
            source_mtime = source.stat().st_mtime
        except FileNotFoundError:
            continue
        if source_mtime > oldest_output_mtime:
            stale_sources.append(source.relative_to(root))
    return sorted(stale), sorted(stale_sources)


def _collect_stale_source_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in [
        root / ".ai" / "goals.yaml",
        root / ".ai" / "decisions" / "evidence.jsonl",
    ]:
        if path.exists():
            candidates.append(path)

    decisions_dir = root / ".ai" / "decisions"
    if decisions_dir.exists():
        candidates.extend(sorted(decisions_dir.glob("*.yaml")))

    runs_dir = root / ".ai" / "runs"
    if runs_dir.exists():
        candidates.extend(sorted(runs_dir.glob("*/evidence.jsonl")))

    for base in ("src", "tests"):
        base_dir = root / base
        if not base_dir.exists():
            continue
        candidates.extend(base_dir.rglob("*.py"))
        candidates.extend(base_dir.rglob("*.rs"))

    for name in ("pyproject.toml", "Cargo.toml", "Cargo.lock"):
        path = root / name
        if path.exists():
            candidates.append(path)

    return candidates


def _latest_mtime(candidates: list[Path]) -> float | None:
    mtimes: list[float] = []
    for path in candidates:
        try:
            mtimes.append(path.stat().st_mtime)
        except FileNotFoundError:
            continue
    if not mtimes:
        return None
    return max(mtimes)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _safe_read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    return data
