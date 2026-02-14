"""Goal execution runner interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devf.core.config import Config
    from devf.core.goals import Goal


@dataclass(frozen=True)
class RunnerResult:
    """Result of an AI execution attempt."""
    success: bool
    output: str  # Combined stdout/stderr or API response
    error_message: str | None = None
    model_used: str | None = None
    latency_ms: int | None = None
    cost_tokens_prompt: int | None = None
    cost_tokens_completion: int | None = None
    cost_estimate_usd: float | None = None


class GoalRunner(ABC):
    """Abstract base class for executing an AI session for a goal."""

    @abstractmethod
    def run(
        self,
        root: Path,
        config: Config,
        goal: Goal,
        prompt: str,
        tool_name: str | None = None,
    ) -> RunnerResult:
        """Execute the AI session."""
        pass
