"""Immutable guardrails for autonomous edits (immune mode)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fnmatch
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


@dataclass(frozen=True)
class ImmunePolicy:
    version: str = "v1"
    enabled: bool = False
    require_grant_for_writes: bool = True
    grant_file: str = ".ai/immune/grant.yaml"
    audit_file: str = ".ai/immune/audit.jsonl"
    max_changed_files: int = 120
    protected_path_patterns: list[str] = field(
        default_factory=lambda: [
            ".ai/policies/**",
            ".ai/protocols/**",
            ".ai/immune/**",
        ]
    )


@dataclass(frozen=True)
class RepairGrant:
    grant_id: str
    issued_by: str
    approved_by: str
    issued_at: datetime | None
    expires_at: datetime | None
    allowed_changes: list[str]
    reason: str


@dataclass(frozen=True)
class ImmuneCheckResult:
    allowed: bool
    reason: str | None = None
    violation_code: str | None = None
    grant_id: str | None = None


def load_immune_policy(root: Path) -> ImmunePolicy:
    path = root / ".ai" / "policies" / "immune_policy.yaml"
    if not path.exists():
        return ImmunePolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ImmunePolicy()

    return ImmunePolicy(
        version=_parse_non_empty_str(data.get("version"), "v1"),
        enabled=bool(data.get("enabled", False)),
        require_grant_for_writes=bool(data.get("require_grant_for_writes", True)),
        grant_file=_parse_non_empty_str(data.get("grant_file"), ".ai/immune/grant.yaml"),
        audit_file=_parse_non_empty_str(data.get("audit_file"), ".ai/immune/audit.jsonl"),
        max_changed_files=_parse_positive_int(data.get("max_changed_files"), 120),
        protected_path_patterns=_parse_str_list(
            data.get("protected_path_patterns"),
            [".ai/policies/**", ".ai/protocols/**", ".ai/immune/**"],
        ),
    )


def evaluate_immune_changes(
    root: Path,
    changed_files: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> ImmuneCheckResult:
    policy = load_immune_policy(root)
    if not policy.enabled:
        return ImmuneCheckResult(allowed=True)
    if not changed_files:
        return ImmuneCheckResult(allowed=True)

    if len(changed_files) > policy.max_changed_files:
        result = ImmuneCheckResult(
            allowed=False,
            reason=(
                f"immune policy violation: change-set too large "
                f"({len(changed_files)} > {policy.max_changed_files})"
            ),
            violation_code="change-set-too-large",
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    protected_hits = _match_paths(changed_files, policy.protected_path_patterns)
    if protected_hits:
        result = ImmuneCheckResult(
            allowed=False,
            reason=(
                "immune policy violation: protected paths modified: "
                + ", ".join(protected_hits[:5])
            ),
            violation_code="protected-path-modified",
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    if not policy.require_grant_for_writes:
        return ImmuneCheckResult(allowed=True)

    grant = _load_repair_grant(root, policy.grant_file)
    if grant is None:
        result = ImmuneCheckResult(
            allowed=False,
            reason="immune policy violation: missing repair grant",
            violation_code="grant-missing",
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    now = datetime.now(timezone.utc)
    if grant.expires_at and now > grant.expires_at:
        result = ImmuneCheckResult(
            allowed=False,
            reason=(
                "immune policy violation: repair grant expired "
                f"at {grant.expires_at.isoformat()}"
            ),
            violation_code="grant-expired",
            grant_id=grant.grant_id,
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    if not grant.allowed_changes:
        result = ImmuneCheckResult(
            allowed=False,
            reason="immune policy violation: repair grant has no allowed_changes",
            violation_code="grant-empty-scope",
            grant_id=grant.grant_id,
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    out_of_scope = _out_of_scope_files(changed_files, grant.allowed_changes)
    if out_of_scope:
        result = ImmuneCheckResult(
            allowed=False,
            reason=(
                "immune policy violation: changes outside grant scope: "
                + ", ".join(out_of_scope[:5])
            ),
            violation_code="grant-scope-violation",
            grant_id=grant.grant_id,
        )
        _append_immune_audit(root, policy, changed_files, result, metadata)
        return result

    return ImmuneCheckResult(allowed=True, grant_id=grant.grant_id)


def write_repair_grant(
    root: Path,
    *,
    allowed_changes: list[str],
    approved_by: str,
    issued_by: str = "llm-supervisor",
    ttl_minutes: int = 30,
    reason: str = "",
) -> Path:
    policy = load_immune_policy(root)
    grant_path = root / policy.grant_file
    grant_path.parent.mkdir(parents=True, exist_ok=True)

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at if ttl_minutes <= 0 else issued_at.replace(
        microsecond=0
    ) + timedelta(minutes=ttl_minutes)

    payload = {
        "grant": {
            "version": 1,
            "grant_id": f"GRT_{uuid4().hex[:12]}",
            "issued_by": issued_by,
            "approved_by": approved_by,
            "issued_at": issued_at.replace(microsecond=0).isoformat(),
            "expires_at": expires_at.isoformat(),
            "allowed_changes": [item for item in allowed_changes if isinstance(item, str) and item.strip()],
            "reason": reason.strip(),
        }
    }
    grant_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return grant_path.relative_to(root)


def _load_repair_grant(root: Path, grant_file: str) -> RepairGrant | None:
    path = root / grant_file
    if not path.exists():
        return None

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    raw = data.get("grant", data)
    if not isinstance(raw, dict):
        return None

    return RepairGrant(
        grant_id=_parse_non_empty_str(raw.get("grant_id"), "unknown"),
        issued_by=_parse_non_empty_str(raw.get("issued_by"), "unknown"),
        approved_by=_parse_non_empty_str(raw.get("approved_by"), "unknown"),
        issued_at=_parse_iso(raw.get("issued_at")),
        expires_at=_parse_iso(raw.get("expires_at")),
        allowed_changes=_parse_str_list(raw.get("allowed_changes"), []),
        reason=_parse_non_empty_str(raw.get("reason"), ""),
    )


def _append_immune_audit(
    root: Path,
    policy: ImmunePolicy,
    changed_files: list[str],
    result: ImmuneCheckResult,
    metadata: dict[str, Any] | None,
) -> None:
    audit_path = root / policy.audit_file
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "immune-violation",
        "policy_version": policy.version,
        "violation_code": result.violation_code,
        "reason": result.reason,
        "grant_id": result.grant_id,
        "changed_files": changed_files,
    }
    if metadata:
        for key, value in metadata.items():
            row[key] = value
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _match_paths(paths: list[str], patterns: list[str]) -> list[str]:
    matched = [
        path
        for path in paths
        if any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    ]
    return sorted(matched)


def _out_of_scope_files(paths: list[str], patterns: list[str]) -> list[str]:
    out: list[str] = []
    for path in paths:
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            out.append(path)
    return sorted(out)


def _parse_non_empty_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_str_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    parsed: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            parsed.append(item.strip())
    return parsed or list(default)


def _parse_positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return default


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
