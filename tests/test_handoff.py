"""Tests for handoff parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import textwrap

import pytest

from hast.core.errors import HastError
from hast.core.handoff import (
    extract_section_lines,
    find_latest_handoff,
    parse_context_files,
    parse_handoff,
)


SAMPLE_HANDOFF = textwrap.dedent("""\
    ---
    timestamp: "2026-02-09T14:30:00+09:00"
    status: complete
    goal_id: M1.1
    ---

    ## Done
    core/auth.py: Login 구현

    ## Key Decisions
    JWT 사용

    ## Changed Files
    core/auth.py (수정)

    ## Next
    M1.2 — Session
    src/session.py 생성

    ## Context Files
    1. core/auth.py
    2. src/session.py
""")


def _write_handoff(path: Path, content: str = SAMPLE_HANDOFF) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_handoff(tmp_path: Path) -> None:
    p = _write_handoff(tmp_path / "2026-02-09_143000.md")
    h = parse_handoff(p)
    assert h.status == "complete"
    assert h.goal_id == "M1.1"
    assert h.timestamp.year == 2026
    assert "Done" in h.sections
    assert "Next" in h.sections


def test_parse_handoff_strips_dashes(tmp_path: Path) -> None:
    p = _write_handoff(tmp_path / "2026-02-09_143000.md")
    h = parse_handoff(p)
    done_lines = h.sections["Done"]
    assert done_lines[0] == "core/auth.py: Login 구현"
    assert not done_lines[0].startswith("- ")


def test_parse_handoff_missing_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(HastError, match="frontmatter"):
        parse_handoff(p)


def test_parse_handoff_missing_timestamp(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(textwrap.dedent("""\
        ---
        status: complete
        goal_id: X
        ---
        body
    """), encoding="utf-8")
    with pytest.raises(HastError, match="timestamp"):
        parse_handoff(p)


def test_parse_handoff_missing_timezone(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(textwrap.dedent("""\
        ---
        timestamp: "2026-02-09T14:30:00"
        status: complete
        goal_id: X
        ---
        body
    """), encoding="utf-8")
    with pytest.raises(HastError, match="timezone"):
        parse_handoff(p)


def test_parse_handoff_unquoted_timestamp(tmp_path: Path) -> None:
    """YAML auto-parses unquoted ISO timestamps as datetime objects."""
    p = tmp_path / "2026-02-10_120000.md"
    p.write_text(textwrap.dedent("""\
        ---
        timestamp: 2026-02-10T12:00:00+09:00
        status: complete
        goal_id: F1.3
        ---

        ## Done
        Added error handling

        ## Key Decisions
        Reused ValueError

        ## Changed Files
        src/calc.py (modified)

        ## Next
        No further goals

        ## Context Files
        1. src/calc.py
    """), encoding="utf-8")
    h = parse_handoff(p)
    assert h.status == "complete"
    assert h.goal_id == "F1.3"
    assert h.timestamp.year == 2026


def test_parse_handoff_invalid_status(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(textwrap.dedent("""\
        ---
        timestamp: "2026-02-09T14:30:00+09:00"
        status: unknown
        goal_id: X
        ---
        body
    """), encoding="utf-8")
    with pytest.raises(HastError, match="status"):
        parse_handoff(p)


def test_find_latest_handoff(tmp_path: Path) -> None:
    d = tmp_path / "handoffs"
    d.mkdir()
    _write_handoff(d / "2026-02-09_140000.md")
    _write_handoff(
        d / "2026-02-09_150000.md",
        SAMPLE_HANDOFF.replace("14:30:00", "15:00:00"),
    )
    h = find_latest_handoff(d, since=None)
    assert h is not None
    assert "150000" in h.path.name


def test_find_latest_handoff_with_since(tmp_path: Path) -> None:
    d = tmp_path / "handoffs"
    d.mkdir()
    _write_handoff(d / "2026-02-09_143000.md")
    # since is in the future relative to file mtime → filtered out
    since = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    h = find_latest_handoff(d, since=since)
    assert h is None


def test_find_latest_handoff_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "handoffs"
    d.mkdir()
    assert find_latest_handoff(d, since=None) is None


def test_find_latest_handoff_missing_dir(tmp_path: Path) -> None:
    assert find_latest_handoff(tmp_path / "nope", since=None) is None


def test_extract_section_lines_none() -> None:
    assert extract_section_lines(None, "Done") == []


def test_parse_context_files() -> None:
    lines = [
        "1. core/auth.py",
        "2. src/session.py",
    ]
    result = parse_context_files(lines)
    assert result == ["core/auth.py", "src/session.py"]


def test_parse_context_files_dash_format() -> None:
    lines = [
        "- core/auth.py",
        "- src/session.py",
    ]
    result = parse_context_files(lines)
    assert result == ["core/auth.py", "src/session.py"]
