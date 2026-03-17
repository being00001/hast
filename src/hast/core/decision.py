"""Decision ticket + validation matrix helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import yaml

from hast.core.errors import HastError


DEFAULT_MATRIX: list[dict[str, Any]] = [
    {
        "criterion": "contract_fit",
        "weight": 30,
        "min_score": 3,
        "description": "Does this alternative satisfy the acceptance contract without ambiguity?",
    },
    {
        "criterion": "regression_risk",
        "weight": 20,
        "min_score": 3,
        "description": "Does it reduce regression risk for adjacent modules and behaviors?",
    },
    {
        "criterion": "operability",
        "weight": 20,
        "min_score": 3,
        "description": "Is it easy to operate, observe, and rollback in production?",
    },
    {
        "criterion": "delivery_speed",
        "weight": 15,
        "min_score": 2,
        "description": "Can this be implemented and verified quickly with low rework?",
    },
    {
        "criterion": "security_posture",
        "weight": 15,
        "min_score": 3,
        "description": "Does it maintain secure defaults and avoid new attack surface?",
    },
]


@dataclass(frozen=True)
class AlternativeScore:
    alternative_id: str
    total_score: float
    eligible: bool
    failed_criteria: list[str]


@dataclass(frozen=True)
class DecisionEvaluation:
    decision_id: str
    goal_id: str
    winner_id: str
    winner_eligible: bool
    ranking: list[AlternativeScore]


def normalize_decision_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    if not cleaned:
        raise HastError("decision_id must not be empty")
    return cleaned


def default_decision_id(goal_id: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    safe_goal = normalize_decision_id(goal_id)
    return f"D_{safe_goal}_{stamp}"


def create_decision_ticket(
    goal_id: str,
    question: str,
    alternatives: list[str],
    decision_id: str,
    owner: str = "architect",
) -> dict[str, Any]:
    if not question.strip():
        raise HastError("question must not be empty")
    if len(alternatives) < 2:
        raise HastError("at least 2 alternatives are required")

    alt_rows = [
        {
            "id": alt,
            "hypothesis": "",
            "approach": "",
            "tradeoffs": [],
        }
        for alt in alternatives
    ]
    score_map = {alt: {} for alt in alternatives}

    return {
        "version": 1,
        "decision_id": normalize_decision_id(decision_id),
        "goal_id": goal_id.strip(),
        "question": question.strip(),
        "status": "proposed",
        "owner": owner.strip() or "architect",
        "created_at": datetime.now().astimezone().isoformat(),
        "updated_at": datetime.now().astimezone().isoformat(),
        "alternatives": alt_rows,
        "validation_matrix": [dict(item) for item in DEFAULT_MATRIX],
        "scores": score_map,
        "selected_alternative": None,
        "decision_reason": "",
        "next_actions": [],
        "evidence_refs": [],
    }


def load_decision_ticket(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HastError(f"decision file not found: {path.as_posix()}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise HastError("decision file must be a mapping")
    if "decision" in raw:
        wrapped = raw.get("decision")
        if not isinstance(wrapped, dict):
            raise HastError("decision.decision must be a mapping")
        raw = wrapped
    validate_decision_ticket(raw)
    return raw


def validate_decision_ticket(ticket: dict[str, Any]) -> None:
    for key in ("decision_id", "goal_id", "question", "status"):
        if not isinstance(ticket.get(key), str) or not str(ticket.get(key)).strip():
            raise HastError(f"decision.{key} must be a non-empty string")

    alternatives = ticket.get("alternatives")
    if not isinstance(alternatives, list) or len(alternatives) < 2:
        raise HastError("decision.alternatives must contain at least 2 items")
    alt_ids: list[str] = []
    for item in alternatives:
        if not isinstance(item, dict):
            raise HastError("decision.alternatives entries must be mappings")
        alt_id = item.get("id")
        if not isinstance(alt_id, str) or not alt_id.strip():
            raise HastError("decision.alternatives[].id must be a non-empty string")
        if alt_id in alt_ids:
            raise HastError(f"duplicate alternative id: {alt_id}")
        alt_ids.append(alt_id)

    matrix = ticket.get("validation_matrix")
    if not isinstance(matrix, list) or not matrix:
        raise HastError("decision.validation_matrix must be a non-empty list")
    seen_criteria: set[str] = set()
    for row in matrix:
        if not isinstance(row, dict):
            raise HastError("decision.validation_matrix entries must be mappings")
        criterion = row.get("criterion")
        weight = row.get("weight")
        min_score = row.get("min_score", 0)
        if not isinstance(criterion, str) or not criterion.strip():
            raise HastError("decision.validation_matrix[].criterion must be a non-empty string")
        if criterion in seen_criteria:
            raise HastError(f"duplicate criterion: {criterion}")
        seen_criteria.add(criterion)
        if not isinstance(weight, int) or weight <= 0:
            raise HastError(f"decision.validation_matrix[{criterion}].weight must be positive int")
        if not isinstance(min_score, int) or min_score < 0 or min_score > 5:
            raise HastError(f"decision.validation_matrix[{criterion}].min_score must be int in 0..5")

    scores = ticket.get("scores")
    if scores is None:
        return
    if not isinstance(scores, dict):
        raise HastError("decision.scores must be a mapping")
    for alt_id, alt_scores in scores.items():
        if alt_id not in alt_ids:
            raise HastError(f"decision.scores contains unknown alternative: {alt_id}")
        if not isinstance(alt_scores, dict):
            raise HastError(f"decision.scores[{alt_id}] must be a mapping")
        for criterion, value in alt_scores.items():
            if criterion not in seen_criteria:
                raise HastError(f"decision.scores[{alt_id}] contains unknown criterion: {criterion}")
            if not isinstance(value, (int, float)):
                raise HastError(f"decision.scores[{alt_id}][{criterion}] must be numeric")
            if value < 0 or value > 5:
                raise HastError(f"decision.scores[{alt_id}][{criterion}] must be in 0..5")


def evaluate_decision_ticket(ticket: dict[str, Any]) -> DecisionEvaluation:
    validate_decision_ticket(ticket)
    decision_id = str(ticket["decision_id"])
    goal_id = str(ticket["goal_id"])
    matrix = list(ticket["validation_matrix"])
    scores = ticket.get("scores") or {}
    alternatives = [str(item["id"]) for item in ticket["alternatives"]]

    rows: list[AlternativeScore] = []
    for alt_id in alternatives:
        alt_scores = scores.get(alt_id, {})
        if not isinstance(alt_scores, dict):
            alt_scores = {}
        failed_criteria: list[str] = []
        weighted_total = 0.0
        for criterion_row in matrix:
            criterion = str(criterion_row["criterion"])
            weight = int(criterion_row["weight"])
            min_score = int(criterion_row.get("min_score", 0))
            score = float(alt_scores.get(criterion, 0.0))
            if score < min_score:
                failed_criteria.append(criterion)
            weighted_total += weight * (score / 5.0)
        rows.append(
            AlternativeScore(
                alternative_id=alt_id,
                total_score=round(weighted_total, 2),
                eligible=not failed_criteria,
                failed_criteria=failed_criteria,
            )
        )

    ranking = sorted(
        rows,
        key=lambda row: (
            1 if row.eligible else 0,
            row.total_score,
            row.alternative_id,
        ),
        reverse=True,
    )
    if not ranking:
        raise HastError("no alternatives to evaluate")
    winner = ranking[0]
    return DecisionEvaluation(
        decision_id=decision_id,
        goal_id=goal_id,
        winner_id=winner.alternative_id,
        winner_eligible=winner.eligible,
        ranking=ranking,
    )


def apply_decision_result(
    ticket: dict[str, Any],
    evaluation: DecisionEvaluation,
    actor: str,
) -> dict[str, Any]:
    updated = dict(ticket)
    updated["selected_alternative"] = evaluation.winner_id
    updated["status"] = "accepted" if evaluation.winner_eligible else "needs_review"
    updated["decision_reason"] = (
        f"selected {evaluation.winner_id} with weighted score "
        f"{evaluation.ranking[0].total_score} (eligible={evaluation.winner_eligible})"
    )
    updated["updated_at"] = datetime.now().astimezone().isoformat()
    history = list(updated.get("decision_history") or [])
    history.append(
        {
            "timestamp": datetime.now().astimezone().isoformat(),
            "actor": actor,
            "winner_id": evaluation.winner_id,
            "winner_eligible": evaluation.winner_eligible,
            "winner_score": evaluation.ranking[0].total_score,
        }
    )
    updated["decision_history"] = history
    return updated


def save_decision_ticket(path: Path, ticket: dict[str, Any]) -> None:
    wrapped = {"decision": ticket}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(wrapped, sort_keys=False, allow_unicode=True), encoding="utf-8")


def append_decision_evidence(
    root: Path,
    decision_file: Path,
    ticket: dict[str, Any],
    evaluation: DecisionEvaluation,
    run_id: str | None,
    actor: str,
) -> Path:
    evidence_path = root / ".ai" / "decisions" / "evidence.jsonl"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    classification = "decision-accepted" if evaluation.winner_eligible else "decision-blocked"
    row = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "event_type": "decision_evaluation",
        "decision_id": evaluation.decision_id,
        "goal_id": evaluation.goal_id,
        "decision_file": _relpath_or_abs(root, decision_file),
        "question": ticket.get("question"),
        "winner_id": evaluation.winner_id,
        "winner_eligible": evaluation.winner_eligible,
        "winner_score": evaluation.ranking[0].total_score if evaluation.ranking else 0.0,
        "ranking": [
            {
                "alternative_id": item.alternative_id,
                "total_score": item.total_score,
                "eligible": item.eligible,
                "failed_criteria": item.failed_criteria,
            }
            for item in evaluation.ranking
        ],
        "status": ticket.get("status"),
        "classification": classification,
        "action_taken": "advance" if evaluation.winner_eligible else "escalate",
        "actor": actor,
        "run_id": run_id,
        "evidence_refs": list(ticket.get("evidence_refs") or []),
        "schema_version": "decision_evidence.v1",
    }
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
    with evidence_path.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")
    return evidence_path


def _relpath_or_abs(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
