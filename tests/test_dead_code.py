"""Tests for dead code detection."""

from __future__ import annotations

from hast.core.result import DeadCodeEntry


def test_dead_code_entry_creation():
    entry = DeadCodeEntry(
        file="src/app.py",
        symbol="unused_func",
        kind="function",
        confidence="high",
    )
    assert entry.file == "src/app.py"
    assert entry.symbol == "unused_func"
    assert entry.kind == "function"
    assert entry.confidence == "high"


def test_dead_code_entry_default_confidence():
    entry = DeadCodeEntry(file="a.py", symbol="x", kind="import")
    assert entry.confidence == "high"
