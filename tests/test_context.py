"""Tests for context assembly."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

from devf.core.context import build_context, build_context_data, find_root, render_context, ContextData
from devf.core.config import Config
from devf.core.goals import Goal


HANDOFF = textwrap.dedent("""\
    ---
    timestamp: "2026-02-09T14:30:00+09:00"
    status: complete
    goal_id: M1.1
    ---

    ## Done
    src/auth.py: Login 구현

    ## Key Decisions
    JWT 사용

    ## Next
    M1.2 — Session
    src/session.py 생성

    ## Context Files
    1. src/auth.py
    2. src/session.py
""")

SESSION_LOG = textwrap.dedent("""\
    ---
    goal_id: M1.1
    status: complete
    base_commit: abc1234
    ---

    ## Changes
    src/auth.py | 15 +++---

    ## Commits
    - abc1234 feat(M1.1): implement login

    ## Test Results
    5 passed, 0 failed
""")


def _setup_project(root: Path) -> None:
    ai = root / ".ai"
    ai.mkdir(parents=True, exist_ok=True)
    (ai / "handoffs").mkdir(exist_ok=True)
    (ai / "sessions").mkdir(exist_ok=True)
    (ai / "config.yaml").write_text(
        'test_command: "echo ok"\nai_tool: "echo {prompt}"\n',
        encoding="utf-8",
    )
    (ai / "goals.yaml").write_text(
        textwrap.dedent("""\
            goals:
              - id: M1
                title: "Auth"
                status: active
                children:
                  - id: M1.1
                    title: "Login"
                    status: done
                  - id: M1.2
                    title: "Session"
                    status: active
        """),
        encoding="utf-8",
    )
    (ai / "rules.md").write_text("# Rules\n- Run tests\n", encoding="utf-8")
    (ai / "handoffs" / "2026-02-09_143000.md").write_text(HANDOFF, encoding="utf-8")


def _setup_project_with_session(root: Path) -> None:
    """Set up project with session log (no handoffs)."""
    _setup_project(root)
    # Remove the handoff
    (root / ".ai" / "handoffs" / "2026-02-09_143000.md").unlink()
    # Add a session log
    (root / ".ai" / "sessions" / "2026-02-10_120000.md").write_text(
        SESSION_LOG, encoding="utf-8",
    )


# --- Session log tests (primary path) ---


def test_build_context_session_log_markdown(tmp_path: Path) -> None:
    _setup_project_with_session(tmp_path)
    output = build_context(tmp_path, "markdown")
    assert "# Session Context" in output
    assert "M1.2" in output
    assert "feat(M1.1): implement login" in output


def test_build_context_session_log_plain(tmp_path: Path) -> None:
    _setup_project_with_session(tmp_path)
    output = build_context(tmp_path, "plain")
    assert "SESSION CONTEXT" in output
    assert "LAST COMMIT: feat(M1.1): implement login" in output
    assert "TESTS: 5 passed, 0 failed" in output


def test_build_context_session_log_json(tmp_path: Path) -> None:
    _setup_project_with_session(tmp_path)
    output = build_context(tmp_path, "json")
    data = json.loads(output)
    assert data["previous_session"]["source"] == "session_log"
    assert data["previous_session"]["goal_id"] == "M1.1"
    assert data["previous_session"]["last_commit"] == "feat(M1.1): implement login"
    assert "src/auth.py" in data["context_files"]


def test_build_context_session_log_context_files(tmp_path: Path) -> None:
    """Session log extracts file paths from diff --stat."""
    _setup_project_with_session(tmp_path)
    output = build_context(tmp_path, "json")
    data = json.loads(output)
    assert "src/auth.py" in data["context_files"]


# --- Handoff fallback tests ---


def test_build_context_handoff_fallback_markdown(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    # No session log, should fall back to handoff
    output = build_context(tmp_path, "markdown")
    assert "# Session Context" in output
    assert "M1.2" in output
    assert "Session" in output


def test_build_context_handoff_fallback_plain(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    output = build_context(tmp_path, "plain")
    assert "SESSION CONTEXT" in output
    assert "M1.2" in output


def test_build_context_handoff_fallback_json(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    output = build_context(tmp_path, "json")
    data = json.loads(output)
    assert data["previous_session"]["source"] == "handoff"
    assert data["current_goal"]["id"] == "M1.2"
    assert data["previous_session"]["status"] == "complete"
    assert len(data["context_files"]) == 2


def test_build_context_json_preserves_unicode(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    output = build_context(tmp_path, "json")
    assert "구현" in output
    assert "\\u" not in output


# --- Session log takes priority over handoff ---


def test_session_log_takes_priority(tmp_path: Path) -> None:
    """When both session log and handoff exist, session log wins."""
    _setup_project(tmp_path)
    (tmp_path / ".ai" / "sessions" / "2026-02-10_120000.md").write_text(
        SESSION_LOG, encoding="utf-8",
    )
    output = build_context(tmp_path, "json")
    data = json.loads(output)
    assert data["previous_session"]["source"] == "session_log"


# --- Edge cases ---


def test_build_context_no_handoff_no_session(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    (tmp_path / ".ai" / "handoffs" / "2026-02-09_143000.md").unlink()
    output = build_context(tmp_path, "markdown")
    assert "None" in output
    assert "M1.2" in output


def test_build_context_no_goals(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (tmp_path / ".ai" / "handoffs" / "2026-02-09_143000.md").unlink()
    output = build_context(tmp_path, "markdown")
    assert "# Session Context" in output


def test_build_context_goal_override(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    override = Goal(id="M1.1", title="Login", status="active")
    output = build_context(tmp_path, "markdown", goal_override=override)
    assert "M1.1" in output
    assert "Login" in output


def test_build_context_goal_override_task_uses_goal(tmp_path: Path) -> None:
    """When goal_override is set, YOUR TASK should show the override goal, not the handoff Next."""
    _setup_project(tmp_path)
    override = Goal(id="M1.3", title="Edge Tests", status="active")
    output = build_context(tmp_path, "plain")
    # Without override: task comes from handoff Next (M1.2 — Session)
    assert "M1.2" in output

    output_override = build_context(tmp_path, "plain", goal_override=override)
    # With override: task should say M1.3
    assert "M1.3 — Edge Tests" in output_override
    # Should NOT contain the handoff's Next task
    assert "src/session.py" not in output_override.split("YOUR TASK")[1].split("CONTEXT FILES")[0]


def test_build_context_task_no_double_dash(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    output = build_context(tmp_path, "markdown")
    assert "- - " not in output


def test_context_max_bytes(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    output = build_context(tmp_path, "plain", max_context_bytes=100)
    assert len(output.encode("utf-8")) > 0


def test_find_root(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    sub = tmp_path / "sub" / "dir"
    sub.mkdir(parents=True)
    assert find_root(sub) == tmp_path


def test_render_context_unknown_format() -> None:
    from devf.core.context import ContextData
    data = ContextData(
        current_goal=None,
        previous_session=None,
        task=[],
        context_files=[],
        rules=[],
    )
    import pytest
    with pytest.raises(Exception):
        render_context(data, "xml")


# --- git_summary and code_overview tests ---


def test_build_context_git_summary(tmp_project: "Path") -> None:
    """Context should include git change summary when in a git repo."""
    from devf.core.context import ContextData
    # tmp_project is a git repo with one commit
    ai = tmp_project / ".ai"
    (ai / "goals.yaml").write_text(
        "goals:\n  - id: G1\n    title: Test\n    status: active\n",
        encoding="utf-8",
    )
    output = build_context(tmp_project, "plain")
    # Should have RECENT CHANGES section with commit info
    assert "RECENT CHANGES" in output
    assert "init" in output  # the initial commit message


def test_build_context_code_overview(tmp_path: Path) -> None:
    """Context should include code structure for Python projects."""
    from devf.core.context import ContextData
    _setup_project(tmp_path)
    # Add a Python file
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "class App:\n    def run(self):\n        pass\n\ndef helper():\n    pass\n",
        encoding="utf-8",
    )
    output = build_context(tmp_path, "markdown")
    assert "Code Overview" in output
    assert "class App" in output
    assert "helper()" in output


def test_build_context_code_overview_plain(tmp_path: Path) -> None:
    """Plain format should include CODE OVERVIEW section."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def action():\n    pass\n", encoding="utf-8")
    output = build_context(tmp_path, "plain")
    assert "CODE OVERVIEW" in output
    assert "action()" in output


