"""hast CLI entry point."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import shlex

import click

from hast.core.auto import run_auto
from hast.core.context import build_context, find_root
from hast.core.errors import DevfError
from hast.core.init_project import init_project


@click.group()
def main() -> None:
    """hast CLI."""


def _emit_json(payload: object) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _normalize_reason_code(value: str) -> str:
    token = value.strip().lower()
    if token.startswith("why:"):
        return token[4:]
    return token


def _resolve_goal_for_focus(root: Path, preferred_goal_id: str | None):
    from hast.core.goals import find_goal, load_goals, select_active_goal

    goals = load_goals(root / ".ai" / "goals.yaml")
    if preferred_goal_id:
        goal = find_goal(goals, preferred_goal_id)
        if goal is None:
            raise DevfError(f"goal not found: {preferred_goal_id}")
        return goal
    return select_active_goal(goals, None)


def _render_tool_launch_command(root: Path, tool_name: str, prompt_rel_path: Path) -> str:
    from hast.core.config import load_config

    default_by_tool = {
        "codex": "codex exec {prompt_file}",
        "claude": "claude -p {prompt_file}",
    }
    template = default_by_tool[tool_name]

    config_path = root / ".ai" / "config.yaml"
    if config_path.exists():
        try:
            config, _ = load_config(config_path)
            if tool_name in config.ai_tools:
                template = config.ai_tools[tool_name]
            elif tool_name in config.ai_tool.lower():
                template = config.ai_tool
        except DevfError:
            pass

    prompt_ref = shlex.quote(prompt_rel_path.as_posix())
    if "{prompt_file}" in template:
        return template.replace("{prompt_file}", prompt_ref)
    if "{prompt}" in template:
        return template.replace("{prompt}", f"$(cat {prompt_ref})")
    return f"{template} {prompt_ref}"


def _render_focus_prompt(root: Path, goal, tool_name: str, context_text: str) -> str:
    from hast.core.config import load_config

    test_command = "pytest -q"
    config_path = root / ".ai" / "config.yaml"
    if config_path.exists():
        try:
            config, _ = load_config(config_path)
            test_command = config.test_command
        except DevfError:
            pass

    goal_lines: list[str] = []
    if goal is None:
        goal_lines.append("- active goal: none (operator must choose)")
    else:
        goal_lines.append(f"- goal_id: {goal.id}")
        goal_lines.append(f"- title: {goal.title}")
        goal_lines.append(f"- phase: {goal.phase or 'legacy'}")
        goal_lines.append(f"- uncertainty: {goal.uncertainty or 'unknown'}")
        if goal.allowed_changes:
            goal_lines.append("- allowed_changes:")
            for item in goal.allowed_changes:
                goal_lines.append(f"  - {item}")
        if goal.test_files:
            goal_lines.append("- must_pass_tests:")
            for item in goal.test_files:
                goal_lines.append(f"  - {item}")

    checklist = [
        "Execution checklist:",
        "1. Implement minimal diff for the current goal.",
        "2. Keep edits within allowed_changes (if configured).",
        f"3. Verify with: {test_command}",
        "4. Non-interactive contract: do not ask clarifying questions; proceed with safest assumption.",
        "5. Summarize changed files + risk notes + next action.",
    ]

    header = [
        f"# hast focus pack ({tool_name})",
        "",
        "You are operating in a low-cognitive-load mode.",
        "Prioritize small, verifiable steps and explicit outputs.",
        "",
        "Goal snapshot:",
        *goal_lines,
        "",
        *checklist,
        "",
        "---",
        "",
        "Context:",
        context_text,
    ]
    return "\n".join(header)


def _render_focus_brief(goal, tool_name: str, prompt_rel: Path, launch_command: str) -> str:
    lines = [
        f"# Focus Brief ({tool_name})",
        "",
        "## Launch",
        f"`{launch_command}`",
        "",
        "## Prompt File",
        f"`{prompt_rel.as_posix()}`",
        "",
        "## Goal",
    ]
    if goal is None:
        lines.append("- none selected (choose a goal before execution)")
    else:
        lines.append(f"- id: `{goal.id}`")
        lines.append(f"- title: {goal.title}")
        lines.append(f"- phase: `{goal.phase or 'legacy'}`")
        lines.append(f"- uncertainty: `{goal.uncertainty or 'unknown'}`")
        if goal.allowed_changes:
            lines.append("- allowed changes:")
            for path in goal.allowed_changes:
                lines.append(f"  - `{path}`")
        if goal.test_files:
            lines.append("- test files:")
            for path in goal.test_files:
                lines.append(f"  - `{path}`")
    return "\n".join(lines) + "\n"


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
    click.echo("  ├── .hast-metadata")
    click.echo("  ├── config.yaml")
    click.echo("  ├── goals.yaml")
    click.echo("  ├── decisions/")
    click.echo("  ├── proposals/")
    click.echo("  ├── protocols/")
    click.echo("  ├── templates/")
    click.echo("  ├── schemas/")
    click.echo("  ├── policies/")
    click.echo("  ├── rules.md")
    click.echo("  ├── sessions/")
    click.echo("  └── handoffs/")
    click.echo("Updated .gitignore")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  1. Edit .ai/config.yaml — set test_command and ai_tool.")
    click.echo("  2. Edit .ai/goals.yaml — add your goals.")
    click.echo("  3. Run: hast auto [goal_id]")


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


@main.command("focus")
@click.option(
    "--tool",
    "tool_name",
    type=click.Choice(["codex", "claude"], case_sensitive=False),
    default="codex",
    show_default=True,
    help="Target operator session profile.",
)
@click.option("--goal", "goal_id", default=None, help="Preferred goal id (defaults to active goal).")
@click.option(
    "--context-format",
    type=click.Choice(["markdown", "plain", "json", "pack"], case_sensitive=False),
    default="pack",
    show_default=True,
    help="Context rendering format used inside prompt file.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def focus_command(
    tool_name: str,
    goal_id: str | None,
    context_format: str,
    json_output: bool,
) -> None:
    """Create a low-cognitive-load session pack for Codex/Claude operators."""
    try:
        root = find_root(Path.cwd())
        goal = _resolve_goal_for_focus(root, goal_id)
        context_text = build_context(root, context_format.lower())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    sessions_dir = root / ".ai" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    goal_token = goal.id if goal is not None else "NO_GOAL"
    prompt_rel = Path(".ai") / "sessions" / f"{ts}_{tool_name}_{goal_token}.prompt.txt"
    brief_rel = Path(".ai") / "sessions" / f"{ts}_{tool_name}_{goal_token}.brief.md"

    launch_command = _render_tool_launch_command(root, tool_name, prompt_rel)
    prompt_text = _render_focus_prompt(root, goal, tool_name, context_text)
    brief_text = _render_focus_brief(goal, tool_name, prompt_rel, launch_command)

    (root / prompt_rel).write_text(prompt_text, encoding="utf-8")
    (root / brief_rel).write_text(brief_text, encoding="utf-8")

    payload = {
        "tool": tool_name,
        "goal": (
            {
                "id": goal.id,
                "title": goal.title,
                "phase": goal.phase,
                "uncertainty": goal.uncertainty,
            }
            if goal is not None
            else None
        ),
        "prompt_path": prompt_rel.as_posix(),
        "brief_path": brief_rel.as_posix(),
        "launch_command": launch_command,
        "context_format": context_format.lower(),
    }

    if json_output:
        _emit_json(payload)
        return

    click.echo(f"Focus pack ready ({tool_name})")
    if goal is not None:
        click.echo(
            f"Goal: {goal.id} | {goal.title} | phase={goal.phase or 'legacy'} | "
            f"uncertainty={goal.uncertainty or 'unknown'}"
        )
    else:
        click.echo("Goal: none selected")
    click.echo(f"Prompt: {prompt_rel.as_posix()}")
    click.echo(f"Brief: {brief_rel.as_posix()}")
    click.echo("Launch:")
    click.echo(f"  {launch_command}")
    click.echo("Next:")
    click.echo("  1. Run the launch command.")
    click.echo("  2. Execute a minimal diff and verify.")
    click.echo("  3. Record outcome with metrics/triage if needed.")


@main.command("map")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def map_command(json_output: bool) -> None:
    """Generate codebase symbol map."""
    from hast.core.analysis import build_symbol_map, format_symbol_map
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


@main.command("explore")
@click.argument("question", nargs=-1, required=True)
@click.option(
    "--max-matches",
    default=20,
    show_default=True,
    type=click.IntRange(min=1, max=200),
    help="Maximum symbol/text matches to include in the report.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def explore_command(question: tuple[str, ...], max_matches: int, json_output: bool) -> None:
    """Read-only design exploration: impact map + candidate approaches."""
    from hast.core.explore import explore_question, format_explore_report, report_to_dict

    question_text = " ".join(part.strip() for part in question if part.strip())
    if not question_text:
        raise click.ClickException("question must be non-empty")

    try:
        root = find_root(Path.cwd())
        report = explore_question(root, question_text, max_matches=max_matches)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "root": root.as_posix(),
                "report": report_to_dict(report),
            }
        )
        return
    click.echo(format_explore_report(report))


@main.command("sim")
@click.argument("goal_id", required=False)
@click.option(
    "--run-tests/--no-run-tests",
    "run_tests",
    default=False,
    show_default=True,
    help="Run baseline test probe using config.test_command.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def sim_command(goal_id: str | None, run_tests: bool, json_output: bool) -> None:
    """Simulate auto readiness and likely failure points without changing code."""
    from hast.core.sim import format_sim_report, report_to_dict, run_simulation

    try:
        root = find_root(Path.cwd())
        report = run_simulation(root, goal_id=goal_id, run_tests=run_tests)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(report_to_dict(report))
        return
    click.echo(format_sim_report(report))


@main.command("handoff")
@click.argument("goal_id", required=False)
@click.option("--stdout", "to_stdout", is_flag=True, help="Print to stdout instead of writing file.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def handoff_command(goal_id: str | None, to_stdout: bool, json_output: bool) -> None:
    """Generate handoff from git history."""
    from hast.core.handoff import generate_handoff

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
    from hast.utils.git import worktree_merge

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
    from hast.utils.git import worktree_list

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


@main.command("doctor")
@click.option(
    "--strict",
    is_flag=True,
    help="Exit non-zero when warnings are present.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def doctor_command(strict: bool, json_output: bool) -> None:
    """Run preflight diagnostics for config, policies, git, and runtime readiness."""
    from hast.core.doctor import format_doctor_report, report_to_dict, run_doctor

    try:
        root = find_root(Path.cwd())
    except DevfError:
        root = Path.cwd().resolve()

    report = run_doctor(root)
    if json_output:
        _emit_json(report_to_dict(report))
    else:
        click.echo(format_doctor_report(report))

    exit_code = 0
    if report.fail_count > 0:
        exit_code = 1
    elif strict and report.warn_count > 0:
        exit_code = 1
    if exit_code:
        raise SystemExit(exit_code)


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
    from hast.core.metrics import build_metrics_report

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


@main.group("observe")
def observe_group() -> None:
    """Observability and readiness commands."""


@main.group("events")
def events_group() -> None:
    """Event bus/reducer commands."""


@main.group("protocol")
def protocol_group() -> None:
    """External orchestration protocol adapters (LangGraph/OpenHands)."""


@protocol_group.command("export")
@click.option(
    "--adapter",
    "adapter_name",
    required=True,
    type=click.Choice(["langgraph", "openhands"], case_sensitive=False),
    help="Target external orchestration adapter.",
)
@click.option("--goal", "goal_id", default=None, help="Goal id (defaults to active goal).")
@click.option(
    "--role",
    "role_name",
    default=None,
    type=click.Choice(["implement", "test", "verify"], case_sensitive=False),
    help="Optional consumer role lane for external worker.",
)
@click.option(
    "--context-format",
    default=None,
    type=click.Choice(["pack", "markdown", "plain", "json"], case_sensitive=False),
    help="Optional context format override.",
)
@click.option(
    "--include-context/--no-include-context",
    default=None,
    help="Override policy default for including context text in packet.",
)
@click.option(
    "--write/--no-write",
    "write_file",
    default=True,
    show_default=True,
    help="Write packet to .ai/protocols/outbox.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def protocol_export_command(
    adapter_name: str,
    goal_id: str | None,
    role_name: str | None,
    context_format: str | None,
    include_context: bool | None,
    write_file: bool,
    json_output: bool,
) -> None:
    from hast.core.protocol_adapters import export_protocol_task_packet

    try:
        root = find_root(Path.cwd())
        result = export_protocol_task_packet(
            root,
            adapter=adapter_name.lower(),
            goal_id=goal_id,
            role=role_name.lower() if isinstance(role_name, str) else None,
            context_format=context_format.lower() if isinstance(context_format, str) else None,
            include_context=include_context,
            write_file=write_file,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "packet": result.packet,
        "packet_path": result.packet_path.as_posix() if result.packet_path else None,
    }
    if json_output:
        _emit_json(payload)
        return

    goal = result.packet.get("goal", {})
    click.echo(
        f"Protocol packet exported: adapter={result.packet.get('adapter')} "
        f"goal={goal.get('goal_id')} role={result.packet.get('execution', {}).get('role')}"
    )
    if result.packet_path:
        click.echo(f"Path: {result.packet_path.as_posix()}")
    else:
        click.echo("Path: (not written; --no-write)")


@protocol_group.command("ingest")
@click.argument("result_packet", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def protocol_ingest_command(result_packet: Path, json_output: bool) -> None:
    from hast.core.protocol_adapters import ingest_protocol_result_packet, load_result_packet_file

    try:
        root = find_root(Path.cwd())
        packet = load_result_packet_file(result_packet)
        result = ingest_protocol_result_packet(root, packet)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "run_id": result.run_id,
        "goal_id": result.goal_id,
        "adapter": result.adapter,
        "evidence_path": result.evidence_path.as_posix(),
        "inbox_path": result.inbox_path.as_posix(),
        "event_id": result.event_id,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(
        f"Protocol result ingested: adapter={result.adapter} goal={result.goal_id} run={result.run_id}"
    )
    click.echo(f"Evidence: {result.evidence_path.as_posix()}")
    click.echo(f"Inbox: {result.inbox_path.as_posix()}")


@main.group("inbox")
def inbox_group() -> None:
    """Operator inbox triage and policy actions."""


@inbox_group.command("list")
@click.option(
    "--include-resolved/--open-only",
    "include_resolved",
    default=False,
    show_default=True,
    help="Include resolved items (approve/reject).",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def inbox_list_command(include_resolved: bool, json_output: bool) -> None:
    from hast.core.operator_inbox import list_inbox_items

    try:
        root = find_root(Path.cwd())
        items = list_inbox_items(root, include_resolved=include_resolved)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "items": items,
                "count": len(items),
                "include_resolved": include_resolved,
            }
        )
        return

    click.echo(f"Operator inbox items: {len(items)}")
    for item in items:
        click.echo(
            f"{item.get('inbox_id')} priority={item.get('priority')} "
            f"reason={item.get('reason_code')} goal={item.get('goal_id') or '(none)'} "
            f"resolved={item.get('resolved')}"
        )


@inbox_group.command("summary")
@click.option(
    "--top-k",
    default=None,
    type=click.IntRange(min=1, max=100),
    help="Max unresolved items to include in summary.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def inbox_summary_command(top_k: int | None, json_output: bool) -> None:
    from hast.core.operator_inbox import summarize_inbox

    try:
        root = find_root(Path.cwd())
        summary = summarize_inbox(root, top_k=top_k)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "total_items": summary.total_items,
        "unresolved_items": summary.unresolved_items,
        "resolved_items": summary.resolved_items,
        "high_priority_unresolved": summary.high_priority_unresolved,
        "by_reason_code": summary.by_reason_code,
        "top_items": summary.top_items,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(
        "Operator inbox summary "
        f"(open={summary.unresolved_items}, resolved={summary.resolved_items}, high={summary.high_priority_unresolved})"
    )
    if summary.by_reason_code:
        click.echo("By reason:")
        for reason, count in sorted(summary.by_reason_code.items()):
            click.echo(f"  - {reason}: {count}")
    if summary.top_items:
        click.echo("Top items:")
        for item in summary.top_items:
            click.echo(
                f"  - {item.get('inbox_id')} [{item.get('priority')}] "
                f"{item.get('reason_code')} :: {item.get('summary')}"
            )


@inbox_group.command("act")
@click.argument("inbox_id")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["approve", "reject", "defer"], case_sensitive=False),
    help="Policy action for the inbox item.",
)
@click.option("--operator", "operator_id", required=True, help="Operator identity.")
@click.option("--reason", default="", help="Optional action rationale.")
@click.option(
    "--goal-status",
    default=None,
    type=click.Choice(
        ["pending", "active", "done", "blocked", "dropped", "obsolete", "superseded", "merged_into"],
        case_sensitive=False,
    ),
    help="Optional goal status transition (policy-authorized only).",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def inbox_act_command(
    inbox_id: str,
    action: str,
    operator_id: str,
    reason: str,
    goal_status: str | None,
    json_output: bool,
) -> None:
    from hast.core.operator_inbox import apply_inbox_action

    try:
        root = find_root(Path.cwd())
        result = apply_inbox_action(
            root,
            inbox_id=inbox_id,
            action=action.lower(),
            operator_id=operator_id,
            reason=reason,
            goal_status=goal_status.lower() if isinstance(goal_status, str) else None,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "inbox_id": result.inbox_id,
        "action": result.action,
        "operator_id": result.operator_id,
        "reason_code": result.reason_code,
        "goal_id": result.goal_id,
        "goal_status": result.goal_status,
        "resolved": result.resolved,
        "actions_path": result.actions_path.as_posix(),
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(
        f"Inbox action recorded: {result.inbox_id} action={result.action} "
        f"goal={result.goal_id or '(none)'} goal_status={result.goal_status or '(unchanged)'}"
    )


@events_group.command("replay")
@click.option(
    "--write/--no-write",
    "write_snapshots",
    default=True,
    show_default=True,
    help="Write reducer snapshots under .ai/state/.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def events_replay_command(write_snapshots: bool, json_output: bool) -> None:
    """Replay event log and optionally materialize reducer snapshots."""
    from hast.core.event_bus import replay_event_log

    try:
        root = find_root(Path.cwd())
        result = replay_event_log(root, write_snapshots=write_snapshots)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "total_events": result.total_events,
        "unique_events": result.unique_events,
        "duplicate_events": result.duplicate_events,
        "goal_count": result.goal_count,
        "inbox_items": result.inbox_items,
        "goal_views_path": result.goal_views_path.as_posix() if result.goal_views_path else None,
        "operator_inbox_path": (
            result.operator_inbox_path.as_posix()
            if result.operator_inbox_path
            else None
        ),
        "write_snapshots": write_snapshots,
    }

    if json_output:
        _emit_json(payload)
        return

    click.echo(
        "Event replay complete "
        f"(total={result.total_events}, unique={result.unique_events}, duplicates={result.duplicate_events})"
    )
    click.echo(f"Goal views: {result.goal_count}")
    click.echo(f"Operator inbox items: {result.inbox_items}")
    if result.goal_views_path and result.operator_inbox_path:
        click.echo(f"Snapshots: {result.goal_views_path.as_posix()}, {result.operator_inbox_path.as_posix()}")
    else:
        click.echo("Snapshots: skipped (--no-write)")


@observe_group.command("baseline")
@click.option(
    "--window",
    "window_days",
    default=14,
    show_default=True,
    type=click.IntRange(min=1, max=365),
    help="Evidence/event aggregation window in days.",
)
@click.option(
    "--write/--no-write",
    "write_report",
    default=True,
    show_default=True,
    help="Write baseline JSON report to .ai/reports/.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def observe_baseline_command(window_days: int, write_report: bool, json_output: bool) -> None:
    """Build observability baseline and readiness verdict."""
    from hast.core.observability import (
        build_observability_baseline,
        write_observability_baseline,
    )

    try:
        root = find_root(Path.cwd())
        report = build_observability_baseline(root, window_days)
        report_path = write_observability_baseline(root, report) if write_report else None
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "window_days": window_days,
        "baseline": asdict(report),
        "report_path": report_path.as_posix() if report_path else None,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(f"Observability baseline ({window_days}d)")
    click.echo(f"Goal runs: {report.goal_runs}")
    click.echo(f"Success rate: {report.success_rate}")
    click.echo(f"First-pass success: {report.first_pass_success_rate}")
    click.echo(f"Retry rate: {report.retry_rate}")
    click.echo(f"Block rate: {report.block_rate}")
    click.echo(f"Security incident rate: {report.security_incident_rate}")
    click.echo(f"Mean attempts to success: {report.mean_attempts_to_success}")
    click.echo(f"MTTR (minutes): {report.mttr_minutes if report.mttr_minutes is not None else '(n/a)'}")
    click.echo(f"Claim attempts: {report.claim_attempts}")
    click.echo(f"Claim collision rate: {report.claim_collision_rate}")
    click.echo(f"Idempotent reuse rate: {report.idempotent_reuse_rate}")
    click.echo(f"Stale lease recoveries: {report.stale_lease_recovery_count}")
    click.echo(f"Baseline ready: {'yes' if report.baseline_ready else 'no'}")
    if report.failing_guards:
        click.echo("Failing guards:")
        for item in report.failing_guards:
            click.echo(f"  - {item}")
    if report_path is not None:
        click.echo(f"Report: {report_path.as_posix()}")


@main.group("immune")
def immune_group() -> None:
    """Immune guardrail commands."""


@main.group("queue")
def queue_group() -> None:
    """Execution queue commands (lease/TTL/idempotency)."""


@queue_group.command("claim")
@click.option("--worker", "worker_id", required=True, help="Worker identity.")
@click.option("--goal", "goal_id", default=None, help="Specific goal id to claim.")
@click.option(
    "--role",
    "role_name",
    default=None,
    type=click.Choice(["implement", "test", "verify"], case_sensitive=False),
    help="Optional consumer role lane filter.",
)
@click.option(
    "--ttl-minutes",
    default=None,
    type=click.IntRange(min=1, max=1440),
    help="Override lease TTL in minutes.",
)
@click.option("--idempotency-key", default=None, help="Idempotency key for duplicate claim retries.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def queue_claim_command(
    worker_id: str,
    goal_id: str | None,
    role_name: str | None,
    ttl_minutes: int | None,
    idempotency_key: str | None,
    json_output: bool,
) -> None:
    from hast.core.execution_queue import claim_goal

    try:
        root = find_root(Path.cwd())
        result = claim_goal(
            root,
            worker_id=worker_id,
            goal_id=goal_id,
            role=role_name.lower() if isinstance(role_name, str) else None,
            ttl_minutes=ttl_minutes,
            idempotency_key=idempotency_key,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "claim_id": result.claim.claim_id,
        "goal_id": result.claim.goal_id,
        "worker_id": result.claim.worker_id,
        "role": result.claim.role,
        "status": result.claim.status,
        "created_at": result.claim.created_at.isoformat(),
        "expires_at": result.claim.expires_at.isoformat(),
        "created": result.created,
        "idempotent_reused": result.idempotent_reused,
        "expired_swept": result.expired_swept,
        "idempotency_key": result.claim.idempotency_key,
    }
    if json_output:
        _emit_json(payload)
        return

    click.echo(
        f"Claimed goal {result.claim.goal_id} with {result.claim.claim_id} "
        f"(worker={result.claim.worker_id}, role={result.claim.role or 'unassigned'}, "
        f"expires={result.claim.expires_at.isoformat()})"
    )
    if result.idempotent_reused:
        click.echo("Idempotency: reused existing active claim.")
    if result.expired_swept:
        click.echo(f"Expired claims swept: {result.expired_swept}")


@queue_group.command("renew")
@click.argument("claim_id")
@click.option("--worker", "worker_id", required=True, help="Worker identity (must own claim).")
@click.option(
    "--ttl-minutes",
    default=None,
    type=click.IntRange(min=1, max=1440),
    help="New lease TTL in minutes from now.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def queue_renew_command(
    claim_id: str,
    worker_id: str,
    ttl_minutes: int | None,
    json_output: bool,
) -> None:
    from hast.core.execution_queue import renew_claim

    try:
        root = find_root(Path.cwd())
        claim = renew_claim(
            root,
            claim_id=claim_id,
            worker_id=worker_id,
            ttl_minutes=ttl_minutes,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "claim_id": claim.claim_id,
        "goal_id": claim.goal_id,
        "worker_id": claim.worker_id,
        "role": claim.role,
        "status": claim.status,
        "expires_at": claim.expires_at.isoformat(),
    }
    if json_output:
        _emit_json(payload)
        return
    click.echo(f"Renewed claim {claim.claim_id} until {claim.expires_at.isoformat()}")


@queue_group.command("release")
@click.argument("claim_id")
@click.option("--worker", "worker_id", required=True, help="Worker identity (must own claim).")
@click.option("--reason", default="", help="Optional release reason.")
@click.option(
    "--goal-status",
    default=None,
    type=click.Choice(
        ["pending", "active", "done", "blocked", "dropped", "obsolete", "superseded", "merged_into"],
        case_sensitive=False,
    ),
    help="Optional goal status update on release.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def queue_release_command(
    claim_id: str,
    worker_id: str,
    reason: str,
    goal_status: str | None,
    json_output: bool,
) -> None:
    from hast.core.execution_queue import release_claim

    try:
        root = find_root(Path.cwd())
        claim = release_claim(
            root,
            claim_id=claim_id,
            worker_id=worker_id,
            reason=reason,
            goal_status=goal_status.lower() if isinstance(goal_status, str) else None,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "claim_id": claim.claim_id,
        "goal_id": claim.goal_id,
        "worker_id": claim.worker_id,
        "role": claim.role,
        "status": claim.status,
        "released_at": claim.released_at.isoformat() if claim.released_at else None,
        "reason": claim.release_reason,
        "goal_status": claim.release_goal_status,
    }
    if json_output:
        _emit_json(payload)
        return
    click.echo(f"Released claim {claim.claim_id} (goal={claim.goal_id}, status={claim.status})")


@queue_group.command("list")
@click.option("--active-only", is_flag=True, help="Show only active claims.")
@click.option("--worker", "worker_id", default=None, help="Filter claims by worker.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def queue_list_command(active_only: bool, worker_id: str | None, json_output: bool) -> None:
    from hast.core.execution_queue import execution_queue_snapshot, list_claims

    try:
        root = find_root(Path.cwd())
        claims = list_claims(root, active_only=active_only, worker_id=worker_id)
        snapshot = execution_queue_snapshot(root)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    rendered = [
        {
            "claim_id": claim.claim_id,
            "goal_id": claim.goal_id,
            "worker_id": claim.worker_id,
            "role": claim.role,
            "status": claim.status,
            "created_at": claim.created_at.isoformat(),
            "expires_at": claim.expires_at.isoformat(),
            "released_at": claim.released_at.isoformat() if claim.released_at else None,
            "idempotency_key": claim.idempotency_key,
        }
        for claim in claims
    ]
    payload = {
        "claims": rendered,
        "snapshot": snapshot,
    }
    if json_output:
        _emit_json(payload)
        return
    click.echo(
        f"Execution queue: active={snapshot['active_claims']} total={snapshot['total_claims']}"
    )
    for item in rendered:
        click.echo(
            f"{item['claim_id']} goal={item['goal_id']} worker={item['worker_id']} "
            f"role={item['role'] or 'unassigned'} "
            f"status={item['status']} expires={item['expires_at']}"
        )


@queue_group.command("sweep")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def queue_sweep_command(json_output: bool) -> None:
    from hast.core.execution_queue import sweep_expired_claims

    try:
        root = find_root(Path.cwd())
        expired = sweep_expired_claims(root)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json({"expired_claims": expired})
        return
    click.echo(f"Expired claims swept: {expired}")


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
    from hast.core.immune_policy import write_repair_grant

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
    from hast.core.docgen import generate_docs
    from hast.core.docs_policy import load_docs_policy, match_high_risk_paths

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
    from hast.core.mermaid import render_mermaid_docs

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
    """Generate `.knowledge/` wikilink pages from hast source artifacts."""
    from hast.core.vault import sync_vault

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
    from hast.core.metrics import build_triage_report

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
    "--lane",
    type=click.Choice(["project", "tool"], case_sensitive=False),
    default="project",
    show_default=True,
    help="Feedback routing lane. tool lane is excluded from goal auto-sync.",
)
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
    lane: str,
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
    from hast.core.feedback import create_feedback_note, write_feedback_note

    try:
        root = find_root(Path.cwd())
        note = create_feedback_note(
            run_id=run_id,
            goal_id=goal_id,
            phase=phase,
            source="worker_explicit",
            lane=lane.lower(),
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
    from hast.core.feedback_infer import infer_and_store_feedback_notes
    from hast.core.feedback_policy import load_feedback_policy

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
@click.option(
    "--lane",
    type=click.Choice(["all", "project", "tool"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Filter notes by lane before backlog aggregation.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_backlog_command(window_days: int, promote: bool, lane: str, json_output: bool) -> None:
    """Build manager backlog candidates from notes."""
    from hast.core.feedback import (
        build_feedback_backlog,
        load_feedback_notes,
        save_feedback_backlog,
    )
    from hast.core.feedback_policy import load_feedback_policy

    try:
        root = find_root(Path.cwd())
        policy = load_feedback_policy(root)
        notes = load_feedback_notes(root, window_days=window_days)
        lane_value = lane.lower()
        if lane_value != "all":
            notes = [note for note in notes if str(note.get("lane") or "project") == lane_value]
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
                "lane": lane_value,
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

    click.echo(f"Window: last {window_days} day(s), lane={lane_value}")
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
@click.option(
    "--lane",
    type=click.Choice(["all", "project", "tool"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Publish backlog items only from the selected lane.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def feedback_publish_command(limit: int, dry_run: bool, lane: str, json_output: bool) -> None:
    """Publish manager-accepted backlog items to Codeberg issues."""
    from hast.core.feedback_policy import load_feedback_policy
    from hast.core.feedback_publish import publish_feedback_backlog

    try:
        root = find_root(Path.cwd())
        policy = load_feedback_policy(root)
        if not policy.publish.enabled and not dry_run:
            raise DevfError(
                "feedback publish is disabled in feedback_policy.yaml "
                "(set publish.enabled: true, or use --dry-run)"
            )
        lane_value = lane.lower()
        lane_filter = None if lane_value == "all" else lane_value
        result = publish_feedback_backlog(
            root,
            policy,
            limit=limit,
            dry_run=dry_run,
            lane=lane_filter,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "limit": limit,
                "dry_run": dry_run,
                "lane": lane_value,
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
    from hast.core.proposals import create_proposal_note, write_proposal_note

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
    from hast.core.proposals import load_proposal_notes

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
    from hast.core.admission import promote_proposals

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
    from hast.core.decision import (
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
    click.echo("Next: fill `scores`, then run `hast decision evaluate <file> --accept`.")


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
    from hast.core.decision import (
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
@click.option(
    "--accept-if-reason",
    "accept_if_reasons",
    multiple=True,
    help="Allow auto-accept only when winner reason code matches (e.g. diff_lines, why:diff_lines).",
)
@click.option(
    "--accept-max-diff-lines",
    type=click.IntRange(min=0),
    default=None,
    help="Allow auto-accept only when winner diff_lines is <= this value.",
)
@click.option(
    "--accept-max-changed-files",
    type=click.IntRange(min=0),
    default=None,
    help="Allow auto-accept only when winner changed_files is <= this value.",
)
@click.option(
    "--accept-require-eligible/--accept-allow-needs-review",
    default=True,
    show_default=True,
    help="With accept-if guard, require matrix evaluation winner_eligible=true before accept.",
)
@click.option("--explain", is_flag=True, help="Print detailed winner explanation.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def decision_spike_command(
    decision_file: str,
    parallel: int,
    command_template: str,
    backend: str,
    actor: str,
    log_evidence: bool,
    accept: bool,
    accept_if_reasons: tuple[str, ...],
    accept_max_diff_lines: int | None,
    accept_max_changed_files: int | None,
    accept_require_eligible: bool,
    explain: bool,
    json_output: bool,
) -> None:
    """Run parallel spikes for all alternatives in a decision ticket."""
    from hast.core.decision import (
        append_decision_evidence,
        apply_decision_result,
        evaluate_decision_ticket,
        load_decision_ticket,
        save_decision_ticket,
    )
    from hast.core.spike import run_decision_spikes

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
        ticket = None
        accepted = False
        guard_enabled = bool(
            accept_if_reasons or accept_max_diff_lines is not None or accept_max_changed_files is not None
        )
        guard_passed = None
        guard_failures: list[str] = []
        normalized_accept_if_reasons = {
            _normalize_reason_code(reason) for reason in accept_if_reasons if reason.strip()
        }

        if guard_enabled and not accept:
            raise DevfError("--accept-if-* options require --accept")

        if accept:
            if guard_enabled:
                guard_passed = True
                winner_row = next(
                    (
                        row
                        for row in result.alternatives
                        if result.winner_id and row.alternative_id == result.winner_id
                    ),
                    None,
                )
                if result.winner_id is None or winner_row is None:
                    guard_failures.append("no winner available from spike result")
                if (
                    normalized_accept_if_reasons
                    and result.winner_reason_code not in normalized_accept_if_reasons
                ):
                    allowed = ", ".join(sorted(normalized_accept_if_reasons))
                    guard_failures.append(
                        f"winner_reason_code={result.winner_reason_code} not in [{allowed}]"
                    )
                if (
                    accept_max_diff_lines is not None
                    and winner_row is not None
                    and winner_row.diff_lines > accept_max_diff_lines
                ):
                    guard_failures.append(
                        f"winner diff_lines={winner_row.diff_lines} exceeds max={accept_max_diff_lines}"
                    )
                if (
                    accept_max_changed_files is not None
                    and winner_row is not None
                    and winner_row.changed_files > accept_max_changed_files
                ):
                    guard_failures.append(
                        f"winner changed_files={winner_row.changed_files} exceeds max={accept_max_changed_files}"
                    )

                ticket = load_decision_ticket(path)
                evaluation = evaluate_decision_ticket(ticket)
                if evaluation.winner_id != result.winner_id:
                    guard_failures.append(
                        "decision matrix winner does not match spike winner "
                        f"({evaluation.winner_id} != {result.winner_id})"
                    )
                if accept_require_eligible and not evaluation.winner_eligible:
                    guard_failures.append("decision matrix winner_eligible is false")

                guard_passed = not guard_failures
            else:
                ticket = load_decision_ticket(path)
                evaluation = evaluate_decision_ticket(ticket)

            if not guard_enabled or guard_passed:
                assert ticket is not None
                ticket = apply_decision_result(ticket, evaluation, actor=actor)
                save_decision_ticket(path, ticket)
                accepted = True
                if log_evidence:
                    evidence_path = append_decision_evidence(
                        root=root,
                        decision_file=path,
                        ticket=ticket,
                        evaluation=evaluation,
                        run_id=None,
                        actor=actor,
                    )
            else:
                accepted = False
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    ranked_alternatives = sorted(
        result.alternatives,
        key=lambda item: (item.comparison_rank or 9999, item.alternative_id),
    )
    alternatives = [
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
            "command": row.command,
            "output_file": row.output_file,
            "metadata_file": row.metadata_file,
        }
        for row in ranked_alternatives
    ]

    if json_output:
        _emit_json(
            {
                "summary_path": result.summary_path.relative_to(root).as_posix(),
                "winner_id": result.winner_id,
                "winner_reason": result.winner_reason,
                "winner_reason_code": result.winner_reason_code,
                "winner_reason_detail": result.winner_reason_detail,
                "winner_vs_runner_up": result.winner_vs_runner_up,
                "escalated": result.escalated,
                "alternatives": alternatives,
                "accept": accept,
                "accept_if_guard_enabled": guard_enabled,
                "accept_if_guard_passed": guard_passed,
                "accept_if_guard_failures": guard_failures,
                "accepted": accepted,
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
    click.echo(f"Winner reason: {result.winner_reason}")
    if explain:
        click.echo(f"Winner detail: {result.winner_reason_detail}")
        if result.winner_vs_runner_up is not None:
            criterion = result.winner_vs_runner_up.get("criterion")
            winner_alt = result.winner_vs_runner_up.get("winner_id")
            runner_up_alt = result.winner_vs_runner_up.get("runner_up_id")
            click.echo(
                "Winner compare: "
                f"criterion={criterion} winner={winner_alt} runner_up={runner_up_alt}"
            )
    for row in ranked_alternatives:
        status = "PASS" if row.passed else "FAIL"
        click.echo(
            f"  {row.alternative_id}: {status} "
            f"rank={row.comparison_rank} "
            f"exit={row.exit_code} duration_ms={row.duration_ms} "
            f"diff_lines={row.diff_lines} changed_files={row.changed_files}"
        )
    if accept:
        if accepted and ticket is not None:
            click.echo(
                f"Decision updated: status={ticket.get('status')} "
                f"selected={ticket.get('selected_alternative')}"
            )
            if log_evidence and evidence_path is not None:
                click.echo(
                    f"Decision evidence appended: {evidence_path.relative_to(root).as_posix()}"
                )
        elif guard_enabled:
            click.echo("Decision auto-accept skipped by guard:")
            for reason in guard_failures:
                click.echo(f"  - {reason}")


@main.command("rotate")
@click.option(
    "--max-size-mb",
    default=5,
    show_default=True,
    type=click.IntRange(min=1),
    help="Size threshold in megabytes.",
)
@click.option(
    "--max-age-days",
    default=30,
    show_default=True,
    type=click.IntRange(min=1),
    help="Age threshold in days.",
)
@click.option("--dry-run", is_flag=True, help="List files without moving.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def rotate_command(
    max_size_mb: int,
    max_age_days: int,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Rotate large or old JSONL files to .ai/archive/."""
    from hast.utils.rotation import rotate_files

    try:
        root = find_root(Path.cwd())
        results = rotate_files(
            root,
            max_size_bytes=max_size_mb * 1024 * 1024,
            max_age_days=max_age_days,
            dry_run=dry_run,
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        from dataclasses import asdict

        _emit_json({
            "dry_run": dry_run,
            "rotated": [asdict(r) for r in results],
            "count": len(results),
        })
        return

    if not results:
        click.echo("No files require rotation.")
        return

    label = "Would rotate" if dry_run else "Rotated"
    for r in results:
        click.echo(f"{label}: {r.original_path} -> {r.archive_path} ({r.reason})")
    click.echo(f"Total: {len(results)} file(s)")


@main.command("auto")
@click.argument("goal_id", required=False)
@click.option("--recursive", is_flag=True, help="Run active goals under the goal.")
@click.option("--dry-run", is_flag=True, help="Print dry-run summary and exit.")
@click.option(
    "--dry-run-full",
    is_flag=True,
    help="With --dry-run, print full prompt(s) instead of summary.",
)
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
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def auto_command(
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    dry_run_full: bool,
    explain: bool,
    tool_name: str | None,
    parallelism: int,
    json_output: bool,
) -> None:
    """Run automated loop."""
    try:
        if dry_run_full and not dry_run:
            raise click.ClickException("--dry-run-full requires --dry-run")
        root = find_root(Path.cwd())

        result = run_auto(
            root=root,
            goal_id=goal_id,
            recursive=recursive,
            dry_run=dry_run,
            dry_run_full=dry_run_full,
            explain=explain,
            tool_name=tool_name,
            parallelism=parallelism,
        )
    except DevfError as exc:
        if json_output:
            _emit_json({"exit_code": 1, "error": str(exc)})
            raise SystemExit(1) from exc
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(result.to_dict())

    raise SystemExit(result.exit_code)


@main.command("retry")
@click.argument("goal_id")
@click.option("--tool", "tool_name", default=None, help="Override AI tool name for rerun.")
@click.option("--no-run", is_flag=True, help="Only reactivate goal and clear attempts.")
@click.option("--keep-attempts", is_flag=True, help="Do not clear .ai/attempts/<goal_id> logs.")
@click.option(
    "--sim/--no-sim",
    "run_sim",
    default=True,
    show_default=True,
    help="Run simulation preview and surface recommended actions before rerun.",
)
@click.option(
    "--no-preflight",
    is_flag=True,
    help="Emergency bypass: rerun auto without doctor preflight checks.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def retry_command(
    goal_id: str,
    tool_name: str | None,
    no_run: bool,
    keep_attempts: bool,
    run_sim: bool,
    no_preflight: bool,
    json_output: bool,
) -> None:
    """One-command recovery: reactivate blocked goal and optionally rerun auto."""
    from hast.core.attempt import clear_attempts
    from hast.core.goals import update_goal_status

    try:
        root = find_root(Path.cwd())
        goals_path = root / ".ai" / "goals.yaml"
        update_goal_status(goals_path, goal_id, "active")
        if not keep_attempts:
            clear_attempts(root, goal_id)

        simulation_payload: dict[str, object] | None = None
        if run_sim:
            from hast.core.sim import run_simulation

            try:
                sim_report = run_simulation(root, goal_id=goal_id, run_tests=False)
                simulation_payload = {
                    "status": sim_report.status,
                    "risk_score": sim_report.risk_score,
                    "ready": sim_report.ready,
                    "recommended_actions": sim_report.recommended_actions[:5],
                }
            except DevfError as exc:
                simulation_payload = {
                    "status": "unavailable",
                    "risk_score": None,
                    "ready": False,
                    "recommended_actions": [f"simulation unavailable: {exc}"],
                }
        if no_run:
            exit_code = 0
        else:
            exit_code = run_auto(
                root=root,
                goal_id=goal_id,
                recursive=False,
                dry_run=False,
                explain=False,
                tool_name=tool_name,
                parallelism=1,
                preflight=not no_preflight,
            )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(
            {
                "goal_id": goal_id,
                "reactivated": True,
                "attempts_cleared": not keep_attempts,
                "ran_auto": not no_run,
                "preflight_enabled": (not no_preflight) if not no_run else None,
                "simulation": simulation_payload if run_sim else None,
                "exit_code": exit_code,
            }
        )
    else:
        click.echo(f"Goal reactivated: {goal_id}")
        click.echo(f"Attempts cleared: {not keep_attempts}")
        if run_sim and simulation_payload is not None:
            status = str(simulation_payload.get("status") or "unknown")
            risk = simulation_payload.get("risk_score")
            click.echo(f"Simulation: status={status} risk={risk}")
            for action in simulation_payload.get("recommended_actions", [])[:3]:
                click.echo(f"  sim> {action}")
        if no_run:
            click.echo("Auto rerun: skipped (--no-run)")
        else:
            click.echo(f"Auto rerun exit code: {exit_code}")

    raise SystemExit(exit_code)


@main.command("plan")
@click.argument("instruction", required=False)
@click.option("--autonomous", is_flag=True, help="Run in continuous autonomous loop.")
@click.option("--tool", "tool_name", help="Override AI tool name.")
def plan_command(instruction: str | None, autonomous: bool, tool_name: str | None) -> None:
    """Architect mode: Plan goals from instructions."""
    from hast.core.architect import plan_goals
    from hast.core.auto import run_auto

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
                click.echo(f"Goal {goal_id} created. Run 'hast auto {goal_id}' to execute.")

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
@click.option(
    "--baseline-window",
    default=None,
    type=click.IntRange(min=1, max=365),
    help="Optional baseline window in days (defaults to --window).",
)
@click.option(
    "--enforce-baseline/--no-enforce-baseline",
    default=False,
    show_default=True,
    help="Block orchestrate when observability baseline is not ready.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def orchestrate_command(
    run_id: str | None,
    window_days: int,
    max_goals: int,
    publish: bool,
    publish_dry_run: bool,
    baseline_window: int | None,
    enforce_baseline: bool,
    json_output: bool,
) -> None:
    """Run productivity cycle for project lane: analyze -> backlog -> goals -> optional publish."""
    from hast.core.orchestrator import orchestrate_productivity_cycle

    try:
        root = find_root(Path.cwd())
        result = orchestrate_productivity_cycle(
            root,
            run_id=run_id,
            window_days=window_days,
            max_goals=max_goals,
            publish=publish,
            publish_dry_run=publish_dry_run,
            baseline_window_days=baseline_window,
            enforce_baseline=enforce_baseline,
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
                "baseline_ready": result.baseline_ready,
                "baseline_failing_guards": list(result.baseline_failing_guards),
                "baseline_window_days": result.baseline_window_days,
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
    click.echo(
        "Baseline ready: "
        + ("yes" if result.baseline_ready else "no")
        + f" (window={result.baseline_window_days}d)"
    )
    if result.baseline_failing_guards:
        click.echo("Baseline failing guards:")
        for item in result.baseline_failing_guards:
            click.echo(f"  - {item}")
    if result.publish_result is not None:
        click.echo(
            f"Publish attempted={result.publish_result.attempted} "
            f"published={result.publish_result.published} "
            f"failed={result.publish_result.failed}"
        )
