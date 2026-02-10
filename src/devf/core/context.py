"""Context assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from devf.core.config import Config, load_config
from devf.core.errors import DevfError
from devf.core.goals import Goal, find_goal_node, load_goals, select_active_goal
from devf.core.handoff import (
    extract_section_lines,
    find_latest_handoff,
    parse_context_files,
)
from devf.core.session import find_latest_session
from devf.utils.codetools import code_structure_snapshot, impact_analysis
from devf.utils.fs import find_project_root
from devf.utils.git import get_changed_files, git_change_summary


@dataclass(frozen=True)
class ContextData:
    current_goal: dict[str, Any] | None
    previous_session: dict[str, Any] | None
    task: list[str]
    context_files: list[str]
    rules: list[str]
    git_summary: str = ""
    code_overview: str = ""


def build_context(
    root: Path,
    format_name: str,
    max_context_bytes: int | None = None,
    goal_override: Any | None = None,
) -> str:
    config = _load_config_or_default(root)
    if max_context_bytes is None:
        max_context_bytes = config.max_context_bytes

    data = build_context_data(root, config, goal_override=goal_override)
    rendered = render_context(data, format_name)
    if len(rendered.encode("utf-8")) <= max_context_bytes:
        return rendered

    trimmed = trim_context_data(data)
    rendered = render_context(trimmed, format_name)
    if len(rendered.encode("utf-8")) <= max_context_bytes:
        return rendered

    # Last resort: trim rules to fit.
    if trimmed.rules:
        trimmed = ContextData(
            current_goal=trimmed.current_goal,
            previous_session=trimmed.previous_session,
            task=trimmed.task,
            context_files=trimmed.context_files,
            rules=_trim_lines_to_bytes(trimmed.rules, max_context_bytes // 2),
            git_summary=trimmed.git_summary,
            code_overview=trimmed.code_overview,
        )
    return render_context(trimmed, format_name)


def build_context_data(
    root: Path, config: Config, goal_override: Any | None = None,
) -> ContextData:
    goals = load_goals(root / ".ai" / "goals.yaml")

    # Try session logs first, fall back to handoffs
    session = find_latest_session(root / ".ai" / "sessions")
    handoff = None
    if session is None:
        handoff = find_latest_handoff(root / ".ai" / "handoffs", since=None)

    if goal_override is not None:
        current_goal = goal_override
    else:
        preferred_id = None
        if session:
            preferred_id = session.goal_id
        elif handoff:
            preferred_id = handoff.goal_id
        current_goal = select_active_goal(goals, preferred_id)

    current_goal_data: dict[str, Any] | None = None
    if current_goal:
        node = find_goal_node(goals, current_goal.id)
        parent = node.parent if node else None
        current_goal_data = {
            "id": current_goal.id,
            "title": current_goal.title,
            "status": current_goal.status,
            "parent": None,
            "notes": current_goal.notes,
            "acceptance": current_goal.acceptance or [],
        }
        if parent:
            current_goal_data["parent"] = {
                "id": parent.id,
                "title": parent.title,
                "status": parent.status,
            }

    previous_session: dict[str, Any] | None = None
    if session:
        # Session log context (git-derived)
        last_commit_msg = ""
        if session.commits:
            last_commit_msg = session.commits[-1][1]
        previous_session = {
            "source": "session_log",
            "goal_id": session.goal_id,
            "status": session.status,
            "last_commit": last_commit_msg,
            "test_results": session.test_summary,
            "changes": session.changes,
        }
    elif handoff:
        previous_session = {
            "source": "handoff",
            "timestamp": handoff.timestamp.isoformat(),
            "status": handoff.status,
            "done": extract_section_lines(handoff, "Done"),
            "key_decisions": extract_section_lines(handoff, "Key Decisions"),
            "next": extract_section_lines(handoff, "Next"),
        }

    task_lines: list[str] = []
    if goal_override is not None and current_goal is not None:
        # auto mode: task is the specific goal being worked on
        task_lines = [f"{current_goal.id} — {current_goal.title}"]
    elif goal_override is None:
        if handoff:
            # interactive mode with handoff: prefer handoff's Next section for continuity
            next_lines = extract_section_lines(handoff, "Next")
            if next_lines:
                task_lines = next_lines
            elif current_goal:
                task_lines = [f"{current_goal.id} — {current_goal.title}"]
        elif current_goal:
            task_lines = [f"{current_goal.id} — {current_goal.title}"]

    context_lines: list[str] = []
    if session:
        # Extract file paths from diff --stat output
        for line in session.changes.splitlines():
            line = line.strip()
            if "|" in line:
                file_path = line.split("|")[0].strip()
                if file_path:
                    context_lines.append(file_path)
    elif handoff:
        context_lines = parse_context_files(extract_section_lines(handoff, "Context Files"))

    rules = _load_rules(root / ".ai" / "rules.md")

    # Git change summary
    git_summary = ""
    since_commit = session.base_commit if session else None
    try:
        git_summary = git_change_summary(root, since_commit)
    except Exception:
        pass  # git not available or not a repo

    # Code structure + impact analysis
    code_overview = ""
    try:
        structure = code_structure_snapshot(root)
        if structure:
            code_overview = structure
        if since_commit:
            changed = get_changed_files(root, since_commit)
            impact_text = impact_analysis(changed, root)
            if impact_text:
                sep = "\n\n" if code_overview else ""
                code_overview += f"{sep}Impact:\n{impact_text}"
    except Exception:
        pass  # graceful degradation

    return ContextData(
        current_goal=current_goal_data,
        previous_session=previous_session,
        task=task_lines,
        context_files=context_lines,
        rules=rules,
        git_summary=git_summary,
        code_overview=code_overview,
    )


def render_context(data: ContextData, format_name: str) -> str:
    if format_name == "json":
        payload = {
            "current_goal": data.current_goal,
            "previous_session": data.previous_session,
            "git_summary": data.git_summary or None,
            "task": data.task,
            "context_files": data.context_files,
            "rules": data.rules,
            "code_overview": data.code_overview or None,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if format_name == "plain":
        return render_plain(data)
    if format_name == "markdown":
        return render_markdown(data)
    raise DevfError(f"unknown format: {format_name}")


def render_plain(data: ContextData) -> str:
    lines: list[str] = []
    lines.append("SESSION CONTEXT")
    lines.append("")

    lines.append("CURRENT GOAL")
    if data.current_goal:
        lines.append(f"{data.current_goal['id']} — {data.current_goal['title']}")
        parent = data.current_goal.get("parent")
        if parent:
            lines.append(f"PARENT: {parent['id']} — {parent['title']} ({parent['status']})")
        notes = data.current_goal.get("notes")
        if notes:
            lines.append(f"NOTES: {notes}")
        acceptance = data.current_goal.get("acceptance", [])
        if acceptance:
            lines.append("ACCEPTANCE CRITERIA:")
            for item in acceptance:
                lines.append(f"  - {item}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("PREVIOUS SESSION")
    if data.previous_session:
        source = data.previous_session.get("source", "handoff")
        if source == "session_log":
            lines.append(f"Goal: {data.previous_session['goal_id']} ({data.previous_session['status']})")
            last_commit = data.previous_session.get("last_commit", "")
            if last_commit:
                lines.append(f"LAST COMMIT: {last_commit}")
            test_results = data.previous_session.get("test_results", "")
            if test_results:
                lines.append(f"TESTS: {test_results}")
        else:
            lines.append(
                f"{data.previous_session['timestamp']} ({data.previous_session['status']})"
            )
            done = data.previous_session.get("done", [])
            key = data.previous_session.get("key_decisions", [])
            if done:
                lines.append(f"DONE: {done[0]}")
            if key:
                lines.append(f"KEY DECISION: {key[0]}")
    else:
        lines.append("None")
    lines.append("")

    if data.git_summary:
        lines.append("RECENT CHANGES")
        for gl in data.git_summary.splitlines():
            lines.append(gl)
        lines.append("")

    lines.append("YOUR TASK")
    if data.task:
        for line in data.task:
            lines.append(f"- {line}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("CONTEXT FILES")
    if data.context_files:
        for line in data.context_files:
            lines.append(f"- {line}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("RULES")
    if data.rules:
        for line in data.rules:
            lines.append(f"- {line}")
    else:
        lines.append("None")

    if data.code_overview:
        lines.append("")
        lines.append("CODE OVERVIEW")
        for gl in data.code_overview.splitlines():
            lines.append(gl)

    return "\n".join(lines)


def render_markdown(data: ContextData) -> str:
    lines: list[str] = []
    lines.append("# Session Context")
    lines.append("")
    lines.append("## Current Goal")
    if data.current_goal:
        lines.append(f"{data.current_goal['id']} — {data.current_goal['title']}")
        parent = data.current_goal.get("parent")
        if parent:
            lines.append(f"Parent: {parent['id']} — {parent['title']} ({parent['status']})")
        notes = data.current_goal.get("notes")
        if notes:
            lines.append(f"**Notes:** {notes}")
        acceptance = data.current_goal.get("acceptance", [])
        if acceptance:
            lines.append("**Acceptance Criteria:**")
            for item in acceptance:
                lines.append(f"- {item}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("## Previous Session")
    if data.previous_session:
        source = data.previous_session.get("source", "handoff")
        if source == "session_log":
            lines.append(f"Goal: {data.previous_session['goal_id']} ({data.previous_session['status']})")
            last_commit = data.previous_session.get("last_commit", "")
            if last_commit:
                lines.append(f"Last commit: {last_commit}")
            test_results = data.previous_session.get("test_results", "")
            if test_results:
                lines.append(f"Tests: {test_results}")
        else:
            lines.append(f"{data.previous_session['timestamp']} ({data.previous_session['status']})")
            done = data.previous_session.get("done", [])
            key = data.previous_session.get("key_decisions", [])
            if done:
                lines.append(f"Done: {done[0]}")
            if key:
                lines.append(f"Key Decision: {key[0]}")
    else:
        lines.append("None")
    lines.append("")

    if data.git_summary:
        lines.append("## Recent Changes")
        for gl in data.git_summary.splitlines():
            lines.append(gl)
        lines.append("")

    lines.append("## Your Task")
    if data.task:
        for line in data.task:
            lines.append(f"- {line}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("## Context Files (read these first)")
    if data.context_files:
        for idx, line in enumerate(data.context_files, start=1):
            lines.append(f"{idx}. {line}")
    else:
        lines.append("None")
    lines.append("")

    lines.append("## Rules")
    if data.rules:
        for line in data.rules:
            lines.append(f"- {line}")
    else:
        lines.append("None")

    if data.code_overview:
        lines.append("")
        lines.append("## Code Overview")
        lines.append("```")
        for gl in data.code_overview.splitlines():
            lines.append(gl)
        lines.append("```")

    return "\n".join(lines)


def trim_context_data(data: ContextData) -> ContextData:
    trimmed_prev = None
    if data.previous_session:
        source = data.previous_session.get("source", "handoff")
        if source == "session_log":
            trimmed_prev = {
                "source": "session_log",
                "goal_id": data.previous_session.get("goal_id"),
                "status": data.previous_session.get("status"),
                "last_commit": data.previous_session.get("last_commit", ""),
                "test_results": data.previous_session.get("test_results", ""),
                "changes": "",
            }
        else:
            trimmed_prev = {
                "source": "handoff",
                "timestamp": data.previous_session.get("timestamp"),
                "status": data.previous_session.get("status"),
                "done": data.previous_session.get("done", [])[:1],
                "key_decisions": data.previous_session.get("key_decisions", [])[:1],
                "next": [],
            }

    # Trim git_summary to 3 lines max
    trimmed_git = ""
    if data.git_summary:
        git_lines = data.git_summary.splitlines()
        trimmed_git = "\n".join(git_lines[:4])  # header + 3 commits
        if len(git_lines) > 4:
            trimmed_git += "\n..."

    return ContextData(
        current_goal=data.current_goal,
        previous_session=trimmed_prev,
        task=data.task[:3],
        context_files=data.context_files[:5],
        rules=data.rules,
        git_summary=trimmed_git,
        code_overview="",  # drop code_overview first (reference material)
    )


def _trim_lines_to_bytes(lines: list[str], max_bytes: int) -> list[str]:
    total = 0
    trimmed: list[str] = []
    for line in lines:
        line_bytes = len((line + "\n").encode("utf-8"))
        if total + line_bytes > max_bytes:
            break
        trimmed.append(line)
        total += line_bytes
    if len(trimmed) < len(lines):
        trimmed.append("... (truncated)")
    return trimmed


def _load_rules(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        lines.append(stripped)
    return lines


def _load_config_or_default(root: Path) -> Config:
    try:
        config, _warnings = load_config(root / ".ai" / "config.yaml")
        return config
    except DevfError:
        return Config(test_command="pytest", ai_tool="claude -p {prompt}")


def find_root(start: Path) -> Path:
    root = find_project_root(start)
    if root is None:
        raise DevfError("could not find .ai directory (run devf init first)")
    return root
