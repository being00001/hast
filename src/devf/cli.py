"""devf CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click

from devf.core.auto import run_auto
from devf.core.context import build_context, find_root
from devf.core.errors import DevfError
from devf.core.init_project import init_project


@click.group()
def main() -> None:
    """devf CLI."""


@main.command("init")
def init_command() -> None:
    """Initialize .ai/ with templates."""
    try:
        created = init_project(Path.cwd())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if not created:
        click.echo("No changes (already initialized).")
        return

    click.echo("Created .ai/")
    click.echo("  ├── config.yaml")
    click.echo("  ├── goals.yaml")
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
    type=click.Choice(["markdown", "plain", "json"], case_sensitive=False),
    default="markdown",
    show_default=True,
)
def context_command(format_name: str) -> None:
    """Assemble session context."""
    try:
        root = find_root(Path.cwd())
        output = build_context(root, format_name.lower())
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(output)


@main.command("handoff")
@click.argument("goal_id", required=False)
@click.option("--stdout", "to_stdout", is_flag=True, help="Print to stdout instead of writing file.")
def handoff_command(goal_id: str | None, to_stdout: bool) -> None:
    """Generate handoff from git history."""
    from devf.core.handoff import generate_handoff

    try:
        root = find_root(Path.cwd())
        content, filename = generate_handoff(root, goal_id)
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc

    if to_stdout:
        click.echo(content)
        return

    path = root / ".ai" / "handoffs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    click.echo(f"Handoff written to .ai/handoffs/{filename}")


@main.command("auto")
@click.argument("goal_id", required=False)
@click.option("--recursive", is_flag=True, help="Run active goals under the goal.")
@click.option("--dry-run", is_flag=True, help="Print prompt and exit.")
@click.option("--explain", is_flag=True, help="Explain outcome decisions.")
@click.option("--tool", "tool_name", help="Override AI tool name.")
def auto_command(
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    explain: bool,
    tool_name: str | None,
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
        )
    except DevfError as exc:
        raise click.ClickException(str(exc)) from exc
    raise SystemExit(exit_code)
