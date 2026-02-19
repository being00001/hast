"""Tests for mechanical gate checks."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import subprocess


from hast.core.config import Config, GateConfig, LanguageProfileConfig
from hast.core.gate import run_gate
from hast.core.goals import Goal
from hast.core.security_policy import SecurityIgnoreRule, SecurityPolicy


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

    def test_gate_scope_allows_configured_generated_paths(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")
        _create_and_stage(tmp_project, "docs/ARCHITECTURE.md", "# generated\n")

        config = _make_config(always_allow_changes=["docs/ARCHITECTURE.md"])
        goal = _make_goal(allowed_changes=["src/*.py"])
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["scope"].passed is True


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


class TestGateRustProfiles:
    def test_gate_rust_only_checks(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "tests/test_smoke.rs", "fn smoke() { assert!(true); }\n")

        config = _make_config(
            language_profiles={
                "python": LanguageProfileConfig(
                    enabled=False,
                    test_file_globs=[],
                    assertion_patterns=[],
                    trivial_assertions=[],
                    targeted_test_command="",
                    gate_commands=[],
                ),
                "rust": LanguageProfileConfig(
                    enabled=True,
                    test_file_globs=["tests/**/*.rs", "tests/*.rs"],
                    assertion_patterns=["assert!("],
                    trivial_assertions=["assert!(true)"],
                    targeted_test_command="true",
                    gate_commands=["true", "true"],
                ),
            }
        )
        goal = _make_goal(languages=["rust"])
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert any(name.startswith("rust_check_") for name in result.checks.keys())
        assert "pytest" not in result.checks


class TestGateRequiredChecks:
    def test_gate_required_check_missing_fails(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(gate=GateConfig(required_checks=["ruff"]))
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["required_checks"].passed is False
        assert "skipped=ruff" in result.checks["required_checks"].output

    def test_gate_required_check_skip_can_be_ignored(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            gate=GateConfig(
                required_checks=["ruff"],
                fail_on_skipped_required=False,
            )
        )
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["required_checks"].passed is True


class TestGateSecurityCommands:
    def test_gate_security_command_failure_blocks(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(gate=GateConfig(security_commands=["false"]))
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert "security_check_1" in result.checks
        assert result.checks["security_check_1"].passed is False

    def test_gate_security_command_named_gitleaks(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            gate=GateConfig(
                security_commands=["echo gitleaks scan ok"],
                required_checks=["gitleaks"],
            )
        )
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert "gitleaks" in result.checks
        assert result.checks["gitleaks"].passed is True
        assert result.checks["required_checks"].passed is True

    def test_gate_security_bundle_policy_runs(self, monkeypatch, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        monkeypatch.setattr(
            "hast.core.gate.load_security_policy",
            lambda _root: SecurityPolicy(
                enabled=True,
                fail_on_missing_tools=False,
                dependency_scanner_mode="either",
                gitleaks_command="true",
                semgrep_command="true",
                trivy_command="true",
                grype_command="true",
            ),
        )

        config = _make_config(
            gate=GateConfig(
                required_checks=["gitleaks", "semgrep", "dependency_scan"],
            )
        )
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["gitleaks"].passed is True
        assert result.checks["semgrep"].passed is True
        assert result.checks["dependency_scan"].passed is True
        assert result.checks["required_checks"].passed is True

    def test_gate_security_bundle_missing_tool_can_skip(self, monkeypatch, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        monkeypatch.setattr(
            "hast.core.gate.load_security_policy",
            lambda _root: SecurityPolicy(
                enabled=True,
                fail_on_missing_tools=False,
                dependency_scanner_mode="either",
                gitleaks_enabled=True,
                gitleaks_command="missing-security-tool --scan",
                semgrep_enabled=False,
                trivy_enabled=False,
                grype_enabled=False,
            ),
        )

        config = _make_config()
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert "gitleaks" in result.checks
        assert result.checks["gitleaks"].skipped is True
        assert "missing security tool" in result.checks["gitleaks"].output

    def test_gate_security_bundle_missing_tool_can_fail(self, monkeypatch, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        monkeypatch.setattr(
            "hast.core.gate.load_security_policy",
            lambda _root: SecurityPolicy(
                enabled=True,
                fail_on_missing_tools=True,
                dependency_scanner_mode="either",
                gitleaks_enabled=True,
                gitleaks_command="missing-security-tool --scan",
                semgrep_enabled=False,
                trivy_enabled=False,
                grype_enabled=False,
            ),
        )

        config = _make_config()
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert "gitleaks" in result.checks
        assert result.checks["gitleaks"].skipped is False
        assert result.checks["gitleaks"].passed is False
        assert "missing security tool" in result.checks["gitleaks"].output

    def test_gate_security_ignore_rule_applies_and_audits(self, monkeypatch, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        monkeypatch.setattr(
            "hast.core.gate.load_security_policy",
            lambda _root: SecurityPolicy(
                enabled=True,
                fail_on_missing_tools=False,
                semgrep_enabled=True,
                semgrep_command="printf 'known false positive\\n' && false",
                gitleaks_enabled=False,
                trivy_enabled=False,
                grype_enabled=False,
                ignore_rules=[
                    SecurityIgnoreRule(
                        rule_id="SG-SEM-1",
                        checks=["semgrep"],
                        pattern="known false positive",
                        reason="tracked false positive",
                        expires_on=date(2099, 1, 1),
                    )
                ],
            ),
        )

        config = _make_config(gate=GateConfig(required_checks=["semgrep"]))
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["semgrep"].passed is True
        assert "[security-ignore]" in result.checks["semgrep"].output

        audit_path = tmp_project / ".ai" / "security" / "audit.jsonl"
        assert audit_path.exists()
        rows = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert rows
        assert rows[-1]["event_type"] == "security-ignore-applied"
        assert rows[-1]["rule_id"] == "SG-SEM-1"

    def test_gate_security_ignore_expired_is_not_applied(self, monkeypatch, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        monkeypatch.setattr(
            "hast.core.gate.load_security_policy",
            lambda _root: SecurityPolicy(
                enabled=True,
                fail_on_missing_tools=False,
                semgrep_enabled=True,
                semgrep_command="printf 'known false positive\\n' && false",
                gitleaks_enabled=False,
                trivy_enabled=False,
                grype_enabled=False,
                ignore_rules=[
                    SecurityIgnoreRule(
                        rule_id="SG-SEM-EXPIRED",
                        checks=["semgrep"],
                        pattern="known false positive",
                        reason="expired exception",
                        expires_on=date(2020, 1, 1),
                    )
                ],
            ),
        )

        config = _make_config()
        goal = _make_goal()
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["semgrep"].passed is False
        assert "[security-ignore-expired]" in result.checks["semgrep"].output

        audit_path = tmp_project / ".ai" / "security" / "audit.jsonl"
        rows = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert rows[-1]["event_type"] == "security-ignore-expired"
        assert rows[-1]["rule_id"] == "SG-SEM-EXPIRED"


class TestGateMutationChecks:
    def test_gate_mutation_fails_below_threshold_for_high_uncertainty(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            test_command="true",
            gate=GateConfig(
                mutation_enabled=True,
                mutation_high_risk_only=True,
                mutation_python_command="printf 'mutation score: 65%%\\n'",
                min_mutation_score_python=70,
            ),
        )
        goal = _make_goal(uncertainty="high")
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert "mutation_python" in result.checks
        assert result.checks["mutation_python"].passed is False

    def test_gate_mutation_passes_when_threshold_met(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            test_command="true",
            gate=GateConfig(
                mutation_enabled=True,
                mutation_high_risk_only=True,
                mutation_python_command="printf 'mutation score: 75%%\\n'",
                min_mutation_score_python=70,
            ),
        )
        goal = _make_goal(uncertainty="high")
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["mutation_python"].passed is True

    def test_gate_mutation_skipped_for_non_high_risk_goal(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            test_command="true",
            gate=GateConfig(
                mutation_enabled=True,
                mutation_high_risk_only=True,
                mutation_python_command="printf 'mutation score: 10%%\\n'",
                min_mutation_score_python=70,
            ),
        )
        goal = _make_goal(uncertainty="low")
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is True
        assert result.checks["mutation_python"].skipped is True

    def test_gate_mutation_skipped_when_prerequisite_checks_fail(self, tmp_project: Path) -> None:
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        _create_and_stage(tmp_project, "src/hello.py", "print('hi')\n")

        config = _make_config(
            test_command="false",
            gate=GateConfig(
                mutation_enabled=True,
                mutation_high_risk_only=True,
                mutation_python_command="printf 'mutation score: 100%%\\n'",
                min_mutation_score_python=70,
            ),
        )
        goal = _make_goal(uncertainty="high")
        result = run_gate(tmp_project, config, goal, base)

        assert result.passed is False
        assert result.checks["pytest"].passed is False
        assert result.checks["mutation_python"].skipped is True
