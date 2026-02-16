"""Structured result types for hast auto runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GoalResult:
    """Result of a single goal execution."""

    id: str
    success: bool
    classification: str | None = None
    phase: str | None = None
    action_taken: str | None = None
    risk_score: int | None = None


@dataclass(frozen=True)
class AutoResult:
    """Structured result from run_auto()."""

    exit_code: int
    run_id: str
    goals: list[GoalResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when all goals passed."""
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable dict matching auto --json output schema."""
        return {
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "goals_processed": [
                {
                    "id": g.id,
                    "success": g.success,
                    "classification": g.classification,
                    "phase": g.phase,
                    "action_taken": g.action_taken,
                    "risk_score": g.risk_score,
                }
                for g in self.goals
            ],
            "changed_files": self.changed_files,
            "evidence_summary": self.evidence_summary,
            "errors": self.errors,
        }
