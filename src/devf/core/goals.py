"""Goal parsing and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

from devf.core.errors import DevfError
from devf.utils.fs import normalize_path

ALLOWED_STATUSES = {
    "pending",
    "active",
    "done",
    "blocked",
    "dropped",
    "obsolete",
    "superseded",
    "merged_into",
}
ALLOWED_PHASES = {"plan", "implement", "gate", "adversarial", "review", None}
ALLOWED_IMPACTS = {"being", "code", "both", None}
ALLOWED_AGENTS = {"opus", "sonnet", "codex", None}
ALLOWED_STATES = {"planned", "red_verified", "green_verified", "review_ready", "merged", None}
ALLOWED_OWNER_AGENTS = {"architect", "tester", "worker", "gatekeeper", None}
ALLOWED_LANGUAGES = {"python", "rust"}
ALLOWED_UNCERTAINTY = {"low", "medium", "high", None}


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
    test_files: list[str] = field(default_factory=list)
    agent: str | None = None
    phase: str | None = None
    impact: str | None = None
    edge_cases: list[str] = field(default_factory=list)
    capability_refs: list[str] = field(default_factory=list)
    phases: list[str] | None = None
    spec_file: str | None = None
    contract_file: str | None = None
    decision_file: str | None = None
    uncertainty: str | None = None
    state: str | None = None
    depends_on: list[str] = field(default_factory=list)
    owner_agent: str | None = None
    languages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoalNode:
    goal: Goal
    depth: int
    parent: Goal | None


def _parse_goal(data: dict[str, Any], root: Path) -> Goal:
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
    children = [_parse_goal(child, root) for child in children_raw]

    expect_failure = bool(data.get("expect_failure", False))

    allowed_changes_raw = data.get("allowed_changes", [])
    if not isinstance(allowed_changes_raw, list):
        raise DevfError(f"goal.allowed_changes must be a list for {goal_id}")
    allowed_changes = []
    for item in allowed_changes_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.allowed_changes entries must be strings for {goal_id}")
        allowed_changes.append(normalize_path(item, root))

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

    test_files_raw = data.get("test_files", [])
    if not isinstance(test_files_raw, list):
        raise DevfError(f"goal.test_files must be a list for {goal_id}")
    test_files: list[str] = []
    for item in test_files_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.test_files entries must be strings for {goal_id}")
        test_files.append(normalize_path(item, root))

    agent = data.get("agent")
    if agent is not None and agent not in ALLOWED_AGENTS:
        raise DevfError(f"goal.agent invalid for {goal_id}: {agent}")

    phase = data.get("phase")
    if phase is not None and phase not in ALLOWED_PHASES:
        raise DevfError(f"goal.phase invalid for {goal_id}: {phase}")

    impact = data.get("impact")
    if impact is not None and impact not in ALLOWED_IMPACTS:
        raise DevfError(f"goal.impact invalid for {goal_id}: {impact}")

    edge_cases_raw = data.get("edge_cases", [])
    if not isinstance(edge_cases_raw, list):
        raise DevfError(f"goal.edge_cases must be a list for {goal_id}")
    edge_cases: list[str] = []
    for item in edge_cases_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.edge_cases entries must be strings for {goal_id}")
        edge_cases.append(item)

    capability_refs_raw = data.get("capability_refs", [])
    if not isinstance(capability_refs_raw, list):
        raise DevfError(f"goal.capability_refs must be a list for {goal_id}")
    capability_refs: list[str] = []
    for item in capability_refs_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.capability_refs entries must be strings for {goal_id}")
        capability_refs.append(item)

    phases_raw = data.get("phases")
    phases: list[str] | None = None
    if phases_raw is not None:
        if not isinstance(phases_raw, list):
            raise DevfError(f"goal.phases must be a list for {goal_id}")
        for item in phases_raw:
            if not isinstance(item, str):
                raise DevfError(f"goal.phases entries must be strings for {goal_id}")
            if item not in ("plan", "implement", "gate", "adversarial", "review", "merge"):
                raise DevfError(f"goal.phases contains invalid phase '{item}' for {goal_id}")
        phases = phases_raw

    spec_file_raw = data.get("spec_file")
    spec_file: str | None = None
    if spec_file_raw is not None:
        if not isinstance(spec_file_raw, str):
            raise DevfError(f"goal.spec_file must be a string for {goal_id}")
        spec_file = normalize_path(spec_file_raw, root)

    contract_file_raw = data.get("contract_file")
    contract_file: str | None = None
    if contract_file_raw is not None:
        if not isinstance(contract_file_raw, str):
            raise DevfError(f"goal.contract_file must be a string for {goal_id}")
        contract_file = normalize_path(contract_file_raw, root)

    decision_file_raw = data.get("decision_file")
    decision_file: str | None = None
    if decision_file_raw is not None:
        if not isinstance(decision_file_raw, str):
            raise DevfError(f"goal.decision_file must be a string for {goal_id}")
        decision_file = normalize_path(decision_file_raw, root)

    uncertainty = data.get("uncertainty")
    if uncertainty is not None:
        if not isinstance(uncertainty, str):
            raise DevfError(f"goal.uncertainty must be a string for {goal_id}")
        uncertainty = uncertainty.strip().lower()
    if uncertainty not in ALLOWED_UNCERTAINTY:
        raise DevfError(f"goal.uncertainty invalid for {goal_id}: {uncertainty}")

    state = data.get("state")
    if state is not None and state not in ALLOWED_STATES:
        raise DevfError(f"goal.state invalid for {goal_id}: {state}")

    depends_on_raw = data.get("depends_on", [])
    if not isinstance(depends_on_raw, list):
        raise DevfError(f"goal.depends_on must be a list for {goal_id}")
    depends_on: list[str] = []
    for item in depends_on_raw:
        if not isinstance(item, str) or not item.strip():
            raise DevfError(f"goal.depends_on entries must be non-empty strings for {goal_id}")
        depends_on.append(item.strip())

    owner_agent = data.get("owner_agent")
    if owner_agent is not None and owner_agent not in ALLOWED_OWNER_AGENTS:
        raise DevfError(f"goal.owner_agent invalid for {goal_id}: {owner_agent}")

    languages_raw = data.get("languages", [])
    if not isinstance(languages_raw, list):
        raise DevfError(f"goal.languages must be a list for {goal_id}")
    languages: list[str] = []
    for item in languages_raw:
        if not isinstance(item, str):
            raise DevfError(f"goal.languages entries must be strings for {goal_id}")
        language = item.strip().lower()
        if language not in ALLOWED_LANGUAGES:
            raise DevfError(f"goal.languages contains invalid language '{item}' for {goal_id}")
        if language not in languages:
            languages.append(language)

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
        test_files=test_files,
        agent=agent,
        phase=phase,
        impact=impact,
        edge_cases=edge_cases,
        capability_refs=capability_refs,
        phases=phases,
        spec_file=spec_file,
        contract_file=contract_file,
        decision_file=decision_file,
        uncertainty=uncertainty,
        state=state,
        depends_on=depends_on,
        owner_agent=owner_agent,
        languages=languages,
    )


def load_goals(path: Path) -> list[Goal]:
    root = path.parent.parent # .ai/goals.yaml -> project root
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError("goals.yaml must be a mapping with a goals list")
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raise DevfError("goals must be a list")

    goals = [_parse_goal(item, root) for item in raw_goals]
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
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def update_goal_fields(path: Path, goal_id: str, fields: dict[str, Any]) -> None:
    """Update arbitrary fields on a goal in goals.yaml."""
    if not path.exists():
        raise DevfError(f"goals.yaml not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError("goals.yaml must be a mapping with a goals list")
    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raise DevfError("goals must be a list")

    updated = _update_goal_fields(raw_goals, goal_id, fields)
    if not updated:
        raise DevfError(f"goal not found: {goal_id}")
    data["goals"] = raw_goals
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _update_goal_fields(
    raw_goals: list[dict[str, Any]], goal_id: str, fields: dict[str, Any],
) -> bool:
    for goal in raw_goals:
        if goal.get("id") == goal_id:
            goal.update(fields)
            return True
        children = goal.get("children")
        if isinstance(children, list):
            if _update_goal_fields(children, goal_id, fields):
                return True
    return False
