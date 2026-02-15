"""devf CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import click

from devf.core.auto import run_auto
from devf.core.context import build_context, find_root
from devf.core.errors import DevfError
from devf.core.init_project import init_project


@click.group()
def main() -> None:
    """devf CLI."""


def _emit_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@main.command("init")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def init_command(json_output: bool) -> None:
    """Initialize .ai/ with templates."""
    try:
        created = init_project(Path.cwd())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if not created:
        if json_output:
            _emit_json({"changed": False, "created_paths": []})
            return
        click.echo("No changes (already initialized).")
        return

    if json_output:
        _emit_json(
            {
                "changed": True,
                "created_paths": sorted(path.as_posix() for path in created),
            }
        )
        return

    click.echo("Created .ai/")
    click.echo("  ├── config.yaml")
    click.echo("  ├── goals.yaml")
    click.echo("  ├── decisions/")
    click.echo("  ├── proposals/")
    click.echo("  ├── templates/")
    click.echo("  ├── schemas/")
    click.echo("  ├── policies/")
    click.echo("  ├── rules.md")
    click.echo("  ├── sessions/")
    click.echo("  └── handoffs/")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  1. Edit .ai/config.yaml — set test_command and ai_tool.")
    click.echo("  2. Edit .ai/goals.yaml — add your goals.")
    click.echo("  3. Run: devf auto [goal_id]")


@main.command("context")
@click.option(
    "--format",
    "format_name",
    type=click.Choice(["markdown", "plain", "json", "pack"], case_sensitive=False),
    default="markdown",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def context_command(format_name: str, json_output: bool) -> None:
    """Assemble session context."""
    try:
        root = find_root(Path.cwd())
        output = build_context(root, format_name.lower())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        _emit_json(
            {
                "format": format_name.lower(),
                "root": root.as_posix(),
                "output": output,
            }
        )
        return
    click.echo(output)


@main.command("map")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def map_command(json_output: bool) -> None:
    """Generate codebase symbol map."""
    from devf.core.analysis import build_symbol_map, format_symbol_map
    try:
        root = find_root(Path.cwd())
        symbol_map = build_symbol_map(root)
        output = format_symbol_map(symbol_map)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        _emit_json(
            {
                "root": root.as_posix(),
                "symbol_map": symbol_map,
            }
        )
        return
    click.echo(output)


@main.command("handoff")
@click.argument("goal_id", required=False)
@click.option("--stdout", "to_stdout", is_flag=True, help="Print to stdout instead of writing file.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def handoff_command(goal_id: str | None, to_stdout: bool, json_output: bool) -> None:
    """Generate handoff from git history."""
    from devf.core.handoff import generate_handoff

    try:
        root = find_root(Path.cwd())
        content, filename = generate_handoff(root, goal_id)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if to_stdout:
        if json_output:
            _emit_json(
                {
                    "goal_id": goal_id,
                    "written": False,
                    "filename": filename,
                    "content": content,
                }
            )
            return
        click.echo(content)
        return

    path = root / ".ai" / "handoffs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if json_output:
        _emit_json(
            {
                "goal_id": goal_id,
                "written": True,
                "path": path.relative_to(root).as_posix(),
                "filename": filename,
            }
        )
        return
    click.echo(f"Handoff written to .ai/handoffs/{filename}")


@main.command("merge")
@click.argument("goal_id")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def merge_command(goal_id: str, json_output: bool) -> None:
    """Merge a completed goal branch into main."""
    from devf.utils.git import worktree_merge

    try:
        root = find_root(Path.cwd())
        worktree_merge(root, goal_id)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        _emit_json({"goal_id": goal_id, "merged": True})
        return
    click.echo(f"Merged goal/{goal_id} into current branch.")


@main.command("status")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def status_command(json_output: bool) -> None:
    """Show active worktrees and goal progress."""
    from devf.utils.git import worktree_list

    try:
        root = find_root(Path.cwd())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    entries = worktree_list(root)
    if not entries:
        if json_output:
            _emit_json({"entries": []})
            return
        click.echo("No active goal worktrees.")
        return

    if json_output:
        _emit_json({"entries": entries})
        return

    for entry in entries:
        click.echo(f"  {entry['goal_id']}  {entry['head']}  {entry['path']}")


@main.command("metrics")
@click.option(
    "--window",
    "window_days",
    default=7,
    show_default=True,
    type=click.IntRange(min=1, max=365),
    help="Aggregate evidence from the last N days.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def metrics_command(window_days: int, json_output: bool) -> None:
    """Show evidence-based productivity and quality metrics."""
    from devf.core.metrics import build_metrics_report

    try:
        root = find_root(Path.cwd())
        report = build_metrics_report(root, window_days)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json({"window_days": window_days, "report": report.__dict__})
        return

    click.echo(f"Window: last {window_days} day(s)")
    click.echo(f"Evidence rows: {report.total_rows}")
    click.echo(f"Goals seen: {report.goals_seen}")
    click.echo(f"Success rows: {report.success_rows}")
    click.echo(f"Failure rows: {report.failure_rows}")
    click.echo(f"Average risk_score: {report.avg_risk_score}")
    click.echo(f"Feedback notes: {report.feedback_notes}")
    click.echo(f"Feedback backlog accepted: {report.feedback_accepted}")
    click.echo(f"Feedback backlog candidates: {report.feedback_candidates}")
    click.echo(f"Feedback backlog published: {report.feedback_published}")
    click.echo(f"Proposal notes: {report.proposal_notes}")
    click.echo(f"Proposal backlog total: {report.proposal_backlog_total}")
    click.echo(f"Proposal backlog accepted: {report.proposal_accepted}")
    click.echo(f"Proposal backlog deferred: {report.proposal_deferred}")
    click.echo(f"Proposal backlog rejected: {report.proposal_rejected}")
    click.echo(f"Proposal promoted goals: {report.proposal_promoted}")
    click.echo(f"Proposal accept ratio: {report.proposal_accept_ratio}")
    click.echo("")
    click.echo("Actions:")
    if report.action_counts:
        for key, value in sorted(report.action_counts.items()):
            click.echo(f"  {key}: {value}")
    else:
        click.echo("  (none)")
    click.echo("Failure classifications:")
    if report.failure_class_counts:
        for key, value in sorted(report.failure_class_counts.items()):
            click.echo(f"  {key}: {value}")
    else:
        click.echo("  (none)")


@main.group("immune")
def immune_group() -> None:
    """Immune guardrail commands."""


@immune_group.command("grant")
@click.option(
    "--allow",
    "allowed_changes",
    multiple=True,
    required=True,
    help="Allowed file glob pattern (repeatable).",
)
@click.option(
    "--approved-by",
    required=True,
    help="Approver identity (supervisor LLM or human).",
)
@click.option(
    "--issued-by",
    default="llm-supervisor",
    show_default=True,
    help="Grant issuer identity.",
)
@click.option(
    "--ttl-minutes",
    default=30,
    show_default=True,
    type=click.IntRange(min=1, max=1440),
    help="Grant lifetime in minutes.",
)
@click.option(
    "--reason",
    default="",
    help="Optional approval reason.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def immune_grant_command(
    allowed_changes: tuple[str, ...],
    approved_by: str,
    issued_by: str,
    ttl_minutes: int,
    reason: str,
    json_output: bool,
) -> None:
    """Issue a short-lived repair grant for autonomous edits."""
    from devf.core.immune_policy import write_repair_grant

    try:
        root = find_root(Path.cwd())
        grant_path = write_repair_grant(
            root,
            allowed_changes=list(allowed_changes),
            approved_by=approved_by,
            issued_by=issued_by,
            ttl_minutes=ttl_minutes,
            reason=reason,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "grant_path": grant_path.as_posix(),
                "approved_by": approved_by,
                "issued_by": issued_by,
                "ttl_minutes": ttl_minutes,
                "allowed_changes": list(allowed_changes),
                "reason": reason,
            }
        )
        return
    click.echo(f"Repair grant written: {grant_path.as_posix()}")


@main.group("docs")
def docs_group() -> None:
    """Documentation control plane commands."""


@docs_group.command("generate")
@click.option(
    "--window",
    "window_days",
    default=14,
    show_default=True,
    type=click.IntRange(min=1, max=365),
    help="Window for quality/security metrics report.",
)
@click.option(
    "--warn-stale/--no-warn-stale",
    default=True,
    show_default=True,
    help="Warn when generated docs are stale before refresh.",
)
@click.option(
    "--mermaid/--no-mermaid",
    "render_mermaid",
    default=True,
    show_default=True,
    help="Render mermaid diagrams found in markdown docs.",
)
@click.option(
    "--open-mermaid-index",
    is_flag=True,
    help="Open generated mermaid index after rendering.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def docs_generate_command(
    window_days: int,
    warn_stale: bool,
    render_mermaid: bool,
    open_mermaid_index: bool,
    json_output: bool,
) -> None:
    """Generate codemap/traceability/decision/quality docs."""
    from devf.core.docgen import generate_docs
    from devf.core.docs_policy import load_docs_policy, match_high_risk_paths

    try:
        root = find_root(Path.cwd())
        docs_policy = load_docs_policy(root)
        result = generate_docs(root, window_days=window_days, render_mermaid=render_mermaid)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    should_warn_stale = warn_stale and docs_policy.freshness.warn_stale
    high_risk_stale_sources: list[Path] = []
    if should_warn_stale and result.stale_paths:
        if not json_output:
            click.echo("Stale docs detected before refresh:")
            for path in result.stale_paths:
                click.echo(f"  - {path.as_posix()}")

    if docs_policy.freshness.block_on_high_risk and result.stale_paths:
        high_risk_stale_sources = match_high_risk_paths(
            result.stale_source_paths,
            docs_policy.freshness.high_risk_path_patterns,
        )
        if high_risk_stale_sources:
            if json_output:
                _emit_json(
                    {
                        "error": "freshness-policy-block",
                        "message": (
                            "generated docs were stale for high-risk paths; "
                            "commit refreshed docs before merge"
                        ),
                        "high_risk_stale_sources": [
                            path.as_posix() for path in high_risk_stale_sources
                        ],
                    }
                )
                raise SystemExit(1)
            else:
                click.echo("Freshness policy block (high-risk stale sources):")
                for path in high_risk_stale_sources:
                    click.echo(f"  - {path.as_posix()}")
            raise click.ClickException(
                "generated docs were stale for high-risk paths; commit refreshed docs before merge"
            )

    if json_output:
        _emit_json(
            {
                "window_days": window_days,
                "output_dir": result.output_dir.as_posix(),
                "generated_paths": [path.as_posix() for path in result.generated_paths],
                "stale_paths": [path.as_posix() for path in result.stale_paths],
                "stale_source_paths": [path.as_posix() for path in result.stale_source_paths],
                "high_risk_stale_sources": [path.as_posix() for path in high_risk_stale_sources],
                "mermaid": {
                    "enabled": render_mermaid,
                    "scanned_files": result.mermaid_scanned_files,
                    "diagrams_found": result.mermaid_diagrams_found,
                    "rendered": result.mermaid_rendered,
                    "failed": result.mermaid_failed,
                    "output_dir": (
                        result.mermaid_output_dir.as_posix()
                        if result.mermaid_output_dir
                        else None
                    ),
                    "index_path": (
                        result.mermaid_index_path.as_posix()
                        if result.mermaid_index_path
                        else None
                    ),
                },
                "warnings": list(result.warnings),
            }
        )
        return

    click.echo(f"Generated docs: {len(result.generated_paths)} file(s)")
    click.echo(f"Output directory: {result.output_dir.as_posix()}")
    for path in result.generated_paths:
        click.echo(f"  - {path.as_posix()}")
    if render_mermaid:
        click.echo(
            "Mermaid diagrams: "
            f"found={result.mermaid_diagrams_found} rendered={result.mermaid_rendered} "
            f"failed={result.mermaid_failed} scanned_files={result.mermaid_scanned_files}"
        )
        if result.mermaid_output_dir:
            click.echo(f"Mermaid output: {result.mermaid_output_dir.as_posix()}")
        if result.mermaid_index_path:
            click.echo(f"Mermaid index: {result.mermaid_index_path.as_posix()}")
            if open_mermaid_index:
                _open_path(root / result.mermaid_index_path)

    if result.warnings:
        click.echo("Warnings:")
        for warning in result.warnings:
            click.echo(f"  - {warning}")


@docs_group.command("mermaid")
@click.option(
    "--glob",
    "markdown_glob",
    default="docs/**/*.md",
    show_default=True,
    help="Markdown glob to scan for mermaid blocks.",
)
@click.option(
    "--mmdc",
    "mmdc_bin",
    default="mmdc",
    show_default=True,
    help="Mermaid CLI binary name/path.",
)
@click.option(
    "--open-index",
    is_flag=True,
    help="Open generated mermaid index in default browser/viewer.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def docs_mermaid_command(
    markdown_glob: str,
    mmdc_bin: str,
    open_index: bool,
    json_output: bool,
) -> None:
    """Render mermaid blocks from docs markdown to SVG assets."""
    from devf.core.mermaid import render_mermaid_docs

    try:
        root = find_root(Path.cwd())
        result = render_mermaid_docs(
            root,
            markdown_glob=markdown_glob,
            mmdc_bin=mmdc_bin,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "markdown_glob": markdown_glob,
                "mmdc_bin": mmdc_bin,
                "scanned_files": result.scanned_files,
                "diagrams_found": result.diagrams_found,
                "rendered": result.rendered,
                "failed": result.failed,
                "output_dir": result.output_dir.as_posix(),
                "index_path": result.index_path.as_posix() if result.index_path else None,
                "warnings": list(result.warnings),
            }
        )
        return

    click.echo(f"Markdown scanned: {result.scanned_files}")
    click.echo(f"Diagrams found: {result.diagrams_found}")
    click.echo(f"Rendered: {result.rendered}")
    click.echo(f"Failed: {result.failed}")
    click.echo(f"Output directory: {result.output_dir.as_posix()}")
    if result.index_path:
        click.echo(f"Index: {result.index_path.as_posix()}")
        if open_index:
            _open_path(root / result.index_path)
    if result.warnings:
        click.echo("Warnings:")
        for warning in result.warnings:
            click.echo(f"  - {warning}")


@docs_group.command("sync-vault")
@click.option(
    "--check-links/--no-check-links",
    default=True,
    show_default=True,
    help="Inspect wikilinks and orphan notes after sync.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Exit with error when broken links or orphan notes are found.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def docs_sync_vault_command(check_links: bool, strict: bool, json_output: bool) -> None:
    """Generate `.knowledge/` wikilink pages from devf source artifacts."""
    from devf.core.vault import sync_vault

    try:
        root = find_root(Path.cwd())
        result = sync_vault(root, check_links=check_links)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        payload = {
            "output_dir": result.output_dir.as_posix(),
            "generated_paths": [path.as_posix() for path in result.generated_paths],
            "check_links": check_links,
            "broken_links": list(result.broken_links),
            "orphan_notes": [path.as_posix() for path in result.orphan_notes],
        }
        if strict and (result.broken_links or result.orphan_notes):
            payload["strict_failed"] = True
            _emit_json(payload)
            raise SystemExit(1)
        _emit_json(payload)
        return

    click.echo(f"Vault synced: {len(result.generated_paths)} file(s)")
    click.echo(f"Output directory: {result.output_dir.as_posix()}")
    for path in result.generated_paths:
        click.echo(f"  - {path.as_posix()}")

    if check_links:
        click.echo(f"Broken wikilinks: {len(result.broken_links)}")
        click.echo(f"Orphan notes: {len(result.orphan_notes)}")
        if result.broken_links:
            click.echo("Broken link details:")
            for item in result.broken_links:
                click.echo(f"  - {item}")
        if result.orphan_notes:
            click.echo("Orphan note details:")
            for path in result.orphan_notes:
                click.echo(f"  - {path.as_posix()}")

    if strict and (result.broken_links or result.orphan_notes):
        raise click.ClickException("vault link checks failed (broken links or orphan notes found)")


def _open_path(path: Path) -> None:
    import subprocess
    import sys

    if sys.platform == "darwin":
        cmd = ["open", str(path)]
    elif sys.platform.startswith("win"):
        cmd = ["cmd", "/c", "start", "", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.run(cmd, check=False)


@main.command("triage")
@click.option("--run-id", "run_id", required=True, help="Run id under .ai/runs/<run_id>.")
@click.option("--goal", "goal_id", default=None, help="Optional goal id filter.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def triage_command(run_id: str, goal_id: str | None, json_output: bool) -> None:
    """Show failure triage rows for a run."""
    from devf.core.metrics import build_triage_report

    try:
        root = find_root(Path.cwd())
        rows = build_triage_report(root, run_id)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if goal_id:
        rows = [row for row in rows if row.goal_id == goal_id]

    if not rows:
        if json_output:
            _emit_json({"run_id": run_id, "goal_id": goal_id, "rows": []})
            return
        click.echo("No triage rows found.")
        return

    if json_output:
        _emit_json(
            {
                "run_id": run_id,
                "goal_id": goal_id,
                "rows": [row.__dict__ for row in rows],
            }
        )
        return

    for row in rows:
        click.echo(
            f"{row.goal_id} phase={row.phase} attempt={row.attempt} "
            f"class={row.classification} failure={row.failure_classification} action={row.action_taken}"
        )
        if row.reason:
            click.echo(f"  reason: {row.reason}")


@main.group("feedback")
def feedback_group() -> None:
    """Feedback capture and manager triage."""


@feedback_group.command("note")
@click.option("--run-id", "run_id", default=None, help="Optional run id context.")
@click.option("--goal", "goal_id", default=None, help="Optional goal id context.")
@click.option("--phase", "phase", default=None, help="Optional phase context.")
@click.option(
    "--category",
    type=click.Choice(
        ["ux_gap", "missing_feature", "waste", "error_clarity", "workflow_friction"],
        case_sensitive=False,
    ),
    required=True,
)
@click.option(
    "--impact",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    required=True,
)
@click.option("--expected", required=True, help="Expected behavior.")
@click.option("--actual", required=True, help="Observed behavior.")
@click.option("--workaround", default="", help="Current workaround if any.")
@click.option(
    "--confidence",
    default=0.7,
    type=click.FloatRange(min=0.0, max=1.0),
    show_default=True,
    help="Confidence score for this note.",
)
@click.option("--tool", "tool_name", default=None, help="Tool/model identifier.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_note_command(
    run_id: str | None,
    goal_id: str | None,
    phase: str | None,
    category: str,
    impact: str,
    expected: str,
    actual: str,
    workaround: str,
    confidence: float,
    tool_name: str | None,
    json_output: bool,
) -> None:
    """Record one explicit worker feedback note."""
    from devf.core.feedback import create_feedback_note, write_feedback_note

    try:
        root = find_root(Path.cwd())
        note = create_feedback_note(
            run_id=run_id,
            goal_id=goal_id,
            phase=phase,
            source="worker_explicit",
            category=category,
            impact=impact,
            expected=expected,
            actual=actual,
            workaround=workaround,
            confidence=confidence,
            tool_name=tool_name,
        )
        write_feedback_note(root, note)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "note_id": note["note_id"],
                "fingerprint": note["fingerprint"],
                "note": note,
            }
        )
        return
    click.echo(f"Feedback note recorded: {note['note_id']}")
    click.echo(f"  fingerprint: {note['fingerprint']}")


@feedback_group.command("analyze")
@click.option("--run-id", "run_id", required=True, help="Run id under .ai/runs/<run_id>.")
@click.option("--goal", "goal_id", default=None, help="Optional goal id filter.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_analyze_command(run_id: str, goal_id: str | None, json_output: bool) -> None:
    """Infer friction notes from evidence rows."""
    from devf.core.feedback_infer import infer_and_store_feedback_notes
    from devf.core.feedback_policy import load_feedback_policy

    try:
        root = find_root(Path.cwd())
        policy = load_feedback_policy(root)
        created = infer_and_store_feedback_notes(root, run_id, policy, goal_id=goal_id)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "run_id": run_id,
                "goal_id": goal_id,
                "created_count": len(created),
                "created": created,
            }
        )
        return
    click.echo(f"Inferred notes created: {len(created)}")
    for note in created[:20]:
        click.echo(
            f"- {note.get('category')} impact={note.get('impact')} goal={note.get('goal_id')} "
            f"fingerprint={note.get('fingerprint')}"
        )


@feedback_group.command("backlog")
@click.option(
    "--window",
    "window_days",
    default=7,
    show_default=True,
    type=click.IntRange(min=1, max=365),
    help="Aggregate notes from the last N days.",
)
@click.option("--promote", is_flag=True, help="Apply manager promotion policy and write backlog.yaml.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_backlog_command(window_days: int, promote: bool, json_output: bool) -> None:
    """Build manager backlog candidates from notes."""
    from devf.core.feedback import (
        build_feedback_backlog,
        load_feedback_notes,
        save_feedback_backlog,
    )
    from devf.core.feedback_policy import load_feedback_policy

    try:
        root = find_root(Path.cwd())
        policy = load_feedback_policy(root)
        notes = load_feedback_notes(root, window_days=window_days)
        items = build_feedback_backlog(notes, policy=policy, promote=promote)
        backlog_path: str | None = None
        if promote:
            path = save_feedback_backlog(root, items)
            backlog_path = path.relative_to(root).as_posix()
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    accepted = sum(1 for item in items if item.get("status") == "accepted")
    deferred = sum(1 for item in items if item.get("status") == "deferred")
    candidates = sum(1 for item in items if item.get("status") == "candidate")
    if json_output:
        _emit_json(
            {
                "window_days": window_days,
                "promote": promote,
                "notes_loaded": len(notes),
                "backlog_items": len(items),
                "accepted": accepted,
                "deferred": deferred,
                "candidate": candidates,
                "backlog_path": backlog_path,
                "items": items,
            }
        )
        return

    click.echo(f"Window: last {window_days} day(s)")
    if promote and backlog_path:
        click.echo(f"Backlog updated: {backlog_path}")
    click.echo(f"Notes loaded: {len(notes)}")
    click.echo(f"Backlog items: {len(items)}")
    click.echo(f"Accepted: {accepted}, Deferred: {deferred}, Candidate: {candidates}")
    for item in items[:20]:
        click.echo(
            f"- [{item.get('status')}] count={item.get('count')} impact={item.get('max_impact')} "
            f"{item.get('title')}"
        )


@feedback_group.command("publish")
@click.option(
    "--limit",
    default=20,
    show_default=True,
    type=click.IntRange(min=1, max=200),
    help="Maximum number of backlog items to publish.",
)
@click.option("--dry-run", is_flag=True, help="Render publish plan without external API calls.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_publish_command(limit: int, dry_run: bool, json_output: bool) -> None:
    """Publish manager-accepted backlog items to Codeberg issues."""
    from devf.core.feedback_policy import load_feedback_policy
    from devf.core.feedback_publish import publish_feedback_backlog

    try:
        root = find_root(Path.cwd())
        policy = load_feedback_policy(root)
        if not policy.publish.enabled and not dry_run:
            raise DevfError(
                "feedback publish is disabled in feedback_policy.yaml "
                "(set publish.enabled: true, or use --dry-run)"
            )
        result = publish_feedback_backlog(root, policy, limit=limit, dry_run=dry_run)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "limit": limit,
                "dry_run": dry_run,
                "attempted": result.attempted,
                "published": result.published,
                "failed": result.failed,
                "skipped": result.skipped,
                "urls": list(result.urls),
            }
        )
        return
    click.echo(f"Attempted: {result.attempted}")
    click.echo(f"Published: {result.published}")
    click.echo(f"Failed: {result.failed}")
    click.echo(f"Skipped: {result.skipped}")
    for url in result.urls:
        click.echo(f"- {url}")


@main.group("propose")
def propose_group() -> None:
    """Emergent goal proposal inbox (capture only)."""


@propose_group.command("note")
@click.option("--run-id", default=None, help="Optional run id.")
@click.option("--goal", "goal_id", default=None, help="Optional related goal id.")
@click.option("--source", default="worker", show_default=True, help="Proposal source actor.")
@click.option(
    "--category",
    type=click.Choice(["risk", "opportunity", "tech_debt", "workflow_friction"], case_sensitive=False),
    required=True,
)
@click.option(
    "--impact",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    required=True,
)
@click.option(
    "--risk",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    required=True,
)
@click.option(
    "--confidence",
    default=0.7,
    type=click.FloatRange(min=0.0, max=1.0),
    show_default=True,
    help="Confidence score for this proposal.",
)
@click.option(
    "--effort-hint",
    default="m",
    type=click.Choice(["xs", "s", "m", "l", "xl"], case_sensitive=False),
    show_default=True,
)
@click.option("--title", required=True, help="Short proposal title.")
@click.option("--why-now", required=True, help="Why this should be addressed now.")
@click.option(
    "--evidence-ref",
    "evidence_refs",
    multiple=True,
    help="Evidence reference path/id. Can be repeated.",
)
@click.option(
    "--affects-goal",
    "affected_goals",
    multiple=True,
    help="Related goal id. Can be repeated.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def propose_note_command(
    run_id: str | None,
    goal_id: str | None,
    source: str,
    category: str,
    impact: str,
    risk: str,
    confidence: float,
    effort_hint: str,
    title: str,
    why_now: str,
    evidence_refs: tuple[str, ...],
    affected_goals: tuple[str, ...],
    json_output: bool,
) -> None:
    """Record one proposal note in `.ai/proposals/notes.jsonl`."""
    from devf.core.proposals import create_proposal_note, write_proposal_note

    try:
        root = find_root(Path.cwd())
        note = create_proposal_note(
            source=source,
            category=category.lower(),
            impact=impact.lower(),
            risk=risk.lower(),
            confidence=confidence,
            effort_hint=effort_hint.lower(),
            title=title,
            why_now=why_now,
            run_id=run_id,
            goal_id=goal_id,
            evidence_refs=list(evidence_refs),
            affected_goals=list(affected_goals),
        )
        path = write_proposal_note(root, note)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "proposal_id": note["proposal_id"],
                "file": path.relative_to(root).as_posix(),
                "fingerprint": note["fingerprint"],
                "note": note,
            }
        )
        return
    click.echo(f"Proposal recorded: {note['proposal_id']}")
    click.echo(f"  file: {path.relative_to(root).as_posix()}")
    click.echo(f"  fingerprint: {note['fingerprint']}")


@propose_group.command("list")
@click.option(
    "--window",
    "window_days",
    default=30,
    show_default=True,
    type=click.IntRange(min=1, max=3650),
    help="Load proposals from the last N days.",
)
@click.option(
    "--category",
    default=None,
    type=click.Choice(["risk", "opportunity", "tech_debt", "workflow_friction"], case_sensitive=False),
    help="Filter by category.",
)
@click.option(
    "--status",
    default=None,
    help="Filter by status (default: all statuses).",
)
@click.option(
    "--limit",
    default=20,
    show_default=True,
    type=click.IntRange(min=1, max=200),
    help="Max rows to print.",
)
@click.option("--json", "json_output", is_flag=True, help="Print rows as JSON array.")
@click.option("--json-output", "json_output", is_flag=True, hidden=True)
def propose_list_command(
    window_days: int,
    category: str | None,
    status: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """List recorded proposal notes."""
    from devf.core.proposals import load_proposal_notes

    try:
        root = find_root(Path.cwd())
        rows = load_proposal_notes(
            root,
            window_days=window_days,
            category=category.lower() if category else None,
            status=status.strip() if status else None,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    shown = rows[:limit]
    if json_output:
        _emit_json(
            {
                "window_days": window_days,
                "category": category.lower() if category else None,
                "status": status.strip() if status else None,
                "total": len(rows),
                "shown": len(shown),
                "rows": shown,
            }
        )
        return

    click.echo(f"Window: last {window_days} day(s)")
    click.echo(f"Proposals loaded: {len(rows)}")
    click.echo(f"Showing: {len(shown)}")
    for row in shown:
        click.echo(
            f"- [{row.get('status')}] {row.get('proposal_id')} "
            f"cat={row.get('category')} impact={row.get('impact')} risk={row.get('risk')} "
            f"title={row.get('title')}"
        )


@propose_group.command("promote")
@click.option(
    "--window",
    "window_days",
    default=14,
    show_default=True,
    type=click.IntRange(min=1, max=3650),
    help="Evaluate proposals from the last N days.",
)
@click.option(
    "--max-active",
    default=5,
    show_default=True,
    type=click.IntRange(min=1, max=200),
    help="Max number of active proposal-derived goals under the program root.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def propose_promote_command(window_days: int, max_active: int, json_output: bool) -> None:
    """Promote proposal inbox items into managed goals by admission policy."""
    from devf.core.admission import promote_proposals

    try:
        root = find_root(Path.cwd())
        result = promote_proposals(
            root,
            window_days=window_days,
            max_active=max_active,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "window_days": window_days,
                "max_active": max_active,
                "total": result.total,
                "accepted": result.accepted,
                "deferred": result.deferred,
                "rejected": result.rejected,
                "goals_added": result.goals_added,
                "backlog_path": result.backlog_path.relative_to(root).as_posix(),
            }
        )
        return
    click.echo(f"Window: last {window_days} day(s)")
    click.echo(f"Total evaluated: {result.total}")
    click.echo(f"Accepted: {result.accepted}")
    click.echo(f"Deferred: {result.deferred}")
    click.echo(f"Rejected: {result.rejected}")
    click.echo(f"Goals added: {result.goals_added}")
    click.echo(f"Backlog updated: {result.backlog_path.relative_to(root).as_posix()}")


@main.group("decision")
def decision_group() -> None:
    """Decision ticket + validation matrix workflow."""


@decision_group.command("new")
@click.argument("goal_id")
@click.option("--question", required=True, help="Decision question to resolve.")
@click.option(
    "--alternatives",
    default="A,B",
    show_default=True,
    help="Comma-separated alternative ids.",
)
@click.option("--decision-id", default=None, help="Optional decision id override.")
@click.option("--owner", default="architect", show_default=True, help="Decision owner.")
@click.option(
    "--file",
    "file_path",
    default=None,
    help="Optional output path (default: .ai/decisions/<decision_id>.yaml).",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def decision_new_command(
    goal_id: str,
    question: str,
    alternatives: str,
    decision_id: str | None,
    owner: str,
    file_path: str | None,
    json_output: bool,
) -> None:
    """Create a decision ticket template."""
    from devf.core.decision import (
        create_decision_ticket,
        default_decision_id,
        normalize_decision_id,
        save_decision_ticket,
    )

    try:
        root = find_root(Path.cwd())
        alt_ids = [item.strip() for item in alternatives.split(",") if item.strip()]
        if len(alt_ids) < 2:
            raise DevfError("at least 2 alternatives are required")

        resolved_id = decision_id.strip() if decision_id else default_decision_id(goal_id)
        ticket = create_decision_ticket(
            goal_id=goal_id,
            question=question,
            alternatives=alt_ids,
            decision_id=resolved_id,
            owner=owner,
        )

        if file_path:
            out_path = Path(file_path)
            if not out_path.is_absolute():
                out_path = root / out_path
        else:
            out_path = root / ".ai" / "decisions" / f"{normalize_decision_id(resolved_id)}.yaml"
        if out_path.exists():
            raise DevfError(f"decision file already exists: {out_path.as_posix()}")
        save_decision_ticket(out_path, ticket)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "decision_file": out_path.relative_to(root).as_posix(),
                "decision_id": ticket["decision_id"],
                "goal_id": goal_id,
                "alternatives": alt_ids,
            }
        )
        return
    click.echo(f"Decision ticket created: {out_path.relative_to(root).as_posix()}")
    click.echo(f"Decision id: {ticket['decision_id']}")
    click.echo(f"Alternatives: {', '.join(alt_ids)}")
    click.echo("Next: fill `scores`, then run `devf decision evaluate <file> --accept`.")


@decision_group.command("evaluate")
@click.argument("decision_file")
@click.option("--accept", is_flag=True, help="Apply winner and update decision status.")
@click.option("--run-id", default=None, help="Optional run id for evidence linkage.")
@click.option("--actor", default="orchestrator", show_default=True, help="Actor name.")
@click.option(
    "--log-evidence/--no-log-evidence",
    default=True,
    show_default=True,
    help="Append decision evaluation row to .ai/decisions/evidence.jsonl.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def decision_evaluate_command(
    decision_file: str,
    accept: bool,
    run_id: str | None,
    actor: str,
    log_evidence: bool,
    json_output: bool,
) -> None:
    """Evaluate a decision ticket against its validation matrix."""
    from devf.core.decision import (
        append_decision_evidence,
        apply_decision_result,
        evaluate_decision_ticket,
        load_decision_ticket,
        save_decision_ticket,
    )

    try:
        root = find_root(Path.cwd())
        path = Path(decision_file)
        if not path.is_absolute():
            path = root / path

        ticket = load_decision_ticket(path)
        evaluation = evaluate_decision_ticket(ticket)
        evidence_path = None

        if accept:
            ticket = apply_decision_result(ticket, evaluation, actor=actor)
            save_decision_ticket(path, ticket)

        if log_evidence:
            evidence_path = append_decision_evidence(
                root=root,
                decision_file=path,
                ticket=ticket,
                evaluation=evaluation,
                run_id=run_id,
                actor=actor,
            )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    ranking = [
        {
            "alternative_id": row.alternative_id,
            "total_score": row.total_score,
            "eligible": row.eligible,
            "failed_criteria": list(row.failed_criteria),
        }
        for row in evaluation.ranking
    ]

    if json_output:
        _emit_json(
            {
                "decision_id": evaluation.decision_id,
                "goal_id": evaluation.goal_id,
                "winner_id": evaluation.winner_id,
                "winner_eligible": evaluation.winner_eligible,
                "accept": accept,
                "status": ticket.get("status"),
                "selected_alternative": ticket.get("selected_alternative"),
                "ranking": ranking,
                "evidence_path": (
                    evidence_path.relative_to(root).as_posix() if evidence_path else None
                ),
            }
        )
        return

    click.echo(f"Decision: {evaluation.decision_id} (goal={evaluation.goal_id})")
    for row in evaluation.ranking:
        if row.eligible:
            tag = "eligible"
        else:
            tag = "blocked:" + ",".join(row.failed_criteria)
        click.echo(f"  {row.alternative_id}: score={row.total_score} {tag}")
    click.echo(
        f"Winner: {evaluation.winner_id} "
        f"(eligible={evaluation.winner_eligible})"
    )
    if accept:
        click.echo(
            f"Decision updated: status={ticket.get('status')} "
            f"selected={ticket.get('selected_alternative')}"
        )
    if log_evidence and evidence_path is not None:
        click.echo(f"Decision evidence appended: {evidence_path.relative_to(root).as_posix()}")


@decision_group.command("spike")
@click.argument("decision_file")
@click.option(
    "--parallel",
    default=2,
    show_default=True,
    type=click.IntRange(min=1, max=32),
    help="Max number of alternatives to execute concurrently.",
)
@click.option(
    "--command",
    "command_template",
    default="true",
    show_default=True,
    help=(
        "Shell template executed per alternative. "
        "Supports {alternative_id}, {decision_id}, {goal_id} placeholders."
    ),
)
@click.option(
    "--backend",
    type=click.Choice(["auto", "thread", "ray"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Execution backend for spike tasks.",
)
@click.option("--actor", default="orchestrator", show_default=True, help="Actor name.")
@click.option(
    "--log-evidence/--no-log-evidence",
    default=True,
    show_default=True,
    help="Append spike summary row to .ai/decisions/evidence.jsonl.",
)
@click.option(
    "--accept",
    is_flag=True,
    help="Run decision evaluate + apply after spikes complete.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def decision_spike_command(
    decision_file: str,
    parallel: int,
    command_template: str,
    backend: str,
    actor: str,
    log_evidence: bool,
    accept: bool,
    json_output: bool,
) -> None:
    """Run parallel spikes for all alternatives in a decision ticket."""
    from devf.core.decision import (
        append_decision_evidence,
        apply_decision_result,
        evaluate_decision_ticket,
        load_decision_ticket,
        save_decision_ticket,
    )
    from devf.core.spike import run_decision_spikes

    try:
        root = find_root(Path.cwd())
        path = Path(decision_file)
        if not path.is_absolute():
            path = root / path

        result = run_decision_spikes(
            root=root,
            decision_file=path,
            parallel=parallel,
            command_template=command_template,
            backend=backend,
            actor=actor,
            log_evidence=log_evidence,
        )
        evidence_path = None

        if accept:
            ticket = load_decision_ticket(path)
            evaluation = evaluate_decision_ticket(ticket)
            ticket = apply_decision_result(ticket, evaluation, actor=actor)
            save_decision_ticket(path, ticket)
            if log_evidence:
                evidence_path = append_decision_evidence(
                    root=root,
                    decision_file=path,
                    ticket=ticket,
                    evaluation=evaluation,
                    run_id=None,
                    actor=actor,
                )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    alternatives = [
        {
            "alternative_id": row.alternative_id,
            "passed": row.passed,
            "exit_code": row.exit_code,
            "duration_ms": row.duration_ms,
            "command": row.command,
            "output_file": row.output_file,
            "metadata_file": row.metadata_file,
        }
        for row in sorted(result.alternatives, key=lambda item: item.alternative_id)
    ]

    if json_output:
        _emit_json(
            {
                "summary_path": result.summary_path.relative_to(root).as_posix(),
                "winner_id": result.winner_id,
                "escalated": result.escalated,
                "alternatives": alternatives,
                "accept": accept,
                "evidence_path": (
                    evidence_path.relative_to(root).as_posix() if evidence_path else None
                ),
            }
        )
        return

    click.echo(
        f"Spike summary: {result.summary_path.relative_to(root).as_posix()} "
        f"(winner={result.winner_id or 'none'}, escalated={result.escalated})"
    )
    for row in sorted(result.alternatives, key=lambda item: item.alternative_id):
        status = "PASS" if row.passed else "FAIL"
        click.echo(
            f"  {row.alternative_id}: {status} "
            f"exit={row.exit_code} duration_ms={row.duration_ms}"
        )
    if accept:
        click.echo(
            f"Decision updated: status={ticket.get('status')} "
            f"selected={ticket.get('selected_alternative')}"
        )
        if log_evidence and evidence_path is not None:
            click.echo(
                f"Decision evidence appended: {evidence_path.relative_to(root).as_posix()}"
            )


@main.command("auto")
@click.argument("goal_id", required=False)
@click.option("--recursive", is_flag=True, help="Run active goals under the goal.")
@click.option("--dry-run", is_flag=True, help="Print prompt and exit.")
@click.option("--explain", is_flag=True, help="Explain outcome decisions.")
@click.option("--tool", "tool_name", help="Override AI tool name.")
@click.option(
    "--parallel",
    "parallelism",
    default=1,
    show_default=True,
    type=click.IntRange(min=1, max=32),
    help="Max number of goals to execute concurrently within dependency-safe batches.",
)
def auto_command(
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    explain: bool,
    tool_name: str | None,
    parallelism: int,
) -> None:
    """Run automated loop."""
    try:
        root = find_root(Path.cwd())
        exit_code = run_auto(
            root=root,
            goal_id=goal_id,
            recursive=recursive,
            dry_run=dry_run,
            explain=explain,
            tool_name=tool_name,
            parallelism=parallelism,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    raise SystemExit(exit_code)


@main.command("plan")
@click.argument("instruction", required=False)
@click.option("--autonomous", is_flag=True, help="Run in continuous autonomous loop.")
@click.option("--tool", "tool_name", help="Override AI tool name.")
def plan_command(instruction: str | None, autonomous: bool, tool_name: str | None) -> None:
    """Architect mode: Plan goals from instructions."""
    from devf.core.architect import plan_goals
    from devf.core.auto import run_auto

    try:
        root = find_root(Path.cwd())
        
        if autonomous:
            if not instruction:
                instruction = "Review documentation and current code, then implement missing features."
            
            click.echo("🚀 Starting Autonomous Architect Loop...")
            
            # Safety Limits
            MAX_LOOPS = 10
            MAX_CONSECUTIVE_FAILURES = 3
            
            loop_count = 0
            fail_count = 0
            
            while True:
                if loop_count >= MAX_LOOPS:
                    click.echo(f"\n🛑 Safety Stop: Max loops ({MAX_LOOPS}) reached.")
                    break
                    
                loop_count += 1
                click.echo(f"\n[Architect] Loop {loop_count}/{MAX_LOOPS}. Planning next move...")
                
                goal_id = plan_goals(root, instruction, tool_name=tool_name)
                
                if not goal_id:
                    click.echo("[Architect] No more goals generated. Stopping.")
                    break
                
                click.echo(f"[Architect] Executing Goal: {goal_id}")
                # Execute the generated goal immediately
                exit_code = run_auto(
                    root=root,
                    goal_id=goal_id,
                    recursive=False,
                    dry_run=False,
                    explain=True,
                    tool_name=tool_name,
                )
                
                if exit_code != 0:
                     fail_count += 1
                     click.echo(f"[Architect] Goal {goal_id} failed. (Failures: {fail_count}/{MAX_CONSECUTIVE_FAILURES})")
                     if fail_count >= MAX_CONSECUTIVE_FAILURES:
                         click.echo("🛑 Safety Stop: Too many consecutive failures.")
                         break
                else:
                     fail_count = 0 # Reset on success
                     click.echo(f"[Architect] Goal {goal_id} complete. Iterating...")
                
                # Update instruction to "Continue" or refresh context?
                # The Architect will see the updated goals.yaml next time.
        else:
            if not instruction:
                raise click.UsageError("Instruction is required for single-run plan.")
            
            goal_id = plan_goals(root, instruction, tool_name=tool_name)
            if goal_id:
                click.echo(f"Goal {goal_id} created. Run 'devf auto {goal_id}' to execute.")

    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("orchestrate")
@click.option("--run-id", default=None, help="Optional run id to analyze; defaults to latest run.")
@click.option(
    "--window",
    "window_days",
    default=14,
    show_default=True,
    type=click.IntRange(min=1, max=365),
    help="Feedback aggregation window in days.",
)
@click.option(
    "--max-goals",
    default=5,
    show_default=True,
    type=click.IntRange(min=1, max=50),
    help="Maximum accepted backlog items to sync into goals.",
)
@click.option("--publish", is_flag=True, help="Publish accepted backlog items after sync.")
@click.option(
    "--publish-dry-run",
    is_flag=True,
    help="When used with --publish, skip external API and simulate publishing.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def orchestrate_command(
    run_id: str | None,
    window_days: int,
    max_goals: int,
    publish: bool,
    publish_dry_run: bool,
    json_output: bool,
) -> None:
    """Run productivity cycle: analyze -> backlog -> goals -> optional publish."""
    from devf.core.orchestrator import orchestrate_productivity_cycle

    try:
        root = find_root(Path.cwd())
        result = orchestrate_productivity_cycle(
            root,
            run_id=run_id,
            window_days=window_days,
            max_goals=max_goals,
            publish=publish,
            publish_dry_run=publish_dry_run,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "run_id": result.run_id,
                "inferred_notes": result.inferred_notes,
                "total_notes": result.total_notes,
                "backlog_items": result.backlog_items,
                "accepted_items": result.accepted_items,
                "goals_added": result.goals_added,
                "publish_result": (
                    {
                        "attempted": result.publish_result.attempted,
                        "published": result.publish_result.published,
                        "failed": result.publish_result.failed,
                        "skipped": result.publish_result.skipped,
                        "urls": list(result.publish_result.urls),
                    }
                    if result.publish_result
                    else None
                ),
            }
        )
        return

    click.echo("Orchestration complete")
    click.echo(f"Run id: {result.run_id or '(none)'}")
    click.echo(f"Inferred notes: {result.inferred_notes}")
    click.echo(f"Total notes (window): {result.total_notes}")
    click.echo(f"Backlog items: {result.backlog_items}")
    click.echo(f"Accepted items: {result.accepted_items}")
    click.echo(f"Goals added: {result.goals_added}")
    if result.publish_result is not None:
        click.echo(
            f"Publish attempted={result.publish_result.attempted} "
            f"published={result.publish_result.published} "
            f"failed={result.publish_result.failed}"
        )
