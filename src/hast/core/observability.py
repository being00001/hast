"""Observability baseline metrics for autonomous operation health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ObservabilityThresholds:
    min_goal_runs: int = 5
    first_pass_success_rate_min: float = 0.40
    block_rate_max: float = 0.35
    security_incident_rate_max: float = 0.20
    claim_collision_rate_max: float = 0.15
    mttr_minutes_max: float = 180.0


@dataclass(frozen=True)
class ObservabilityPolicy:
    version: str = "v1"
    thresholds: ObservabilityThresholds = ObservabilityThresholds()


@dataclass(frozen=True)
class ObservabilityBaselineReport:
    window_days: int
    goal_runs: int
    success_rate: float
    first_pass_success_rate: float
    retry_rate: float
    block_rate: float
    security_incident_rate: float
    mean_attempts_to_success: float
    mttr_minutes: float | None
    claim_attempts: int
    claim_collision_rate: float
    idempotent_reuse_rate: float
    stale_lease_recovery_count: int
    baseline_ready: bool
    failing_guards: list[str]
    policy_version: str


def load_observability_policy(root: Path) -> ObservabilityPolicy:
    path = root / ".ai" / "policies" / "observability_policy.yaml"
    if not path.exists():
        return ObservabilityPolicy()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ObservabilityPolicy()
    raw = data.get("thresholds")
    if not isinstance(raw, dict):
        raw = {}
    thresholds = ObservabilityThresholds(
        min_goal_runs=_as_int(raw.get("min_goal_runs"), 5, min_value=1),
        first_pass_success_rate_min=_as_fraction(raw.get("first_pass_success_rate_min"), 0.40),
        block_rate_max=_as_fraction(raw.get("block_rate_max"), 0.35),
        security_incident_rate_max=_as_fraction(raw.get("security_incident_rate_max"), 0.20),
        claim_collision_rate_max=_as_fraction(raw.get("claim_collision_rate_max"), 0.15),
        mttr_minutes_max=_as_positive_float(raw.get("mttr_minutes_max"), 180.0),
    )
    version = data.get("version")
    return ObservabilityPolicy(
        version=version.strip() if isinstance(version, str) and version.strip() else "v1",
        thresholds=thresholds,
    )


def build_observability_baseline(root: Path, window_days: int) -> ObservabilityBaselineReport:
    policy = load_observability_policy(root)
    rows = _load_recent_evidence_rows(root, window_days)
    grouped = _group_goal_runs(rows)

    goal_runs = len(grouped)
    success_count = 0
    first_pass_count = 0
    retry_count = 0
    block_count = 0
    security_count = 0
    attempts_to_success: list[int] = []
    recovery_minutes: list[float] = []

    for run_rows in grouped.values():
        run_rows_sorted = sorted(run_rows, key=lambda item: (item[0], _attempt_value(item[1])))
        payloads = [row for _, row in run_rows_sorted]
        attempts = [_attempt_value(row) for row in payloads]
        max_attempt = max(attempts) if attempts else 1
        had_retry = max_attempt > 1 or any(str(row.get("action_taken")) == "retry" for row in payloads)

        final_row = run_rows_sorted[-1][1]
        final_success = bool(final_row.get("success"))
        final_block = str(final_row.get("action_taken") or "") == "block"
        had_security = any(str(row.get("failure_classification") or "") == "security" for row in payloads)

        if final_success:
            success_count += 1
            attempts_to_success.append(max_attempt)
        if final_success and max_attempt <= 1 and not any(not bool(row.get("success")) for row in payloads):
            first_pass_count += 1
        if had_retry:
            retry_count += 1
        if final_block:
            block_count += 1
        if had_security:
            security_count += 1

        recovery = _recovery_minutes(payloads)
        if recovery is not None:
            recovery_minutes.append(recovery)

    success_rate = _rate(success_count, goal_runs)
    first_pass_success_rate = _rate(first_pass_count, goal_runs)
    retry_rate = _rate(retry_count, goal_runs)
    block_rate = _rate(block_count, goal_runs)
    security_incident_rate = _rate(security_count, goal_runs)
    mean_attempts_to_success = (
        sum(attempts_to_success) / len(attempts_to_success) if attempts_to_success else 0.0
    )
    mttr_minutes = (sum(recovery_minutes) / len(recovery_minutes)) if recovery_minutes else None

    queue_events = _load_recent_queue_events(root, window_days)
    claim_created = _count_event(queue_events, "claim_created")
    claim_rejected_total = _count_event(queue_events, "claim_rejected")
    claim_rejected_collision = _count_event(
        queue_events,
        "claim_rejected",
        reason_code="goal_already_claimed",
    )
    claim_attempts = claim_created + claim_rejected_total
    claim_collision_rate = _rate(claim_rejected_collision, claim_attempts)
    idempotent_reused = _count_event(queue_events, "idempotent_claim_reused")
    idempotent_reuse_rate = _rate(idempotent_reused, claim_created + idempotent_reused)
    stale_lease_recovery_count = _count_event(queue_events, "claim_expired")

    guards = policy.thresholds
    failing_guards: list[str] = []
    if goal_runs < guards.min_goal_runs:
        failing_guards.append(
            f"samples(min_goal_runs): {goal_runs} < {guards.min_goal_runs}"
        )
    if first_pass_success_rate < guards.first_pass_success_rate_min:
        failing_guards.append(
            f"first_pass_success_rate: {first_pass_success_rate:.3f} < {guards.first_pass_success_rate_min:.3f}"
        )
    if block_rate > guards.block_rate_max:
        failing_guards.append(f"block_rate: {block_rate:.3f} > {guards.block_rate_max:.3f}")
    if security_incident_rate > guards.security_incident_rate_max:
        failing_guards.append(
            f"security_incident_rate: {security_incident_rate:.3f} > {guards.security_incident_rate_max:.3f}"
        )
    if claim_attempts > 0 and claim_collision_rate > guards.claim_collision_rate_max:
        failing_guards.append(
            f"claim_collision_rate: {claim_collision_rate:.3f} > {guards.claim_collision_rate_max:.3f}"
        )
    if mttr_minutes is not None and mttr_minutes > guards.mttr_minutes_max:
        failing_guards.append(f"mttr_minutes: {mttr_minutes:.2f} > {guards.mttr_minutes_max:.2f}")

    return ObservabilityBaselineReport(
        window_days=window_days,
        goal_runs=goal_runs,
        success_rate=round(success_rate, 3),
        first_pass_success_rate=round(first_pass_success_rate, 3),
        retry_rate=round(retry_rate, 3),
        block_rate=round(block_rate, 3),
        security_incident_rate=round(security_incident_rate, 3),
        mean_attempts_to_success=round(mean_attempts_to_success, 3),
        mttr_minutes=round(mttr_minutes, 2) if mttr_minutes is not None else None,
        claim_attempts=claim_attempts,
        claim_collision_rate=round(claim_collision_rate, 3),
        idempotent_reuse_rate=round(idempotent_reuse_rate, 3),
        stale_lease_recovery_count=stale_lease_recovery_count,
        baseline_ready=not failing_guards,
        failing_guards=failing_guards,
        policy_version=policy.version,
    )


def write_observability_baseline(root: Path, report: ObservabilityBaselineReport) -> Path:
    path = root / ".ai" / "reports" / "observability_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.__dict__
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _group_goal_runs(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[datetime, dict[str, Any]]]]:
    grouped: dict[tuple[str, str], list[tuple[datetime, dict[str, Any]]]] = {}
    for row in rows:
        run_id = row.get("run_id")
        goal_id = row.get("goal_id")
        if not isinstance(run_id, str) or not run_id.strip():
            continue
        if not isinstance(goal_id, str) or not goal_id.strip():
            continue
        timestamp = _parse_iso(row.get("timestamp"))
        if timestamp is None:
            continue
        grouped.setdefault((run_id.strip(), goal_id.strip()), []).append((timestamp, row))
    return grouped


def _load_recent_evidence_rows(root: Path, window_days: int) -> list[dict[str, Any]]:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return []
    threshold = datetime.now().astimezone() - timedelta(days=window_days)
    rows: list[dict[str, Any]] = []
    for evidence_file in sorted(runs_dir.glob("*/evidence.jsonl")):
        for line in evidence_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _parse_iso(row.get("timestamp"))
            if timestamp is None or timestamp < threshold:
                continue
            rows.append(row)
    return rows


def _load_recent_queue_events(root: Path, window_days: int) -> list[dict[str, Any]]:
    path = root / ".ai" / "queue" / "events.jsonl"
    if not path.exists():
        return []
    threshold = datetime.now().astimezone() - timedelta(days=window_days)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = _parse_iso(row.get("timestamp"))
        if timestamp is None or timestamp < threshold:
            continue
        rows.append(row)
    return rows


def _attempt_value(row: dict[str, Any]) -> int:
    value = row.get("attempt")
    if isinstance(value, int) and value > 0:
        return value
    return 1


def _recovery_minutes(rows: list[dict[str, Any]]) -> float | None:
    first_failure: datetime | None = None
    for row in rows:
        ts = _parse_iso(row.get("timestamp"))
        if ts is None:
            continue
        if not bool(row.get("success")) and first_failure is None:
            first_failure = ts
            continue
        if first_failure is not None and bool(row.get("success")) and ts >= first_failure:
            return max(0.0, (ts - first_failure).total_seconds() / 60.0)
    return None


def _count_event(rows: list[dict[str, Any]], event_type: str, reason_code: str | None = None) -> int:
    count = 0
    for row in rows:
        if str(row.get("event_type") or "") != event_type:
            continue
        if reason_code is not None and str(row.get("reason_code") or "") != reason_code:
            continue
        count += 1
    return count


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_int(value: Any, default: int, *, min_value: int) -> int:
    if isinstance(value, int) and value >= min_value:
        return value
    return default


def _as_fraction(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        f = float(value)
        if 0.0 <= f <= 1.0:
            return f
    return default


def _as_positive_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return default
