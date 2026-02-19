"""Tests for attempt logging."""

from __future__ import annotations

from pathlib import Path

from hast.core.attempt import (
    DIFF_MAX_CHARS,
    TEST_OUTPUT_MAX_LINES,
    clear_attempts,
    load_attempts,
    save_attempt,
)


def test_save_and_load(tmp_path: Path) -> None:
    save_attempt(
        tmp_path, "G1", 1, "failed", "tests failed",
        "src/a.py | 3 +++", "FAILED test_foo",
        diff="--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-old\n+new",
    )
    logs = load_attempts(tmp_path, "G1")
    assert len(logs) == 1
    assert logs[0].attempt == 1
    assert logs[0].classification == "failed"
    assert logs[0].diff.startswith("--- a/src/a.py")


def test_load_empty(tmp_path: Path) -> None:
    assert load_attempts(tmp_path, "G1") == []


def test_save_multiple_sorted(tmp_path: Path) -> None:
    save_attempt(tmp_path, "G1", 2, "failed", None, "", "err2")
    save_attempt(tmp_path, "G1", 1, "failed", None, "", "err1")
    logs = load_attempts(tmp_path, "G1")
    assert [log.attempt for log in logs] == [1, 2]


def test_clear(tmp_path: Path) -> None:
    save_attempt(tmp_path, "G1", 1, "failed", None, "", "err")
    clear_attempts(tmp_path, "G1")
    assert load_attempts(tmp_path, "G1") == []


def test_clear_nonexistent(tmp_path: Path) -> None:
    clear_attempts(tmp_path, "G1")  # should not raise


def test_diff_truncated(tmp_path: Path) -> None:
    big_diff = "x" * (DIFF_MAX_CHARS + 1000)
    save_attempt(tmp_path, "G1", 1, "failed", None, "", "", diff=big_diff)
    logs = load_attempts(tmp_path, "G1")
    assert len(logs[0].diff) < len(big_diff)
    assert "truncated" in logs[0].diff


def test_test_output_truncated(tmp_path: Path) -> None:
    big_output = "\n".join(f"line {i}" for i in range(100))
    save_attempt(tmp_path, "G1", 1, "failed", None, "", big_output)
    logs = load_attempts(tmp_path, "G1")
    saved_lines = logs[0].test_output.splitlines()
    assert len(saved_lines) <= TEST_OUTPUT_MAX_LINES


def test_backward_compat_no_diff(tmp_path: Path) -> None:
    """Loading attempts saved without diff field should still work."""
    import yaml
    attempt_dir = tmp_path / ".ai" / "attempts" / "G1"
    attempt_dir.mkdir(parents=True)
    data = {
        "attempt": 1,
        "classification": "failed",
        "reason": "tests failed",
        "diff_stat": "1 file changed",
        "test_output": "FAILED",
    }
    (attempt_dir / "attempt_1.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8",
    )
    logs = load_attempts(tmp_path, "G1")
    assert len(logs) == 1
    assert logs[0].diff == ""
