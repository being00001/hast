"""Context assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import ast
import json
from typing import Any, Iterable

from hast.core.analysis import build_symbol_map, format_symbol_map
from hast.core.config import Config, load_config
from hast.core.errors import DevfError
from hast.core.goals import find_goal_node, load_goals, select_active_goal
from hast.core.handoff import (
    extract_section_lines,
    find_latest_handoff,
    parse_context_files,
)
from hast.core.session import find_latest_session
from hast.utils.codetools import build_import_map, find_related_tests, impact_analysis
from hast.utils.fs import find_project_root
from hast.utils.git import get_changed_files, git_change_summary


@dataclass(frozen=True)
class ContextData:
    current_goal: dict[str, Any] | None
    previous_session: dict[str, Any] | None
    task: list[str]
    context_files: list[str]
    rules: list[str]
    git_summary: str = ""
    code_overview: str = ""
    file_contents: dict[str, str] = field(default_factory=dict)
    suggested_tests: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


CODE_OVERVIEW_LIMIT = 40
CONTEXT_FILE_LIMIT = 5
FILE_CONTENT_MAX_LINES = 500
FILE_CONTENT_MAX_BYTES = 20_000


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

    # Stage 1: drop file_contents (largest payload)
    lite = ContextData(
        current_goal=data.current_goal,
        previous_session=data.previous_session,
        task=data.task,
        context_files=data.context_files,
        rules=data.rules,
        git_summary=data.git_summary,
        code_overview=data.code_overview,
        file_contents={},
        suggested_tests=data.suggested_tests,
        warnings=data.warnings,
    )
    rendered = render_context(lite, format_name)
    if len(rendered.encode("utf-8")) <= max_context_bytes:
        return rendered

    # Stage 2: drop code_overview + trim session/git
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
            "test_files": current_goal.test_files or [],
            "allowed_changes": current_goal.allowed_changes or [],
            "agent": getattr(current_goal, "agent", None),
            "phase": getattr(current_goal, "phase", None),
            "contract_file": getattr(current_goal, "contract_file", None),
            "decision_file": getattr(current_goal, "decision_file", None),
            "uncertainty": getattr(current_goal, "uncertainty", None),
            "languages": getattr(current_goal, "languages", None) or [],
            "impact": getattr(current_goal, "impact", None),
            "edge_cases": getattr(current_goal, "edge_cases", None) or [],
            "capability_refs": getattr(current_goal, "capability_refs", None) or [],
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

    rules_path = config.rules_path
    if rules_path:
        rules = _load_rules(root / rules_path)
    else:
        # Fallback chain: .ai/rules.md -> CLAUDE.md
        rules = _load_rules(root / ".ai" / "rules.md")
        if not rules:
            rules = _load_rules(root / "CLAUDE.md")

    plan_note_lines = _load_rules(root / ".ai" / "plan_note.md")
    if plan_note_lines:
        rules = [
            "[PLAN_NOTE] Keep this active every session. Edit: .ai/plan_note.md",
            *plan_note_lines,
            *rules,
        ]

    # Git change summary
    git_summary = ""
    since_commit = session.base_commit if session else None
    try:
        git_summary = git_change_summary(root, since_commit)
    except Exception:
        pass  # git not available or not a repo

    # Code structure + impact analysis
    code_overview = ""
    if config.codemap_path:
        cm_path = root / config.codemap_path
        if cm_path.exists():
            try:
                code_overview = cm_path.read_text(encoding="utf-8")
            except Exception as e:
                warnings_list.append(f"Failed to read codemap_path: {e}")

    file_contents: dict[str, str] = {}
    suggested_tests: list[str] = []
    warnings_list: list[str] = []
    try:
        # Scoping: Tier 1 (Context Files + Test Files + Allowed Changes)
        tier1_raw = set(context_lines)
        if current_goal_data:
            tier1_raw.update(current_goal_data.get("test_files", []))
            tier1_raw.update(current_goal_data.get("allowed_changes", []))

        # Expand globs + normalize
        tier1_files, missing = _expand_paths(root, tier1_raw)
        if missing:
            for m in missing:
                warnings_list.append(f"Missing path or no glob matches: {m}")

        # Fallback context files if none provided
        if not context_lines and tier1_files:
            context_lines = _select_context_files(tier1_files, CONTEXT_FILE_LIMIT)

        # Scoping: Tier 2 (1-hop neighbors)
        tier2_files = set()
        import_map, module_to_file = build_import_map(root)
        from hast.utils.codetools import file_to_module

        # 1. Who imports Tier 1? (importers)
        for f in tier1_files:
            module_name = file_to_module(f)
            if module_name and module_name in import_map:
                tier2_files.update(import_map[module_name])

        # 2. What does Tier 1 import? (forward deps)
        for f in tier1_files:
            forward = _extract_forward_deps(root / f, module_to_file)
            if forward:
                tier2_files.update(forward)

        # 3. Limit Tier 2 with Priority
        if len(tier2_files) > CODE_OVERVIEW_LIMIT:
            sorted_files = sorted(list(tier2_files), key=_get_priority, reverse=True)
            tier2_files = set(sorted_files[:CODE_OVERVIEW_LIMIT])

        # Combine
        scope_files = tier1_files | tier2_files

        symbol_map_files = list(scope_files) if scope_files else None

        # Only build symbol map if code_overview is still empty
        if not code_overview:
            symbol_map = build_symbol_map(root, symbol_map_files)
            structure = format_symbol_map(symbol_map)
            if structure:
                code_overview = structure

        # Read file contents for Tier 1 files
        file_contents = _read_file_contents(root, tier1_files)

        # Identify tests that import files in the current scope
        suggested_tests = find_related_tests(root, list(tier1_files))

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
        file_contents=file_contents,
        suggested_tests=suggested_tests,
        warnings=warnings_list,
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
            "file_contents": data.file_contents or None,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if format_name == "plain":
        return render_plain(data)
    if format_name == "markdown":
        return render_markdown(data)
    if format_name == "pack":
        return render_pack(data)
    raise DevfError(f"unknown format: {format_name}")


def render_pack(data: ContextData) -> str:
    """Render context as an XML pack for AI."""
    lines = ['<context_pack version="1">']

    # Meta question for Opus sessions (autonomous dev loop)
    if data.current_goal and data.current_goal.get("agent") == "opus":
        lines.append('  <meta_question>이 변경 이후에 달라지는 것은 Being인가, Being의 코드인가?</meta_question>')

    if data.current_goal:
        lines.append(f'  <task id="{data.current_goal["id"]}">{data.current_goal["title"]}</task>')

        lines.append("  <constraints>")
        if data.current_goal.get("test_files"):
            for tf in data.current_goal["test_files"]:
                lines.append(f"    <must_pass>{tf}</must_pass>")
        if data.current_goal.get("allowed_changes"):
            for ac in data.current_goal["allowed_changes"]:
                lines.append(f"    <allowed_changes>{ac}</allowed_changes>")
        if data.current_goal.get("acceptance"):
            for item in data.current_goal["acceptance"]:
                lines.append(f"    <criteria>{item}</criteria>")
        if data.current_goal.get("edge_cases"):
            for item in data.current_goal["edge_cases"]:
                lines.append(f"    <edge_case>{item}</edge_case>")
        if data.current_goal.get("contract_file"):
            lines.append(f"    <contract_file>{data.current_goal['contract_file']}</contract_file>")
        if data.current_goal.get("decision_file"):
            lines.append(f"    <decision_file>{data.current_goal['decision_file']}</decision_file>")
        if data.current_goal.get("uncertainty"):
            lines.append(f"    <uncertainty>{data.current_goal['uncertainty']}</uncertainty>")
        lines.append("  </constraints>")

        if data.current_goal.get("notes"):
             lines.append(f"  <notes>{data.current_goal['notes']}</notes>")

    if data.previous_session or data.suggested_tests:
        lines.append("  <evidence>")
        if data.previous_session:
            status = data.previous_session.get("status", "unknown")
            lines.append(f'    <last_session_status>{status}</last_session_status>')
        if data.suggested_tests:
            lines.append("    <suggested_tests>")
            for t in data.suggested_tests:
                lines.append(f"      <test>{t}</test>")
            lines.append("    </suggested_tests>")
        lines.append("  </evidence>")

    if data.file_contents:
        lines.append("  <target_files>")
        for fpath in sorted(data.file_contents):
            content = data.file_contents[fpath]
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            escaped = _xml_escape(content)
            lines.append(f'    <source path="{fpath}" lines="{line_count}">')
            lines.append(escaped)
            lines.append("    </source>")
        lines.append("  </target_files>")

    if data.context_files or data.code_overview:
        lines.append("  <reference>")
        if data.context_files:
            for f in data.context_files:
                 lines.append(f"    <file>{f}</file>")
        if data.code_overview:
            lines.append("    <code_map>")
            # Indent code overview
            for line in data.code_overview.splitlines():
                lines.append(f"      {line}")
            lines.append("    </code_map>")
        lines.append("  </reference>")

    if data.rules:
        lines.append("  <rules>")
        for r in data.rules:
            lines.append(f"    <rule>{r}</rule>")
        lines.append("  </rules>")

    if data.warnings:
        lines.append("  <warnings>")
        for w in data.warnings:
            lines.append(f"    <warning>{w}</warning>")
        lines.append("  </warnings>")

    lines.append("</context_pack>")
    return "\n".join(lines)


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
        allowed_changes = data.current_goal.get("allowed_changes", [])
        if allowed_changes:
            lines.append("ALLOWED CHANGES:")
            for item in allowed_changes:
                lines.append(f"  - {item}")
        contract_file = data.current_goal.get("contract_file")
        if contract_file:
            lines.append(f"CONTRACT FILE: {contract_file}")
        decision_file = data.current_goal.get("decision_file")
        if decision_file:
            lines.append(f"DECISION FILE: {decision_file}")
        uncertainty = data.current_goal.get("uncertainty")
        if uncertainty:
            lines.append(f"UNCERTAINTY: {uncertainty}")
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

    if data.warnings:
        lines.append("")
        lines.append("WARNINGS")
        for w in data.warnings:
            lines.append(f"! {w}")

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
        allowed_changes = data.current_goal.get("allowed_changes", [])
        if allowed_changes:
            lines.append("**Allowed Changes:**")
            for item in allowed_changes:
                lines.append(f"- {item}")
        test_files = data.current_goal.get("test_files", [])
        if test_files:
            lines.append("**Contract Tests (MUST PASS):**")
            for item in test_files:
                lines.append(f"- {item}")
        contract_file = data.current_goal.get("contract_file")
        if contract_file:
            lines.append(f"**Contract File:** `{contract_file}`")
        decision_file = data.current_goal.get("decision_file")
        if decision_file:
            lines.append(f"**Decision File:** `{decision_file}`")
        uncertainty = data.current_goal.get("uncertainty")
        if uncertainty:
            lines.append(f"**Uncertainty:** `{uncertainty}`")
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

    if data.warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in data.warnings:
            lines.append(f"⚠️ {w}")

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
        file_contents={},  # drop file_contents (largest payload)
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
        raise DevfError("could not find .ai directory (run hast init first)")
    return root


def _has_glob(value: str) -> bool:
    return any(ch in value for ch in ("*", "?", "["))


def _normalize_relpath(root: Path, path: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    return rel.as_posix()


def _expand_paths(root: Path, items: Iterable[str]) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    missing: list[str] = []
    for item in items:
        if not item:
            continue
        item = item.strip()
        if not item:
            continue
        if _has_glob(item):
            matches = []
            for p in root.glob(item):
                if p.is_dir():
                    for sub in p.rglob("*.py"):
                        rel = _normalize_relpath(root, sub)
                        if rel:
                            matches.append(rel)
                else:
                    rel = _normalize_relpath(root, p)
                    if rel:
                        matches.append(rel)
            if matches:
                files.update(matches)
            else:
                missing.append(item)
            continue
        p = Path(item)
        if not p.is_absolute():
            p = root / p
        if p.is_dir():
            for sub in p.rglob("*.py"):
                rel = _normalize_relpath(root, sub)
                if rel:
                    files.add(rel)
            continue
        if p.exists():
            rel = _normalize_relpath(root, p)
            if rel:
                files.add(rel)
        else:
            missing.append(item)
    return files, missing


def _get_priority(path: str) -> int:
    if path.startswith(("src/", "app/", "core/", "fastapi/", "hyperqueue/")):
        return 10
    if path.startswith(("tests/", "docs/", "examples/", "docs_src/")):
        return 1
    return 5


def _select_context_files(files: set[str], limit: int) -> list[str]:
    if not files:
        return []
    # Filter out low-priority files (tests/docs) for fallbacks to avoid noise
    high_priority = [f for f in files if _get_priority(f) > 1]
    if not high_priority:
        # If everything is low priority, just take the top ones anyway
        high_priority = list(files)

    sorted_files = sorted(high_priority, key=_get_priority, reverse=True)
    return sorted_files[:limit]


def _extract_forward_deps(path: Path, module_to_file: dict[str, str]) -> set[str]:
    if not path.exists() or not path.name.endswith(".py"):
        return set()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    resolved: set[str] = set()
    for module in imports:
        for known_mod, file_path in module_to_file.items():
            if (
                module == known_mod
                or module.startswith(known_mod + ".")
                or known_mod.startswith(module + ".")
            ):
                resolved.add(file_path)
    return resolved


def _xml_escape(text: str) -> str:
    """Minimal XML escape for source code content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read_file_contents(
    root: Path, files: set[str],
) -> dict[str, str]:
    """Read file contents for Tier 1 files, with per-file size limits."""
    result: dict[str, str] = {}
    for rel in sorted(files):
        path = root / rel
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        # Skip binary files
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.splitlines(keepends=True)
        if len(raw) > FILE_CONTENT_MAX_BYTES or len(lines) > FILE_CONTENT_MAX_LINES:
            limit = min(FILE_CONTENT_MAX_LINES, len(lines))
            # Also respect byte budget
            kept: list[str] = []
            byte_count = 0
            for line in lines[:limit]:
                byte_count += len(line.encode("utf-8"))
                if byte_count > FILE_CONTENT_MAX_BYTES:
                    break
                kept.append(line)
            text = "".join(kept)
            if not text.endswith("\n"):
                text += "\n"
            text += f"... (truncated, total {len(lines)} lines)\n"
        result[rel] = text
    return result