def test_context_trim_drops_code_overview(tmp_path: Path) -> None:
    """When context is trimmed, code_overview should be dropped first."""
    from devf.core.context import ContextData, trim_context_data
    data = ContextData(
        current_goal={"id": "G1", "title": "Test", "status": "active", "parent": None},
        previous_session=None,
        task=["do stuff"],
        context_files=["a.py", "b.py"],
        rules=["run tests"],
        git_summary="3 commits since last session:\n  abc init\n  def feat\n  ghi fix",
        code_overview="src/app.py (100 lines)\n  class App (3 methods)",
    )
    trimmed = trim_context_data(data)
    assert trimmed.code_overview == ""
    assert trimmed.git_summary  # git_summary preserved (but may be shortened)


def test_context_json_includes_new_fields(tmp_path: Path) -> None:
    """JSON format should include git_summary and code_overview."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def fn():\n    pass\n", encoding="utf-8")
    output = build_context(tmp_path, "json")
    data = json.loads(output)
    assert "git_summary" in data
    assert "code_overview" in data


# --- notes and acceptance tests ---


def test_build_context_goal_with_notes(tmp_path: Path) -> None:
    """Context should include goal notes when present."""
    _setup_project(tmp_path)
    override = Goal(id="G1", title="Login", status="active", notes="JWT 사용")
    output = build_context(tmp_path, "plain", goal_override=override)
    assert "NOTES: JWT" in output


def test_build_context_goal_with_acceptance_plain(tmp_path: Path) -> None:
    """Plain format should show acceptance criteria."""
    _setup_project(tmp_path)
    override = Goal(
        id="G1", title="Login", status="active",
        acceptance=["pytest passes", "endpoint works"],
    )
    output = build_context(tmp_path, "plain", goal_override=override)
    assert "ACCEPTANCE CRITERIA:" in output
    assert "pytest passes" in output


def test_build_context_goal_with_acceptance_markdown(tmp_path: Path) -> None:
    """Markdown format should show acceptance criteria."""
    _setup_project(tmp_path)
    override = Goal(
        id="G1", title="Login", status="active",
        acceptance=["pytest passes"],
    )
    output = build_context(tmp_path, "markdown", goal_override=override)
    assert "**Acceptance Criteria:**" in output
    assert "pytest passes" in output


def test_build_context_goal_with_acceptance_json(tmp_path: Path) -> None:
    """JSON format should include acceptance in current_goal."""
    _setup_project(tmp_path)
    override = Goal(
        id="G1", title="Login", status="active",
        acceptance=["tests pass"],
    )
    output = build_context(tmp_path, "json", goal_override=override)
    data = json.loads(output)
    assert data["current_goal"]["acceptance"] == ["tests pass"]
    assert data["current_goal"]["notes"] is None


def test_build_context_goal_with_contract_file(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    override = Goal(
        id="G1",
        title="Login",
        status="active",
        contract_file=".ai/contracts/login.contract.yaml",
    )
    output = build_context(tmp_path, "json", goal_override=override)
    data = json.loads(output)
    assert data["current_goal"]["contract_file"] == ".ai/contracts/login.contract.yaml"


def test_build_context_goal_with_decision_file(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    override = Goal(
        id="G1",
        title="Login",
        status="active",
        decision_file=".ai/decisions/login.yaml",
        uncertainty="high",
    )
    output = build_context(tmp_path, "json", goal_override=override)
    data = json.loads(output)
    assert data["current_goal"]["decision_file"] == ".ai/decisions/login.yaml"
    assert data["current_goal"]["uncertainty"] == "high"


# --- file_contents tests ---


def test_pack_includes_file_contents(tmp_path: Path) -> None:
    """Pack format should include actual source code of allowed_changes files."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")

    override = Goal(
        id="G1", title="Login", status="active",
        allowed_changes=["src/auth.py"],
    )
    output = build_context(tmp_path, "pack", goal_override=override)
    assert "<target_files>" in output
    assert 'path="src/auth.py"' in output
    assert "def login():" in output


