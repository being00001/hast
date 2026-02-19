"""Protocol adapter bridge for external orchestrators (Wave 9E)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import yaml

from hast.core.consumer_roles import normalize_consumer_role, role_for_phase
from hast.core.context import build_context
from hast.core.control_plane_contract import ALLOWED_ACTIONS
from hast.core.errors import DevfError
from hast.core.event_bus import emit_shadow_event
from hast.core.evidence import new_run_id, write_evidence_row
from hast.core.goals import find_goal, load_goals, select_active_goal

SUPPORTED_PROTOCOL_ADAPTERS = {"langgraph", "openhands"}
SUPPORTED_CONTEXT_FORMATS = {"pack", "markdown", "plain", "json"}


@dataclass(frozen=True)
class ProtocolAdapterPolicy:
    version: str = "v1"
    enabled_adapters: tuple[str, ...] = ("langgraph", "openhands")
    default_export_context_format: str = "pack"
    include_context_by_default: bool = True
    include_prompt_by_default: bool = True
    max_context_chars: int = 200_000
    require_goal_exists: bool = True
    result_inbox_dir: str = ".ai/protocols/inbox"
    processed_results_dir: str = ".ai/protocols/processed"
    poll_interval_seconds: int = 2
    max_wait_seconds: int = 900
    require_packet_id_match: bool = True
    archive_consumed_packets: bool = True


@dataclass(frozen=True)
class ProtocolExportResult:
    packet: dict[str, Any]
    packet_path: Path | None


@dataclass(frozen=True)
class ProtocolIngestResult:
    run_id: str
    goal_id: str
    adapter: str
    evidence_path: Path
    inbox_path: Path
    event_id: str | None


@dataclass(frozen=True)
class ProtocolResultPacketMatch:
    path: Path
    packet: dict[str, Any]


def load_protocol_adapter_policy(root: Path) -> ProtocolAdapterPolicy:
    path = root / ".ai" / "policies" / "protocol_adapter_policy.yaml"
    if not path.exists():
        return ProtocolAdapterPolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ProtocolAdapterPolicy()

    enabled_raw = data.get("enabled_adapters", list(SUPPORTED_PROTOCOL_ADAPTERS))
    enabled: list[str] = []
    if isinstance(enabled_raw, list):
        for item in enabled_raw:
            if not isinstance(item, str):
                continue
            token = item.strip().lower()
            if token in SUPPORTED_PROTOCOL_ADAPTERS and token not in enabled:
                enabled.append(token)
    if not enabled:
        enabled = sorted(SUPPORTED_PROTOCOL_ADAPTERS)

    context_format = _as_str(data.get("default_export_context_format"), "pack").lower()
    if context_format not in SUPPORTED_CONTEXT_FORMATS:
        context_format = "pack"

    include_default = _as_bool(data.get("include_context_by_default"), True)
    include_prompt_default = _as_bool(data.get("include_prompt_by_default"), True)
    max_context_chars = _bounded_int(
        data.get("max_context_chars"),
        default=200_000,
        min_value=1_000,
        max_value=2_000_000,
    )
    require_goal_exists = _as_bool(data.get("require_goal_exists"), True)
    result_inbox_dir = _as_str(data.get("result_inbox_dir"), ".ai/protocols/inbox")
    processed_results_dir = _as_str(data.get("processed_results_dir"), ".ai/protocols/processed")
    poll_interval_seconds = _bounded_int(
        data.get("poll_interval_seconds"),
        default=2,
        min_value=1,
        max_value=60,
    )
    max_wait_seconds = _bounded_int(
        data.get("max_wait_seconds"),
        default=900,
        min_value=1,
        max_value=86_400,
    )
    require_packet_id_match = _as_bool(data.get("require_packet_id_match"), True)
    archive_consumed_packets = _as_bool(data.get("archive_consumed_packets"), True)

    return ProtocolAdapterPolicy(
        version=_as_str(data.get("version"), "v1"),
        enabled_adapters=tuple(enabled),
        default_export_context_format=context_format,
        include_context_by_default=include_default,
        include_prompt_by_default=include_prompt_default,
        max_context_chars=max_context_chars,
        require_goal_exists=require_goal_exists,
        result_inbox_dir=result_inbox_dir,
        processed_results_dir=processed_results_dir,
        poll_interval_seconds=poll_interval_seconds,
        max_wait_seconds=max_wait_seconds,
        require_packet_id_match=require_packet_id_match,
        archive_consumed_packets=archive_consumed_packets,
    )


def export_protocol_task_packet(
    root: Path,
    *,
    adapter: str,
    goal_id: str | None = None,
    role: str | None = None,
    context_format: str | None = None,
    include_context: bool | None = None,
    prompt_text: str | None = None,
    include_prompt: bool | None = None,
    write_file: bool = True,
) -> ProtocolExportResult:
    policy = load_protocol_adapter_policy(root)
    adapter_token = _normalize_adapter(adapter, policy)
    selected_goal = _resolve_goal(root, goal_id)
    role_token = normalize_consumer_role(role) if role is not None else None
    if role is not None and role_token is None:
        raise DevfError(f"invalid role: {role}")
    if role_token is None:
        role_token = role_for_phase(root, selected_goal.phase)

    resolved_context_format = (
        context_format.strip().lower()
        if isinstance(context_format, str) and context_format.strip()
        else policy.default_export_context_format
    )
    if resolved_context_format not in SUPPORTED_CONTEXT_FORMATS:
        raise DevfError(
            f"invalid context format: {resolved_context_format} "
            f"(allowed: {', '.join(sorted(SUPPORTED_CONTEXT_FORMATS))})"
        )
    include_ctx = policy.include_context_by_default if include_context is None else include_context
    include_prompt_text = policy.include_prompt_by_default if include_prompt is None else include_prompt

    context_text: str | None = None
    if include_ctx:
        context_text = build_context(root, resolved_context_format, goal_override=selected_goal)
        if len(context_text) > policy.max_context_chars:
            raise DevfError(
                f"context too large for protocol export "
                f"({len(context_text)} > {policy.max_context_chars})"
            )
    exported_prompt: str | None = None
    if include_prompt_text and isinstance(prompt_text, str):
        if len(prompt_text) > policy.max_context_chars:
            raise DevfError(
                f"prompt too large for protocol export "
                f"({len(prompt_text)} > {policy.max_context_chars})"
            )
        exported_prompt = prompt_text

    run_id = new_run_id()
    packet = {
        "schema_version": "protocol_task.v1",
        "packet_id": f"pkt_{uuid4().hex[:16]}",
        "adapter": adapter_token,
        "created_at": datetime.now().astimezone().isoformat(),
        "run_id": run_id,
        "goal": {
            "goal_id": selected_goal.id,
            "title": selected_goal.title,
            "status": selected_goal.status,
            "phase": selected_goal.phase,
            "uncertainty": selected_goal.uncertainty,
            "owner_agent": selected_goal.owner_agent,
            "allowed_changes": list(selected_goal.allowed_changes),
            "test_files": list(selected_goal.test_files),
        },
        "execution": {
            "role": role_token,
            "mode": "non-interactive",
            "contract": "bounded-write-scope",
            "prompt": exported_prompt,
        },
        "context": {
            "included": include_ctx,
            "format": resolved_context_format,
            "text": context_text,
        },
        "instructions": _adapter_instructions(adapter_token),
    }

    packet_path: Path | None = None
    if write_file:
        packet_path = _write_task_packet(root, packet)
    return ProtocolExportResult(packet=packet, packet_path=packet_path)


def ingest_protocol_result_packet(root: Path, packet: dict[str, Any]) -> ProtocolIngestResult:
    payload = _validate_result_packet(packet, root)
    run_id = payload["run_id"]
    goal_id = payload["goal_id"]
    adapter = payload["adapter"]
    evidence_row = payload["evidence_row"]

    write_evidence_row(root, run_id, evidence_row)
    evidence_path = root / ".ai" / "runs" / run_id / "evidence.jsonl"

    inbox_path = root / ".ai" / "protocols" / "inbox" / "results.jsonl"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    raw_row = {
        "ingested_at": datetime.now().astimezone().isoformat(),
        "schema_version": "protocol_result.v1",
        "adapter": adapter,
        "goal_id": goal_id,
        "run_id": run_id,
        "payload": packet,
    }
    with inbox_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(raw_row, ensure_ascii=False, sort_keys=True) + "\n")

    event_id = emit_shadow_event(
        root,
        source="protocol",
        event_type="protocol_result_ingested",
        payload={
            "adapter": adapter,
            "goal_id": goal_id,
            "run_id": run_id,
            "success": evidence_row["success"],
            "action_taken": evidence_row["action_taken"],
            "classification": evidence_row["classification"],
        },
        idempotency_key=f"protocol_result|{adapter}|{goal_id}|{run_id}|{evidence_row['attempt']}",
    )
    return ProtocolIngestResult(
        run_id=run_id,
        goal_id=goal_id,
        adapter=adapter,
        evidence_path=evidence_path,
        inbox_path=inbox_path,
        event_id=event_id,
    )


def load_result_packet_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DevfError(f"result packet file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DevfError(f"invalid result packet JSON: {path}") from exc
    if not isinstance(data, dict):
        raise DevfError("result packet must be a JSON object")
    return data


def wait_for_result_packet(
    root: Path,
    *,
    adapter: str,
    goal_id: str,
    packet_id: str | None,
    run_id: str | None,
    timeout_seconds: int | None = None,
    poll_interval_seconds: int | None = None,
) -> ProtocolResultPacketMatch:
    policy = load_protocol_adapter_policy(root)
    adapter_token = _normalize_adapter(adapter, policy)
    timeout = timeout_seconds if timeout_seconds is not None else policy.max_wait_seconds
    poll = poll_interval_seconds if poll_interval_seconds is not None else policy.poll_interval_seconds
    timeout = _bounded_int(timeout, default=policy.max_wait_seconds, min_value=1, max_value=86_400)
    poll = _bounded_int(poll, default=policy.poll_interval_seconds, min_value=1, max_value=60)

    inbox_dir = _resolve_policy_path(root, policy.result_inbox_dir)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout

    while True:
        for path in sorted(inbox_dir.glob("*.json")):
            packet = _try_load_packet(path)
            if packet is None:
                continue
            if not _packet_matches(
                packet,
                adapter=adapter_token,
                goal_id=goal_id,
                packet_id=packet_id,
                run_id=run_id,
                require_packet_id_match=policy.require_packet_id_match,
            ):
                continue
            return ProtocolResultPacketMatch(path=path, packet=packet)

        if time.monotonic() >= deadline:
            raise DevfError(
                f"protocol result timeout after {timeout}s "
                f"(adapter={adapter_token}, goal_id={goal_id}, packet_id={packet_id or '(none)'})"
            )
        time.sleep(poll)


def archive_result_packet(root: Path, result_packet_path: Path) -> Path:
    policy = load_protocol_adapter_policy(root)
    archive_dir = _resolve_policy_path(root, policy.processed_results_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    dest = archive_dir / f"{ts}_{result_packet_path.name}"
    result_packet_path.replace(dest)
    return dest


def _write_task_packet(root: Path, packet: dict[str, Any]) -> Path:
    out_dir = root / ".ai" / "protocols" / "outbox"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    goal_id = _safe_file_token(str(packet["goal"]["goal_id"]))
    adapter = _safe_file_token(str(packet["adapter"]))
    path = out_dir / f"{ts}_{adapter}_{goal_id}.json"
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _resolve_policy_path(root: Path, configured: str) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return root / path


def _resolve_goal(root: Path, goal_id: str | None):
    goals = load_goals(root / ".ai" / "goals.yaml")
    if goal_id:
        goal = find_goal(goals, goal_id)
        if goal is None:
            raise DevfError(f"goal not found: {goal_id}")
        return goal
    selected = select_active_goal(goals, None)
    if selected is None:
        raise DevfError("no active goal to export")
    return selected


def _normalize_adapter(adapter: str, policy: ProtocolAdapterPolicy) -> str:
    token = adapter.strip().lower()
    if token not in SUPPORTED_PROTOCOL_ADAPTERS:
        raise DevfError(f"unsupported adapter: {adapter}")
    if token not in set(policy.enabled_adapters):
        raise DevfError(f"adapter disabled by policy: {adapter}")
    return token


def _adapter_instructions(adapter: str) -> list[str]:
    if adapter == "langgraph":
        return [
            "Use packet.goal and packet.context as graph state input.",
            "Run non-interactive execution with bounded write scope.",
            "Return protocol_result.v1 with action_taken and classification.",
        ]
    return [
        "Run OpenHands task from packet.goal + packet.context.",
        "Do not request interactive clarification; apply safest assumption.",
        "Return protocol_result.v1 with action_taken and classification.",
    ]


def _validate_result_packet(packet: dict[str, Any], root: Path) -> dict[str, Any]:
    policy = load_protocol_adapter_policy(root)
    schema_version = _as_str(packet.get("schema_version"), "protocol_result.v1")
    if schema_version != "protocol_result.v1":
        raise DevfError(f"invalid schema_version: {schema_version}")

    adapter = _normalize_adapter(_as_str(packet.get("adapter"), ""), policy)
    goal_id = _as_str(packet.get("goal_id"), "")
    if not goal_id:
        raise DevfError("goal_id is required")
    if policy.require_goal_exists:
        goals = load_goals(root / ".ai" / "goals.yaml")
        if find_goal(goals, goal_id) is None:
            raise DevfError(f"goal not found for result packet: {goal_id}")

    success = packet.get("success")
    if not isinstance(success, bool):
        raise DevfError("success must be boolean")

    action_taken = _as_str(packet.get("action_taken"), "advance").lower()
    if action_taken not in ALLOWED_ACTIONS:
        raise DevfError(f"invalid action_taken: {action_taken}")

    classification = _as_str(packet.get("classification"), "complete" if success else "failed-external")
    phase = _as_str(packet.get("phase"), "implement")
    attempt = _bounded_int(packet.get("attempt"), default=1, min_value=1, max_value=1000)
    run_id = _as_str(packet.get("run_id"), new_run_id())
    summary = _as_str(packet.get("summary"), "")
    failure_classification = _nullable_str(packet.get("failure_classification"))
    if not success and failure_classification is None and action_taken in {"retry", "escalate", "block"}:
        failure_classification = "impl-defect"

    evidence_row = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "run_id": run_id,
        "goal_id": goal_id,
        "phase": phase,
        "attempt": attempt,
        "success": success,
        "should_retry": action_taken == "retry",
        "classification": classification,
        "action_taken": action_taken,
        "failure_classification": failure_classification,
        "reason": summary or None,
        "event_type": "auto_attempt",
        "model_used": f"external:{adapter}",
    }
    return {
        "adapter": adapter,
        "goal_id": goal_id,
        "run_id": run_id,
        "evidence_row": evidence_row,
    }


def _packet_matches(
    packet: dict[str, Any],
    *,
    adapter: str,
    goal_id: str,
    packet_id: str | None,
    run_id: str | None,
    require_packet_id_match: bool,
) -> bool:
    if _as_str(packet.get("schema_version"), "") != "protocol_result.v1":
        return False
    if _as_str(packet.get("adapter"), "").lower() != adapter:
        return False
    if _as_str(packet.get("goal_id"), "") != goal_id:
        return False
    if run_id is not None and _as_str(packet.get("run_id"), "") != run_id:
        return False
    packet_packet_id = _nullable_str(packet.get("packet_id"))
    if require_packet_id_match and packet_id is not None:
        return packet_packet_id == packet_id
    if packet_id is not None and packet_packet_id is not None:
        return packet_packet_id == packet_id
    return True


def _try_load_packet(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _safe_file_token(value: str) -> str:
    token = value.strip().replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in token)


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _nullable_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bounded_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    if not isinstance(value, int):
        return default
    if value < min_value or value > max_value:
        return default
    return value
