"""Consumer role policy for async worker pull routing (Wave 9D)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROLE_IMPLEMENT = "implement"
ROLE_TEST = "test"
ROLE_VERIFY = "verify"
ALLOWED_CONSUMER_ROLES = {ROLE_IMPLEMENT, ROLE_TEST, ROLE_VERIFY}


@dataclass(frozen=True)
class ConsumerRolePolicy:
    version: str = "v1"
    default_role: str = ROLE_IMPLEMENT
    phase_to_role: dict[str, str] | None = None


def load_consumer_role_policy(root: Path) -> ConsumerRolePolicy:
    path = root / ".ai" / "policies" / "consumer_role_policy.yaml"
    default_map = _default_phase_to_role()
    if not path.exists():
        return ConsumerRolePolicy(
            version="v1",
            default_role=ROLE_IMPLEMENT,
            phase_to_role=default_map,
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return ConsumerRolePolicy(version="v1", default_role=ROLE_IMPLEMENT, phase_to_role=default_map)

    default_role = _as_str(data.get("default_role"), ROLE_IMPLEMENT).lower()
    if default_role not in ALLOWED_CONSUMER_ROLES:
        default_role = ROLE_IMPLEMENT

    raw_map = data.get("phase_to_role")
    phase_map = _default_phase_to_role()
    if isinstance(raw_map, dict):
        normalized = _normalize_phase_map(raw_map)
        if normalized:
            phase_map = normalized

    return ConsumerRolePolicy(
        version=_as_str(data.get("version"), "v1"),
        default_role=default_role,
        phase_to_role=phase_map,
    )


def normalize_consumer_role(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    token = value.strip().lower()
    if token in ALLOWED_CONSUMER_ROLES:
        return token
    return None


def role_for_phase(root: Path, phase: str | None) -> str:
    policy = load_consumer_role_policy(root)
    phase_key = (phase or "").strip().lower()
    if phase_key and policy.phase_to_role and phase_key in policy.phase_to_role:
        return policy.phase_to_role[phase_key]
    return policy.default_role


def goal_is_claimable_for_role(root: Path, *, role: str, phase: str | None) -> bool:
    token = normalize_consumer_role(role)
    if token is None:
        return False
    return role_for_phase(root, phase) == token


def _default_phase_to_role() -> dict[str, str]:
    return {
        "plan": ROLE_IMPLEMENT,
        "implement": ROLE_IMPLEMENT,
        "adversarial": ROLE_TEST,
        "gate": ROLE_VERIFY,
        "review": ROLE_VERIFY,
    }


def _normalize_phase_map(raw_map: dict[Any, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for phase, role in raw_map.items():
        if not isinstance(phase, str) or not phase.strip():
            continue
        role_token = normalize_consumer_role(role if isinstance(role, str) else None)
        if role_token is None:
            continue
        out[phase.strip().lower()] = role_token
    return out


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
