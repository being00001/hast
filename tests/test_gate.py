"""Tests for mechanical gate checks."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from devf.core.config import Config, GateConfig
from devf.core.gate import CheckResult, GateResult, run_gate
from devf.core.goals import Goal


def _make_config(**overrides: object) -> Config:
    defaults: dict = {
        "test_command": "echo ok",
        "ai_tool": "echo {prompt}",
    }
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[arg-type]


def _make_goal(**overrides: object) -> Goal:
    defaults: dict = {
        "id": "G1",
        "title": "Test Goal",
        "status": "active",
    }
    defaults.update(overrides)
    return Goal(**defaults)  # type: ignore[arg-type]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=True,
    )


def _create_and_stage(root: Path, rel_path: str, content: str = "hello\n") -> None:
    """Create a file relative to root and stage it."""
    fp = root / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    _git(root, "add", rel_path)


class TestGateAllPass:
    def test_gate_all_pass(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config()
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert all(
            c.passed or c.skipped for c in result.checks.values()
        )


class TestGateTestsFail:
    def test_gate_tests_fail(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(test_command="false")
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["pytest"].passed is False


class TestGateDiffSizeExceeded:
    def test_gate_diff_size_exceeded(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        big_content = "\n".join(f"line {i}" for i in range(50)) + "\n"
        _create_and_stage(tmp_project, "src/big.py", big_content)

        config = _make_config(gate=GateConfig(max_diff_lines=5))
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["diff_size"].passed is False


class TestGateScopeViolation:
    def test_gate_scope_violation(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "outside.txt", "oops\n")

        config = _make_config()
        goal = _make_goal(allowed_changes=["src/*.py"])
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["scope"].passed is False
        assert "outside.txt" in result.checks["scope"].output


class TestGateMypySkipped:
    def test_gate_mypy_skipped(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(gate=GateConfig(mypy_command=""))
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["mypy"].skipped is True


class TestGateSummaryFormat:
    def test_gate_summary_format(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config()
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert "pytest" in result.summary
        assert "mypy" in result.summary
        assert "ruff" in result.summary
        assert "diff_size" in result.summary
        assert "scope" in result.summary
