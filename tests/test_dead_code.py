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


def test_cross_module_used_not_flagged(tmp_path: Path) -> None:
    """Function imported by another module is not dead."""
    _write_py(tmp_path, "src/lib/__init__.py", "")
    _write_py(tmp_path, "src/lib/utils.py", """\
        def helper():
            return 1
    """)
    _write_py(tmp_path, "src/app.py", """\
        from lib.utils import helper

        result = helper()
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "helper" and e.kind == "function" for e in results)


def test_cross_module_unused_flagged(tmp_path: Path) -> None:
    """Function not imported anywhere is dead."""
    _write_py(tmp_path, "src/lib/__init__.py", "")
    _write_py(tmp_path, "src/lib/utils.py", """\
        def helper():
            return 1

        def orphan():
            return 2
    """)
    _write_py(tmp_path, "src/app.py", """\
        from lib.utils import helper

        result = helper()
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "helper" for e in results)
    assert any(e.symbol == "orphan" and e.kind == "function" for e in results)


def test_init_reexport_not_flagged(tmp_path: Path) -> None:
    """Symbols re-exported via __init__.py are not dead."""
    _write_py(tmp_path, "src/lib/__init__.py", """\
        from lib.utils import helper
    """)
    _write_py(tmp_path, "src/lib/utils.py", """\
        def helper():
            return 1
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "helper" and e.kind == "function" for e in results)


def test_all_export_not_flagged(tmp_path: Path) -> None:
    """Symbols listed in __all__ are not dead."""
    _write_py(tmp_path, "src/app.py", """\
        __all__ = ["public_func"]

        def public_func():
            return 1
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "public_func" for e in results)


def test_same_name_different_module_not_confused(tmp_path: Path) -> None:
    """Two modules with same-named function: only the unused one is flagged."""
    _write_py(tmp_path, "src/mod_a/__init__.py", "")
    _write_py(tmp_path, "src/mod_a/utils.py", """\
        def process():
            return "a"
    """)
    _write_py(tmp_path, "src/mod_b/__init__.py", "")
    _write_py(tmp_path, "src/mod_b/utils.py", """\
        def process():
            return "b"
    """)
    _write_py(tmp_path, "src/app.py", """\
        from mod_a.utils import process

        result = process()
    """)
    results = find_dead_code(tmp_path)
    dead_process = [e for e in results if e.symbol == "process" and e.kind == "function"]
    assert len(dead_process) == 1
    assert dead_process[0].file == "src/mod_b/utils.py"


def test_init_reexport_import_not_flagged(tmp_path: Path) -> None:
    """Imports in __init__.py are re-exports — never flag them as unused."""
    _write_py(tmp_path, "src/core/__init__.py", """\
        from .being import Being
        from .config import Config
    """)
    _write_py(tmp_path, "src/core/being.py", """\
        class Being:
            pass
    """)
    _write_py(tmp_path, "src/core/config.py", """\
        class Config:
            pass
    """)
    results = find_dead_code(tmp_path)
    init_imports = [e for e in results if e.kind == "import" and "__init__" in e.file]
    assert init_imports == [], f"__init__.py imports should not be flagged: {init_imports}"


def test_init_unused_function_still_flagged(tmp_path: Path) -> None:
    """Functions defined in __init__.py CAN be dead code (imports are skipped, not defs)."""
    _write_py(tmp_path, "src/core/__init__.py", """\
        from .being import Being

        def unused_helper():
            return 1
    """)
    _write_py(tmp_path, "src/core/being.py", """\
        class Being:
            pass
    """)
    results = find_dead_code(tmp_path)
    # Import should NOT be flagged
    assert not any(e.symbol == "Being" and e.kind == "import" for e in results)
    # Function CAN be flagged (it's not an import re-export)
    assert any(e.symbol == "unused_helper" and e.kind == "function" for e in results)


# --- FP fixes: __future__, tests/, dotted imports ---


def test_future_import_not_flagged(tmp_path: Path) -> None:
    """from __future__ import annotations is a compiler directive, never flag."""
    _write_py(tmp_path, "src/app.py", """\
        from __future__ import annotations

        def main() -> str:
            return "hello"
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "annotations" for e in results)


def test_future_import_mixed(tmp_path: Path) -> None:
    """__future__ skipped but real unused import still caught."""
    _write_py(tmp_path, "src/app.py", """\
        from __future__ import annotations
        import os

        def main() -> str:
            return "hello"
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "annotations" for e in results)
    assert any(e.symbol == "os" and e.kind == "import" for e in results)


def test_test_files_excluded(tmp_path: Path) -> None:
    """Files in tests/ directory are excluded from dead code analysis."""
    _write_py(tmp_path, "src/app.py", """\
        def main():
            return 1
    """)
    _write_py(tmp_path, "tests/test_app.py", """\
        from app import main

        def test_main():
            assert main() == 1

        def helper():
            pass
    """)
    results = find_dead_code(tmp_path)
    # test files should not appear in results at all
    assert not any("tests/" in e.file for e in results)


def test_dotted_import_used(tmp_path: Path) -> None:
    """import importlib.util — usage via importlib.util.X is not unused."""
    _write_py(tmp_path, "src/app.py", """\
        import importlib.util

        def check(name):
            return importlib.util.find_spec(name)
    """)
    results = find_dead_code(tmp_path)
    assert not any(e.symbol == "importlib.util" for e in results)
    assert not any(e.symbol == "importlib" for e in results)


def test_dotted_import_unused(tmp_path: Path) -> None:
    """import os.path — actually unused should still be caught."""
    _write_py(tmp_path, "src/app.py", """\
        import os.path

        def main():
            return 1
    """)
    results = find_dead_code(tmp_path)
    assert any(e.symbol == "os" and e.kind == "import" for e in results)
