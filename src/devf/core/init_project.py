"""Project initialization."""

from __future__ import annotations

from pathlib import Path


CONFIG_TEMPLATE = """test_command: "pytest"
ai_tool: "claude -p {prompt}"
"""

GOALS_TEMPLATE = """goals: []
"""

RULES_TEMPLATE = """# .ai/rules.md

## Verification
- Run tests before committing
- Commit only after tests pass

## Commit Format
{type}({goal_id}): {description}
types: feat, fix, refactor, test, docs, chore
"""


def init_project(root: Path) -> list[Path]:
    ai_dir = root / ".ai"
    created: list[Path] = []

    ai_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir = ai_dir / "sessions"
    if not sessions_dir.exists():
        sessions_dir.mkdir(parents=True, exist_ok=True)
        created.append(sessions_dir)

    handoffs_dir = ai_dir / "handoffs"
    if not handoffs_dir.exists():
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        created.append(handoffs_dir)

    config_path = ai_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        created.append(config_path)

    goals_path = ai_dir / "goals.yaml"
    if not goals_path.exists():
        goals_path.write_text(GOALS_TEMPLATE, encoding="utf-8")
        created.append(goals_path)

    rules_path = ai_dir / "rules.md"
    if not rules_path.exists():
        rules_path.write_text(RULES_TEMPLATE, encoding="utf-8")
        created.append(rules_path)

    return created
