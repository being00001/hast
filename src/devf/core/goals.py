"""Goal parsing and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

from devf.core.errors import DevfError

ALLOWED_STATUSES = {"pending", "active", "done", "blocked", "dropped"}


@dataclass
class Goal:
    id: str
    title: str
    status: str
    children: list["Goal"] = field(default_factory=list)
    expect_failure: bool = False
    allowed_changes: list[str] = field(default_factory=list)
    prompt_mode: str | None = None
    mode: str | None = None
    tool: str | None = None
    notes: str | None = None
    acceptance: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoalNode:
    goal: Goal
    depth: int
    parent: Goal | None


def _parse_goal(data: dict[str, Any]) -> Goal:
    goal_id = data.get("id")
    title = data.get("title")
    status = data.get("status")
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise DevfError("goal.id is required and must be a string")
    if not isinstance(title, str) or not title.strip():
        raise DevfError(f"goal.title is required for {goal_id}")
    if status not in ALLOWED_STATUSES:
        raise DevfError(f"goal.status invalid for {goal_id}: {status}")

    children_raw = data.get("children", [])
    if not isinstance(children_raw, list):
        raise DevfError(f"goal.children must be a list for {goal_id}")
    children = [_parse_goal(child) for child in children_raw]

    expect_failure = bool(data.get("expect_failure", False))

    allowed_changes_raw = data.get("allowed_changes", [])
    if not isinstance(allowed_changes_raw, list):
        raise DevfError(f"goal.allowed_changes must be a list for {goal_id}")
    allowed_changes = []
    for item in allowed_changes_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.allowed_changes entries must be strings for {goal_id}")
        allowed_changes.append(item)

    prompt_mode = data.get("prompt_mode")
    if prompt_mode is not None and prompt_mode != "adversarial":
        raise DevfError(f"goal.prompt_mode invalid for {goal_id}: {prompt_mode}")

    mode = data.get("mode")
    if mode is not None and mode != "interactive":
        raise DevfError(f"goal.mode invalid for {goal_id}: {mode}")

    tool = data.get("tool")
    if tool is not None and not isinstance(tool, str):
        raise DevfError(f"goal.tool must be a string for {goal_id}")

    notes = data.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise DevfError(f"goal.notes must be a string for {goal_id}")

    acceptance_raw = data.get("acceptance", [])
    if not isinstance(acceptance_raw, list):
        raise DevfError(f"goal.acceptance must be a list for {goal_id}")
    acceptance: list[str] = []
    for item in acceptance_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.acceptance entries must be strings for {goal_id}")
        acceptance.append(item)

    return Goal(
        id=goal_id,
        title=title,
        status=status,
        children=children,
        expect_failure=expect_failure,
        allowed_changes=allowed_changes,
        prompt_mode=prompt_mode,
        mode=mode,
        tool=tool,
        notes=notes,
        acceptance=acceptance,
    )


def load_goals(path: Path) -> list[Goal]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError("goals.yaml must be a mapping with a goals list")
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raise DevfError("goals must be a list")

    goals = [_parse_goal(item) for item in raw_goals]
    _ensure_unique_ids(goals)
    return goals


def _ensure_unique_ids(goals: Iterable[Goal]) -> None:
    seen: set[str] = set()
    for node in iter_goals(goals):
        if node.goal.id in seen:
            raise DevfError(f"duplicate goal id: {node.goal.id}")
        seen.add(node.goal.id)


def iter_goals(goals: Iterable[Goal], depth: int = 0, parent: Goal | None = None) -> Iterator[GoalNode]:
    for goal in goals:
        node = GoalNode(goal=goal, depth=depth, parent=parent)
        yield node
        if goal.children:
            yield from iter_goals(goal.children, depth + 1, goal)


def find_goal(goals: Iterable[Goal], goal_id: str) -> Goal | None:
    for node in iter_goals(goals):
        if node.goal.id == goal_id:
            return node.goal
    return None


def find_goal_node(goals: Iterable[Goal], goal_id: str) -> GoalNode | None:
    for node in iter_goals(goals):
        if node.goal.id == goal_id:
            return node
    return None


def select_active_goal(goals: list[Goal], preferred_id: str | None) -> Goal | None:
    if preferred_id:
        node = find_goal_node(goals, preferred_id)
        if node and node.goal.status == "active" and node.goal.mode != "interactive":
            return node.goal

    candidates: list[GoalNode] = [
        node
        for node in iter_goals(goals)
        if node.goal.status == "active" and node.goal.mode != "interactive"
    ]
    if not candidates:
        return None

    max_depth = max(node.depth for node in candidates)
    for node in candidates:
        if node.depth == max_depth:
            return node.goal
    return None


def collect_goals(goals: list[Goal], root_id: str | None, recursive: bool) -> list[Goal]:
    if not recursive:
        selected = select_active_goal(goals, root_id)
        return [selected] if selected else []

    if root_id is None:
        raise DevfError("goal_id is required with --recursive")

    root_node = find_goal_node(goals, root_id)
    if root_node is None:
        raise DevfError(f"goal not found: {root_id}")

    collected: list[Goal] = []

    def walk(goal: Goal) -> None:
        if goal.status == "active" and goal.mode != "interactive":
            collected.append(goal)
        for child in goal.children:
            walk(child)

    walk(root_node.goal)
    return collected


def update_goal_status(path: Path, goal_id: str, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise DevfError(f"invalid status: {status}")
    if not path.exists():
        raise DevfError(f"goals.yaml not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError("goals.yaml must be a mapping with a goals list")
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raise DevfError("goals must be a list")

    updated = _update_goal_status(raw_goals, goal_id, status)
    if not updated:
        raise DevfError(f"goal not found: {goal_id}")
    data["goals"] = raw_goals
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _update_goal_status(raw_goals: list[dict[str, Any]], goal_id: str, status: str) -> bool:
    for goal in raw_goals:
        if goal.get("id") == goal_id:
            goal["status"] = status
            return True
        children = goal.get("children")
        if isinstance(children, list):
            if _update_goal_status(children, goal_id, status):
                return True
    return False
