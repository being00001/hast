"""Tests for JSONL rotation utility."""

from __future__ import annotations

import os
import time
from pathlib import Path

from hast.utils.rotation import (
    RotationResult,
    discover_jsonl_files,
    rotate_files,
)


def _make_jsonl(path: Path, size_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * size_bytes, encoding="utf-8")


def test_rotate_no_ai_dir(tmp_path: Path) -> None:
    assert rotate_files(tmp_path) == []


def test_rotate_skips_small_files(tmp_path: Path) -> None:
    _make_jsonl(tmp_path / ".ai" / "feedback" / "notes.jsonl", 100)
    results = rotate_files(tmp_path, max_size_bytes=1024, max_age_days=365)
    assert results == []


def test_rotate_moves_large_file(tmp_path: Path) -> None:
    target = tmp_path / ".ai" / "feedback" / "notes.jsonl"
    _make_jsonl(target, 2000)
    results = rotate_files(tmp_path, max_size_bytes=1000, max_age_days=365)
    assert len(results) == 1
    assert results[0].reason == "size"
    assert not target.exists()
    archive = tmp_path / results[0].archive_path
    assert archive.exists()
    assert archive.parent.name == "archive"


def test_rotate_moves_old_file(tmp_path: Path) -> None:
    target = tmp_path / ".ai" / "feedback" / "notes.jsonl"
    _make_jsonl(target, 100)
    old_time = time.time() - (40 * 86400)
    os.utime(target, (old_time, old_time))
    results = rotate_files(tmp_path, max_size_bytes=5 * 1024 * 1024, max_age_days=30)
    assert len(results) == 1
    assert results[0].reason == "age"
    assert not target.exists()


def test_rotate_dry_run_does_not_move(tmp_path: Path) -> None:
    target = tmp_path / ".ai" / "feedback" / "notes.jsonl"
    _make_jsonl(target, 2000)
    results = rotate_files(tmp_path, max_size_bytes=1000, dry_run=True)
    assert len(results) == 1
    assert target.exists()


def test_discover_jsonl_files(tmp_path: Path) -> None:
    ai = tmp_path / ".ai"
    _make_jsonl(ai / "feedback" / "notes.jsonl", 10)
    _make_jsonl(ai / "events" / "events.jsonl", 10)
    _make_jsonl(ai / "runs" / "run1" / "evidence.jsonl", 10)
    found = discover_jsonl_files(ai)
    names = [p.name for p in found]
    assert "notes.jsonl" in names
    assert "events.jsonl" in names
    assert "evidence.jsonl" in names


def test_rotate_archive_naming(tmp_path: Path) -> None:
    target = tmp_path / ".ai" / "feedback" / "notes.jsonl"
    _make_jsonl(target, 2000)
    results = rotate_files(tmp_path, max_size_bytes=1000, max_age_days=365)
    assert len(results) == 1
    archive_name = Path(results[0].archive_path).name
    assert archive_name.startswith("feedback__notes.")
    assert archive_name.endswith(".jsonl")
