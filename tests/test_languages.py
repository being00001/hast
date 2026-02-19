"""Tests for language profile command helpers."""

from __future__ import annotations

from hast.core.config import GateConfig
from hast.core.languages import apply_pytest_reliability_flags


def test_apply_pytest_reliability_flags_parallel_and_random() -> None:
    gate = GateConfig(
        pytest_parallel=True,
        pytest_workers="auto",
        pytest_reruns_on_flaky=2,
        pytest_random_order=True,
    )

    base = apply_pytest_reliability_flags("pytest -q tests/test_app.py", gate, include_reruns=False)
    assert "-n auto" in base
    assert "--random-order" in base
    assert "--reruns" not in base

    rerun = apply_pytest_reliability_flags("pytest -q tests/test_app.py", gate, include_reruns=True)
    assert "--reruns 2" in rerun


def test_apply_pytest_reliability_flags_non_pytest_noop() -> None:
    gate = GateConfig(pytest_parallel=True, pytest_workers="auto")
    command = "cargo test"
    assert apply_pytest_reliability_flags(command, gate, include_reruns=True) == command


def test_apply_pytest_reliability_flags_python_module_pytest() -> None:
    gate = GateConfig(pytest_parallel=True, pytest_workers="4", pytest_random_order=True)
    command = "python -m pytest -q"
    rendered = apply_pytest_reliability_flags(command, gate, include_reruns=False)
    assert "python -m pytest -q -n 4 --random-order" in rendered


def test_apply_pytest_reliability_flags_does_not_duplicate_existing_flags() -> None:
    gate = GateConfig(
        pytest_parallel=True,
        pytest_workers="auto",
        pytest_reruns_on_flaky=2,
        pytest_random_order=True,
    )
    command = "pytest -q -n 2 --random-order --reruns 1"
    rendered = apply_pytest_reliability_flags(command, gate, include_reruns=True)
    assert rendered == command
