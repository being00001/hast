from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Temporary git repo with one initial commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("tmp project\n", encoding="utf-8")
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    (ai_dir / "config.yaml").write_text(
        'test_command: "echo ok"\nai_tool: "echo {prompt}"\n',
        encoding="utf-8",
    )
    (ai_dir / "goals.yaml").write_text("goals: []\n", encoding="utf-8")
    (ai_dir / "rules.md").write_text("# rules\n", encoding="utf-8")
    (ai_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (ai_dir / "handoffs").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path
