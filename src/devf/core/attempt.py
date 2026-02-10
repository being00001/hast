"""Attempt logging for retry context injection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil

import yaml


@dataclass(frozen=True)
class AttemptLog:
    attempt: int
    classification: str
    reason: str | None
    diff_stat: str
    test_output: str


def save_attempt(
    root: Path,
    goal_id: str,
    attempt: int,
    classification: str,
    reason: str | None,
    diff_stat: str,
    test_output: str,
) -> None:
    """Save attempt details to a file."""
    attempt_dir = _get_attempt_dir(root, goal_id)
    attempt_dir.mkdir(parents=True, exist_ok=True)

    log = AttemptLog(
        attempt=attempt,
        classification=classification,
        reason=reason,
        diff_stat=diff_stat,
        test_output=test_output,
    )

    file_path = attempt_dir / f"attempt_{attempt}.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(asdict(log), f, sort_keys=False)


def load_attempts(root: Path, goal_id: str) -> list[AttemptLog]:
    """Load all attempts for a goal, sorted by attempt number."""
    attempt_dir = _get_attempt_dir(root, goal_id)
    if not attempt_dir.exists():
        return []

    logs = []
    for file_path in attempt_dir.glob("attempt_*.yaml"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                logs.append(AttemptLog(**data))
        except Exception:  # pylint: disable=broad-except
            continue

    return sorted(logs, key=lambda x: x.attempt)


def clear_attempts(root: Path, goal_id: str) -> None:
    """Remove all attempt logs for a goal."""
    attempt_dir = _get_attempt_dir(root, goal_id)
    if attempt_dir.exists():
        shutil.rmtree(attempt_dir)


def _get_attempt_dir(root: Path, goal_id: str) -> Path:
    return root / ".ai" / "attempts" / goal_id
