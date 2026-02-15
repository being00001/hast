"""Focused tests for RED quality gates and failure triage."""

from __future__ import annotations

from pathlib import Path
import subprocess

from devf.core.auto import (
    _run_tests,
    evaluate,
    _validate_planned_changes,
    _triage_test_failure,
    _validate_contract_change_rules,
    _validate_bdd_impl_scope,
    _validate_role_scope,
    _verify_bdd_red_stage,
)
from devf.core.contract import AcceptanceContract
from devf.core.config import Config, GateConfig, LanguageProfileConfig
from devf.core.goals import Goal
from devf.utils.file_parser import FileChange


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("test\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return _git(root, "rev-parse", "HEAD")


def _rust_test_config(targeted_test_command: str = "false") -> Config:
    return Config(
        test_command="true",
        ai_tool="echo {prompt}",
        language_profiles={
            "rust": LanguageProfileConfig(
                enabled=True,
                test_file_globs=["tests/**/*.rs", "tests/*.rs"],
                assertion_patterns=["assert!(", "assert_eq!(", "assert_ne!("],
                trivial_assertions=["assert!(true)", "assert_eq!(1, 1)"],
                targeted_test_command=targeted_test_command,
                gate_commands=["true"],
            ),
            "python": LanguageProfileConfig(
                enabled=False,
                test_file_globs=[],
                assertion_patterns=[],
                trivial_assertions=[],
                targeted_test_command="",
                gate_commands=[],
            ),
        },
    )


def test_triage_failure_classification() -> None:
    c1, _ = _triage_test_failure("ModuleNotFoundError: No module named 'x'")
    c2, _ = _triage_test_failure("SyntaxError: invalid syntax")
    c3, _ = _triage_test_failure("AssertionError: expected 1 == 2")
    assert c1 == "failed-env"
    assert c2 == "failed-syntax"
    assert c3 == "failed-impl"


def test_run_tests_applies_pytest_parallel_flags(monkeypatch, tmp_path: Path) -> None:
    commands: list[str] = []

    class _Proc:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode
            self.stdout = "ok"
            self.stderr = ""

    def _fake_run(command: str, **kwargs: object) -> _Proc:
        commands.append(command)
        return _Proc(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    config = Config(
        test_command="pytest -q",
        ai_tool="echo {prompt}",
        gate=GateConfig(pytest_parallel=True, pytest_workers="auto", pytest_random_order=True),
    )
    ok, output = _run_tests(tmp_path, "pytest -q", config)

    assert ok
    assert output == "ok"
    assert len(commands) == 1
    assert "-n auto" in commands[0]
    assert "--random-order" in commands[0]


def test_run_tests_reruns_when_flaky_failure_detected(monkeypatch, tmp_path: Path) -> None:
    commands: list[str] = []

    class _Proc:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    responses = [
        _Proc(returncode=1, stdout="FAILED due to timeout"),
        _Proc(returncode=0, stdout="PASSED on rerun"),
    ]

    def _fake_run(command: str, **kwargs: object) -> _Proc:
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    config = Config(
        test_command="pytest -q",
        ai_tool="echo {prompt}",
        gate=GateConfig(pytest_reruns_on_flaky=2),
    )
    ok, output = _run_tests(tmp_path, "pytest -q", config)

    assert ok
    assert len(commands) == 2
    assert "--reruns 2" in commands[1]
    assert "[devf] flaky rerun triggered" in output


def test_run_tests_does_not_rerun_non_flaky_failure(monkeypatch, tmp_path: Path) -> None:
    commands: list[str] = []

    class _Proc:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def _fake_run(command: str, **kwargs: object) -> _Proc:
        commands.append(command)
        return _Proc(returncode=1, stdout="AssertionError: expected 1 == 2")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    config = Config(
        test_command="pytest -q",
        ai_tool="echo {prompt}",
        gate=GateConfig(pytest_reruns_on_flaky=2),
    )
    ok, output = _run_tests(tmp_path, "pytest -q", config)

    assert not ok
    assert "AssertionError" in output
    assert len(commands) == 1


def test_validate_bdd_impl_scope_blocks_tests_and_specs() -> None:
    ok, reason = _validate_bdd_impl_scope(["src/app.py"])
    assert ok
    assert reason is None

    ok, reason = _validate_bdd_impl_scope(["tests/test_app.py", "src/app.py"])
    assert not ok
    assert reason is not None
    assert "tests/test_app.py" in reason

    ok, reason = _validate_bdd_impl_scope(["features/login.feature"])
    assert not ok
    assert reason is not None
    assert "login.feature" in reason


def test_validate_role_scope() -> None:
    goal_tester = Goal(id="G1", title="test", status="active", owner_agent="tester")
    ok, reason = _validate_role_scope(goal_tester, ["tests/test_app.py"])
    assert ok
    assert reason is None
    ok, reason = _validate_role_scope(goal_tester, ["src/app.py"])
    assert not ok
    assert "tester role" in (reason or "")

    goal_worker = Goal(id="G2", title="impl", status="active", owner_agent="worker")
    ok, reason = _validate_role_scope(goal_worker, ["src/app.py"])
    assert ok
    assert reason is None
    ok, reason = _validate_role_scope(goal_worker, ["tests/test_app.py"])
    assert not ok
    assert "worker role" in (reason or "")


def test_validate_planned_changes_hard_block() -> None:
    goal_tester = Goal(id="G1", title="test", status="active", owner_agent="tester")
    ok, reason = _validate_planned_changes(
        Path("."),
        goal_tester,
        {"src/app.py": "x = 1\n"},
        stage="legacy",
    )
    assert not ok
    assert "tester role" in (reason or "")

    goal_impl = Goal(id="G2", title="impl", status="active", owner_agent="worker")
    ok, reason = _validate_planned_changes(
        Path("."),
        goal_impl,
        {"tests/test_app.py": "def test_x(): pass\n"},
        stage="bdd-green",
        contract_file=".ai/contracts/login.contract.yaml",
    )
    assert not ok
    assert "protected files" in (reason or "") or "worker role" in (reason or "")

    ok, reason = _validate_planned_changes(
        Path("."),
        Goal(id="G3", title="red", status="active"),
        {"src/app.py": "x = 1\n"},
        stage="bdd-red",
    )
    assert not ok
    assert "RED stage" in (reason or "")

    ok, reason = _validate_planned_changes(
        Path("."),
        Goal(id="G4", title="red", status="active"),
        [FileChange(path="src/app.py", content="x = 1\n")],
        stage="bdd-red",
    )
    assert not ok
    assert "RED stage" in (reason or "")


def test_validate_contract_change_rules() -> None:
    contract = AcceptanceContract(
        required_changes=["src/*.py"],
        forbidden_changes=["tests/*"],
        required_docs=["README.md", "docs/*.md"],
        required_security_docs=["SECURITY.md"],
    )

    ok, reason = _validate_contract_change_rules(
        ["src/app.py"],
        contract,
        ".ai/contracts/login.contract.yaml",
    )
    assert not ok
    assert "README.md" in (reason or "") or "docs/*.md" in (reason or "")

    ok, reason = _validate_contract_change_rules(
        ["tests/test_app.py"],
        contract,
        ".ai/contracts/login.contract.yaml",
    )
    assert not ok
    assert reason is not None

    ok, reason = _validate_contract_change_rules(
        [".ai/contracts/login.contract.yaml", "src/app.py"],
        contract,
        ".ai/contracts/login.contract.yaml",
    )
    assert not ok
    assert reason is not None

    ok, reason = _validate_contract_change_rules(
        ["src/app.py", "README.md", "docs/guide.md"],
        contract,
        ".ai/contracts/login.contract.yaml",
    )
    assert not ok
    assert "SECURITY.md" in (reason or "")

    ok, reason = _validate_contract_change_rules(
        ["src/app.py", "README.md", "docs/guide.md", "SECURITY.md"],
        contract,
        ".ai/contracts/login.contract.yaml",
    )
    assert ok
    assert reason is None


def test_red_gate_requires_python_test_files(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    gate = _verify_bdd_red_stage(tmp_path, base)
    assert not gate.passed
    assert "test files" in gate.reason


def test_red_gate_rejects_src_changes(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_x():\n    assert False\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    gate = _verify_bdd_red_stage(tmp_path, base)
    assert not gate.passed
    assert "source files changed" in gate.reason


def test_red_gate_contract_required_assertion_missing(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_x():\n    assert 1 == 2\n",
        encoding="utf-8",
    )
    contract = AcceptanceContract(required_assertions=["status_code == 200"])
    gate = _verify_bdd_red_stage(
        tmp_path,
        base,
        ".ai/contracts/login.contract.yaml",
        contract,
    )
    assert not gate.passed
    assert "required assertion" in gate.reason


def test_red_gate_accepts_meaningful_failing_tests(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_red.py").write_text(
        "def test_red_gate_target():\n    assert 1 == 2\n",
        encoding="utf-8",
    )

    gate = _verify_bdd_red_stage(tmp_path, base)
    assert gate.passed
    assert gate.test_files == ["tests/test_red.py"]


def test_red_gate_rejects_trivial_assertions(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_trivial.py").write_text(
        "def test_trivial():\n    assert True\n",
        encoding="utf-8",
    )

    gate = _verify_bdd_red_stage(tmp_path, base)
    assert not gate.passed
    assert "trivial" in gate.reason


def test_red_gate_accepts_rust_failing_tests(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_red.rs").write_text(
        "fn smoke() { assert_eq!(1, 2); }\n",
        encoding="utf-8",
    )

    gate = _verify_bdd_red_stage(
        tmp_path,
        base,
        config=_rust_test_config(targeted_test_command="false"),
        languages=["rust"],
    )
    assert gate.passed
    assert gate.test_files == ["tests/test_red.rs"]


def test_red_gate_rejects_rust_trivial_assertions(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_trivial.rs").write_text(
        "fn smoke() { assert!(true); }\n",
        encoding="utf-8",
    )

    gate = _verify_bdd_red_stage(
        tmp_path,
        base,
        config=_rust_test_config(targeted_test_command="false"),
        languages=["rust"],
    )
    assert not gate.passed
    assert "trivial" in gate.reason


def test_evaluate_contract_must_pass_tests_enforced(tmp_path: Path) -> None:
    _ = _init_repo(tmp_path)
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "contracts" / "login.contract.yaml").write_text(
        """
must_pass_tests:
  - tests/test_login.py
""",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add contract")
    base = _git(tmp_path, "rev-parse", "HEAD")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("x = 1\n", encoding="utf-8")

    config = Config(test_command="true", ai_tool="echo {prompt}")
    goal = Goal(
        id="G1",
        title="Login",
        status="active",
        contract_file=".ai/contracts/login.contract.yaml",
    )
    outcome, output = evaluate(tmp_path, config, goal, base)
    assert not outcome.success
    assert outcome.classification == "contract-violation"
    assert "must_pass_tests" in (outcome.reason or "")
    assert "ERROR" in output or "not found" in output.lower() or "no tests ran" in output.lower()
