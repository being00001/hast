"""Acceptance contract loading and lightweight validation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path

import yaml

from hast.core.errors import DevfError
from hast.utils.fs import normalize_path


@dataclass(frozen=True)
class AcceptanceContract:
    version: int = 1
    must_pass_tests: list[str] = field(default_factory=list)
    must_fail_tests: list[str] = field(default_factory=list)
    required_test_files: list[str] = field(default_factory=list)
    required_assertions: list[str] = field(default_factory=list)
    required_changes: list[str] = field(default_factory=list)
    forbidden_changes: list[str] = field(default_factory=list)
    required_docs: list[str] = field(default_factory=list)
    required_security_docs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    state_transitions: list[str] = field(default_factory=list)
    error_cases: list[str] = field(default_factory=list)
    security_requirements: list[str] = field(default_factory=list)


def load_acceptance_contract(root: Path, contract_file: str | None) -> AcceptanceContract | None:
    """Load and validate a goal contract file."""
    if not contract_file:
        return None

    path = root / contract_file
    if not path.exists():
        raise DevfError(f"contract file not found: {contract_file}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise DevfError(f"contract must be a mapping: {contract_file}")

    # Optional wrapper for readability:
    # contract:
    #   must_pass_tests: [...]
    if "contract" in data:
        wrapped = data.get("contract")
        if not isinstance(wrapped, dict):
            raise DevfError(f"contract.contract must be a mapping: {contract_file}")
        data = wrapped

    version = data.get("version", 1)
    if not isinstance(version, int) or version <= 0:
        raise DevfError(f"contract.version must be a positive integer: {contract_file}")

    return AcceptanceContract(
        version=version,
        must_pass_tests=_parse_str_list(data, "must_pass_tests", contract_file, root, normalize=True),
        must_fail_tests=_parse_str_list(data, "must_fail_tests", contract_file, root, normalize=True),
        required_test_files=_parse_str_list(data, "required_test_files", contract_file, root, normalize=True),
        required_assertions=_parse_str_list(data, "required_assertions", contract_file, root, normalize=False),
        required_changes=_parse_str_list(data, "required_changes", contract_file, root, normalize=True),
        forbidden_changes=_parse_str_list(data, "forbidden_changes", contract_file, root, normalize=True),
        required_docs=_parse_str_list(data, "required_docs", contract_file, root, normalize=True),
        required_security_docs=_parse_str_list(
            data, "required_security_docs", contract_file, root, normalize=True,
        ),
        inputs=_parse_str_list(data, "inputs", contract_file, root, normalize=False),
        outputs=_parse_str_list(data, "outputs", contract_file, root, normalize=False),
        state_transitions=_parse_str_list(data, "state_transitions", contract_file, root, normalize=False),
        error_cases=_parse_str_list(data, "error_cases", contract_file, root, normalize=False),
        security_requirements=_parse_str_list(data, "security_requirements", contract_file, root, normalize=False),
    )


def validate_required_patterns(items: list[str], patterns: list[str], label: str) -> tuple[bool, str | None]:
    """Require every pattern to match at least one item."""
    for pattern in patterns:
        if not any(fnmatch.fnmatch(item, pattern) for item in items):
            return False, f"{label} missing required pattern: {pattern}"
    return True, None


def validate_forbidden_patterns(items: list[str], patterns: list[str], label: str) -> tuple[bool, str | None]:
    """Reject any item that matches forbidden patterns."""
    for item in items:
        for pattern in patterns:
            if fnmatch.fnmatch(item, pattern):
                return False, f"{label} violated forbidden pattern {pattern}: {item}"
    return True, None


def contract_prompt_lines(contract: AcceptanceContract) -> list[str]:
    """Render human-readable contract summary for prompts."""
    lines: list[str] = ["ACCEPTANCE CONTRACT (READ-ONLY):"]
    if contract.inputs:
        lines.append("- Inputs:")
        lines.extend(f"  - {v}" for v in contract.inputs[:8])
    if contract.outputs:
        lines.append("- Outputs:")
        lines.extend(f"  - {v}" for v in contract.outputs[:8])
    if contract.state_transitions:
        lines.append("- State transitions:")
        lines.extend(f"  - {v}" for v in contract.state_transitions[:8])
    if contract.error_cases:
        lines.append("- Error cases:")
        lines.extend(f"  - {v}" for v in contract.error_cases[:8])
    if contract.security_requirements:
        lines.append("- Security requirements:")
        lines.extend(f"  - {v}" for v in contract.security_requirements[:8])
    if contract.required_assertions:
        lines.append("- Required assertions:")
        lines.extend(f"  - {v}" for v in contract.required_assertions[:8])
    if contract.must_pass_tests:
        lines.append("- Must pass tests:")
        lines.extend(f"  - {v}" for v in contract.must_pass_tests[:8])
    if contract.must_fail_tests:
        lines.append("- Must fail tests in RED:")
        lines.extend(f"  - {v}" for v in contract.must_fail_tests[:8])
    if contract.required_changes:
        lines.append("- Required code changes:")
        lines.extend(f"  - {v}" for v in contract.required_changes[:8])
    if contract.required_docs:
        lines.append("- Required docs updates:")
        lines.extend(f"  - {v}" for v in contract.required_docs[:8])
    if contract.required_security_docs:
        lines.append("- Required security docs updates:")
        lines.extend(f"  - {v}" for v in contract.required_security_docs[:8])
    if contract.forbidden_changes:
        lines.append("- Forbidden code changes:")
        lines.extend(f"  - {v}" for v in contract.forbidden_changes[:8])
    return lines


def _parse_str_list(
    data: dict,
    key: str,
    contract_file: str,
    root: Path,
    normalize: bool,
) -> list[str]:
    raw = data.get(key, [])
    if not isinstance(raw, list):
        raise DevfError(f"contract.{key} must be a list: {contract_file}")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise DevfError(f"contract.{key} entries must be strings: {contract_file}")
        result.append(normalize_path(item, root) if normalize else item)
    return result
