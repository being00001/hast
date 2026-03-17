"""Goal dependency scheduler for execution batches."""

from __future__ import annotations

from collections import deque

from hast.core.errors import HastError
from hast.core.goals import Goal, find_goal, iter_goals


def build_execution_batches(all_goals: list[Goal], selected: list[Goal]) -> list[list[Goal]]:
    """Build topological batches for selected goals based on ``depends_on``."""
    if not selected:
        return []

    selected_map = {goal.id: goal for goal in selected}
    all_ids = {node.goal.id for node in iter_goals(all_goals)}

    indegree: dict[str, int] = {goal.id: 0 for goal in selected}
    edges: dict[str, set[str]] = {goal.id: set() for goal in selected}

    for goal in selected:
        for dep in goal.depends_on:
            if dep not in all_ids:
                raise HastError(f"goal dependency not found: {goal.id} -> {dep}")

            if dep in selected_map:
                if goal.id not in edges[dep]:
                    edges[dep].add(goal.id)
                    indegree[goal.id] += 1
                continue

            dep_goal = find_goal(all_goals, dep)
            if dep_goal is None or dep_goal.status != "done":
                raise HastError(
                    f"goal dependency not satisfied: {goal.id} requires {dep} (status must be done)"
                )

    ready = deque(sorted([gid for gid, deg in indegree.items() if deg == 0]))
    visited = 0
    batches: list[list[Goal]] = []

    while ready:
        level_ids = list(ready)
        ready.clear()
        batch: list[Goal] = []
        for gid in level_ids:
            visited += 1
            batch.append(selected_map[gid])
            for nxt in sorted(edges[gid]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        batches.append(batch)

    if visited != len(selected):
        raise HastError("goal dependency cycle detected in selected goals")

    return batches
