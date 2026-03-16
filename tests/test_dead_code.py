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


def test_unused_function_detected(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/app.py", """\
        def used():
            return 1

        def unused():
            return 2

        result = used()
    """)
    results = find_dead_code(tmp_path)
    assert any(e.symbol == "unused" and e.kind == "function" for e in results)
    assert not any(e.symbol == "used" and e.kind == "function" for e in results)


def test_unused_class_detected(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/app.py", """\
        class Used:
            pass

        class Unused:
            pass

        obj = Used()
    """)
    results = find_dead_code(tmp_path)
    assert any(e.symbol == "Unused" and e.kind == "class" for e in results)
    assert not any(e.symbol == "Used" for e in results)


def test_dunder_names_not_flagged(tmp_path: Path) -> None:
    """__all__, __version__ etc should not be flagged."""
    _write_py(tmp_path, "src/app.py", """\
        __all__ = ["main"]
        __version__ = "1.0"

        def main():
            pass
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol.startswith("__") for e in results)


def test_decorated_function_not_flagged(tmp_path: Path) -> None:
    """Decorated functions may be used via framework — skip them."""
    _write_py(tmp_path, "src/app.py", """\
        def my_decorator(f):
            return f

        @my_decorator
        def handler():
            pass
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "handler" for e in results)


def test_async_function_detected(tmp_path: Path) -> None:
    """async def should be handled the same as def."""
    _write_py(tmp_path, "src/app.py", """\
        async def used():
            return 1

        async def unused():
            return 2

        import asyncio
        asyncio.run(used())
    """)
    results = find_dead_code(tmp_path)
    fns = [e for e in results if e.kind == "function"]
    assert any(e.symbol == "unused" for e in fns)
    assert not any(e.symbol == "used" for e in fns)


def test_single_underscore_private_still_detected(tmp_path: Path) -> None:
    """Single-underscore private functions CAN be dead code."""
    _write_py(tmp_path, "src/app.py", """\
        def _helper():
            return 1

        def public():
            return 2

        result = public()
    """)
    results = find_dead_code(tmp_path)
    assert any(e.symbol == "_helper" and e.confidence == "medium" for e in results)