def test_pack_file_contents_xml_escaped(tmp_path: Path) -> None:
    """Source code with <, >, & should be XML-escaped."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "cmp.py").write_text("x = 1 < 2 and 3 > 1\n", encoding="utf-8")

    override = Goal(
        id="G1", title="Compare", status="active",
        allowed_changes=["src/cmp.py"],
    )
    output = build_context(tmp_path, "pack", goal_override=override)
    assert "&lt;" in output
    assert "&gt;" in output


def test_file_contents_in_json(tmp_path: Path) -> None:
    """JSON format should include file_contents dict."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("x = 1\n", encoding="utf-8")

    override = Goal(
        id="G1", title="Mod", status="active",
        allowed_changes=["src/mod.py"],
    )
    output = build_context(tmp_path, "json", goal_override=override)
    data = json.loads(output)
    assert "file_contents" in data
    assert data["file_contents"] is not None
    assert "src/mod.py" in data["file_contents"]
    assert "x = 1" in data["file_contents"]["src/mod.py"]


def test_file_contents_truncated_large_file(tmp_path: Path) -> None:
    """Large files should be truncated with a marker."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    lines = "\n".join(f"line_{i} = {i}" for i in range(600))
    (src / "big.py").write_text(lines, encoding="utf-8")

    override = Goal(
        id="G1", title="Big", status="active",
        allowed_changes=["src/big.py"],
    )
    output = build_context(tmp_path, "pack", goal_override=override)
    assert "truncated" in output
    assert "600 lines" in output


def test_file_contents_skips_binary(tmp_path: Path) -> None:
    """Binary files should not be included in file_contents."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    (src / "ok.py").write_text("x = 1\n", encoding="utf-8")

    override = Goal(
        id="G1", title="Bin", status="active",
        allowed_changes=["src/data.bin", "src/ok.py"],
    )
    output = build_context(tmp_path, "json", goal_override=override)
    data = json.loads(output)
    fc = data["file_contents"] or {}
    assert "src/data.bin" not in fc
    assert "src/ok.py" in fc


def test_trim_drops_file_contents_first(tmp_path: Path) -> None:
    """When trimmed, file_contents should be dropped before code_overview."""
    from devf.core.context import trim_context_data
    data = ContextData(
        current_goal={"id": "G1", "title": "Test", "status": "active", "parent": None},
        previous_session=None,
        task=["do stuff"],
        context_files=["a.py"],
        rules=["run tests"],
        git_summary="1 commit",
        code_overview="class Foo (2 methods)",
        file_contents={"a.py": "x = 1\n"},
    )
    trimmed = trim_context_data(data)
    assert trimmed.file_contents == {}
    assert trimmed.code_overview == ""  # also dropped in trim_context_data


def test_build_context_file_contents_with_test_files(tmp_path: Path) -> None:
    """test_files should also have their contents included."""
    _setup_project(tmp_path)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_auth.py").write_text(
        "def test_login(): assert True\n", encoding="utf-8",
    )

    override = Goal(
        id="G1", title="Login", status="active",
        allowed_changes=["src/auth.py"],
        test_files=["tests/test_auth.py"],
    )
    output = build_context(tmp_path, "pack", goal_override=override)
    assert "def login():" in output
    assert "def test_login():" in output
