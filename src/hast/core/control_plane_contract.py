"""Control-plane contract for evidence rows and policy actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hast.core.triage import TRIAGE_CLASSES


CONTROL_PLANE_CONTRACT_VERSION = "cp.v1"

ALLOWED_ACTIONS = {
    "advance",
    "retry",
    "escalate",
    "block",
    "rollback",
}

ALLOWED_EVENT_TYPES = {
    "auto_attempt",
    "goal_invalidation",
    "decision_spike",
}


@dataclass(frozen=True)
class ControlPlaneValidationResult:
    normalized_row: dict[str, Any]
    warnings: list[str]


def normalize_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized.setdefault("contract_version", CONTROL_PLANE_CONTRACT_VERSION)
    normalized.setdefault("event_type", _infer_event_type(normalized))
    return normalized


def validate_evidence_row(row: dict[str, Any]) -> ControlPlaneValidationResult:
    normalized = normalize_evidence_row(row)
    warnings: list[str] = []

    action = normalized.get("action_taken")
    success = normalized.get("success")
    should_retry = normalized.get("should_retry")
    failure_classification = normalized.get("failure_classification")
    event_type = normalized.get("event_type")

    if action is None:
        warnings.append("missing action_taken")
    elif action not in ALLOWED_ACTIONS:
        warnings.append(f"invalid action_taken: {action}")

    if event_type not in ALLOWED_EVENT_TYPES:
        warnings.append(f"invalid event_type: {event_type}")

    if isinstance(success, bool) and isinstance(action, str):
        if success and action != "advance":
            warnings.append("success rows must use action_taken=advance")
        if not success and action == "advance":
            warnings.append("failed rows must not use action_taken=advance")

    if isinstance(should_retry, bool) and isinstance(action, str):
        if should_retry and action != "retry":
            warnings.append("should_retry=true rows must use action_taken=retry")
        if not should_retry and action == "retry":
            warnings.append("should_retry=false rows must not use action_taken=retry")

    if failure_classification is not None:
        if not isinstance(failure_classification, str):
            warnings.append("failure_classification must be a string or null")
        elif failure_classification not in TRIAGE_CLASSES:
            warnings.append(f"unknown failure_classification: {failure_classification}")
    elif isinstance(action, str) and action in {"retry", "escalate", "block"}:
        warnings.append("non-advance action requires failure_classification")

    return ControlPlaneValidationResult(normalized_row=normalized, warnings=warnings)


def _infer_event_type(row: dict[str, Any]) -> str:
    classification = str(row.get("classification") or "")
    phase = str(row.get("phase") or "")
    if classification.startswith("decision-spike"):
        return "decision_spike"
    if phase == "replan" and classification == "goal-invalidated":
        return "goal_invalidation"
    return "auto_attempt"
