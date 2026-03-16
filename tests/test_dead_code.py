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


from pathlib import Path
import textwrap

from hast.utils.codetools import find_dead_code


def _write_py(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_unused_import_detected(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/app.py", """\
        import os
        from pathlib import Path

        def main():
            return Path(".")
    """)
    results = find_dead_code(tmp_path)
    unused = [e for e in results if e.kind == "import"]
    assert any(e.symbol == "os" and e.file == "src/app.py" for e in unused)


def test_used_import_not_flagged(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/app.py", """\
        from pathlib import Path

        def main():
            return Path(".")
    """)
    results = find_dead_code(tmp_path)
    unused_imports = [e for e in results if e.kind == "import"]
    assert not any(e.symbol == "Path" for e in unused_imports)


def test_import_used_in_type_annotation(tmp_path: Path) -> None:
    """Type annotations count as usage."""
    _write_py(tmp_path, "src/app.py", """\
        from pathlib import Path

        def main() -> Path:
            return Path(".")
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "Path" for e in results)


def test_star_import_not_flagged(tmp_path: Path) -> None:
    """Star imports are ambiguous — skip them."""
    _write_py(tmp_path, "src/app.py", """\
        from os.path import *

        def main():
            pass
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.kind == "import" and e.file == "src/app.py" for e in results)


def test_aliased_import(tmp_path: Path) -> None:
    """Aliased imports: check alias name, not original."""
    _write_py(tmp_path, "src/app.py", """\
        import os as operating_system

        def main():
            return operating_system.getcwd()
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "operating_system" for e in results)


def test_empty_project(tmp_path: Path) -> None:
    """Empty project returns empty list."""
    results = find_dead_code(tmp_path)
    assert results == []


def test_syntax_error_file_skipped(tmp_path: Path) -> None:
    """Files with syntax errors are gracefully skipped."""
    (tmp_path / "bad.py").write_text("def (broken:", encoding="utf-8")
    _write_py(tmp_path, "good.py", """\
        import os

        def main():
            pass
    """)
    results = find_dead_code(tmp_path)
    assert any(e.symbol == "os" for e in results)
