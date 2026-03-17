"""Tests for acceptance contract parsing and helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hast.core.contract import (
    AcceptanceContract,
    contract_prompt_lines,
    load_acceptance_contract,
    validate_forbidden_patterns,
    validate_required_patterns,
)
from hast.core.errors import HastError


def test_load_acceptance_contract_basic(tmp_path: Path) -> None:
    contract_path = tmp_path / ".ai" / "contracts"
    contract_path.mkdir(parents=True)
    (contract_path / "login.contract.yaml").write_text(
        """
version: 1
must_pass_tests:
  - tests/test_login.py
required_assertions:
  - status_code == 200
security_requirements:
  - rate limit enabled
required_docs:
  - README.md
required_security_docs:
  - SECURITY.md
""",
        encoding="utf-8",
    )

    contract = load_acceptance_contract(tmp_path, ".ai/contracts/login.contract.yaml")
    assert contract is not None
    assert contract.must_pass_tests == ["tests/test_login.py"]
    assert contract.required_assertions == ["status_code == 200"]
    assert contract.security_requirements == ["rate limit enabled"]
    assert contract.required_docs == ["README.md"]
    assert contract.required_security_docs == ["SECURITY.md"]


def test_load_acceptance_contract_with_wrapper(tmp_path: Path) -> None:
    contract_path = tmp_path / ".ai" / "contracts"
    contract_path.mkdir(parents=True)
    (contract_path / "wrapped.contract.yaml").write_text(
        """
contract:
  required_changes:
    - src/auth.py
  forbidden_changes:
    - tests/*
""",
        encoding="utf-8",
    )

    contract = load_acceptance_contract(tmp_path, ".ai/contracts/wrapped.contract.yaml")
    assert contract is not None
    assert contract.required_changes == ["src/auth.py"]
    assert contract.forbidden_changes == ["tests/*"]


def test_load_acceptance_contract_missing_file(tmp_path: Path) -> None:
    with pytest.raises(HastError, match="contract file not found"):
        load_acceptance_contract(tmp_path, ".ai/contracts/nope.yaml")


def test_validate_required_patterns() -> None:
    ok, reason = validate_required_patterns(
        ["src/auth.py", "tests/test_auth.py"],
        ["src/*.py", "tests/test_*.py"],
        "changed files",
    )
    assert ok
    assert reason is None

    ok, reason = validate_required_patterns(
        ["src/auth.py"],
        ["tests/test_*.py"],
        "changed files",
    )
    assert not ok
    assert reason is not None


def test_validate_forbidden_patterns() -> None:
    ok, reason = validate_forbidden_patterns(
        ["src/auth.py"],
        ["tests/*"],
        "changed files",
    )
    assert ok
    assert reason is None

    ok, reason = validate_forbidden_patterns(
        ["tests/test_auth.py"],
        ["tests/*"],
        "changed files",
    )
    assert not ok
    assert reason is not None


def test_contract_prompt_lines() -> None:
    contract = AcceptanceContract(
        inputs=["email/password"],
        outputs=["access token"],
        security_requirements=["rate limit enabled"],
    )
    lines = contract_prompt_lines(contract)
    rendered = "\n".join(lines)
    assert "Inputs" in rendered
    assert "Outputs" in rendered
    assert "Security requirements" in rendered
