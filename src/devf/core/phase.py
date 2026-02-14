"""Phase transition logic and template loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

try:
    import jinja2
except ImportError:
    jinja2 = None  # type: ignore[assignment]


PHASE_ORDER = ["plan", "implement", "gate", "adversarial", "merge"]

PHASE_TEMPLATE_MAP = {
    "plan": "plan.md.j2",
    "implement": "implement.md.j2",
    "adversarial": "adversarial.md.j2",
    "review": "review.md.j2",
}

# Default agent per phase. Goal.agent overrides this.
# Rationale (Codex 5.3 proposal):
#   - plan: opus (명세 설계, 메타 인지 질문)
#   - implement: codex (Terminal-Bench 75%+, 4x token efficiency)
#   - adversarial: codex (sandbox isolation, --full-auto, best-of-N)
PHASE_AGENT_MAP: dict[str, str] = {
    "plan": "opus",
    "implement": "codex",
    "adversarial": "codex",
}


def next_phase(current: str) -> str | None:
    """Find current in PHASE_ORDER, return next element, or None if last/not found."""
    try:
        idx = PHASE_ORDER.index(current)
    except ValueError:
        return None
    if idx + 1 < len(PHASE_ORDER):
        return PHASE_ORDER[idx + 1]
    return None


def regress_phase(current: str) -> str:
    """Always returns 'implement' (gate/adversarial failures regress to implement)."""
    return "implement"


def advance_phase(current: str) -> str | None:
    """Alias for next_phase."""
    return next_phase(current)


def load_phase_template(root: Path, phase: str) -> Any:
    """Load a Jinja2 template for the given phase from .ai/templates/."""
    if jinja2 is None:
        return None
    filename = PHASE_TEMPLATE_MAP.get(phase)
    if filename is None:
        return None
    template_path = root / ".ai" / "templates" / filename
    if not template_path.exists():
        return None
    template_dir = root / ".ai" / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template(filename)


def parse_plan_output(output: str) -> dict[str, Any] | None:
    """Extract goal_update dict from yaml/yml code blocks in output."""
    pattern = re.compile(r"```(?:yaml|yml)\s*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(output):
        yaml_content = match.group(1)
        try:
            parsed = yaml.safe_load(yaml_content)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and "goal_update" in parsed:
            goal_update = parsed["goal_update"]
            if isinstance(goal_update, dict):
                return goal_update
    return None
