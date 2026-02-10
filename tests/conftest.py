"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

import pytest


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal git repo with .ai/ initialized."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )

    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    (ai_dir / "sessions").mkdir()
    (ai_dir / "handoffs").mkdir()

    (ai_dir / "config.yaml").write_text(
        textwrap.dedent("""\
            test_command: "echo ok"
            ai_tool: "echo {prompt}"
        """),
        encoding="utf-8",
    )
    (ai_dir / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai_dir / "rules.md").write_text(
        textwrap.dedent("""\
            # Rules
            ## Verification
            - Run tests before handoff
        """),
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )

    return tmp_path
