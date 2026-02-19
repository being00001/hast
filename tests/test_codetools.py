"""Tests for AST-based code analysis utilities."""

from __future__ import annotations

from pathlib import Path
import textwrap

from hast.utils.codetools import (
    build_import_map,
    code_structure_snapshot,
    complexity_check,
    impact_analysis,
)


def _write_py(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


# --- code_structure_snapshot ---


def test_snapshot_classes_and_functions(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/foo.py", """\
        class Foo:
            def method_a(self):
                pass
            def method_b(self):
                pass

        def helper():
            pass
    """)
    result = code_structure_snapshot(tmp_path)
    assert "src/foo.py" in result
    assert "class Foo (2 methods)" in result
    assert "fn helper()" in result


def test_snapshot_skips_venv(tmp_path: Path) -> None:
    _write_py(tmp_path, "venv/lib/pkg.py", """\
        class Hidden:
            pass
    """)
    _write_py(tmp_path, "src/app.py", """\
        def main():
            pass
    """)
    result = code_structure_snapshot(tmp_path)
    assert "Hidden" not in result
    assert "fn main()" in result


def test_snapshot_empty_project(tmp_path: Path) -> None:
    result = code_structure_snapshot(tmp_path)
    assert result == ""


def test_snapshot_ignores_syntax_error(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def (broken:", encoding="utf-8")
    _write_py(tmp_path, "good.py", """\
        def ok():
            pass
    """)
    result = code_structure_snapshot(tmp_path)
    assert "fn ok()" in result




def test_snapshot_skips_tests(tmp_path: Path) -> None:
    _write_py(tmp_path, "tests/test_foo.py", """\
        def test_something():
            pass
    """)
    _write_py(tmp_path, "src/app.py", """\
        def main():
            pass
    """)
    result = code_structure_snapshot(tmp_path)
    assert "test_foo" not in result
    assert "fn main()" in result


def test_snapshot_dataclass_fields(tmp_path: Path) -> None:
    _write_py(tmp_path, "src/models.py", """\
        from dataclasses import dataclass

        @dataclass
        class Config:
            name: str
            value: int
            active: bool = True

        @dataclass(frozen=True)
        class Point:
            x: float
            y: float
    """)
    result = code_structure_snapshot(tmp_path)
    assert "class Config (3 fields)" in result
    assert "class Point (2 fields)" in result


# --- build_import_map ---


def test_import_map_basic(tmp_path: Path) -> None:
    _write_py(tmp_path, "core/__init__.py", "")
    _write_py(tmp_path, "core/auth.py", """\
        def login():
            pass
    """)
    _write_py(tmp_path, "core/session.py", """\
        from core.auth import login
    """)
    reverse_map, _ = build_import_map(tmp_path)
    assert "core.auth" in reverse_map
    assert "core/session.py" in reverse_map["core.auth"]


def test_import_map_no_external(tmp_path: Path) -> None:
    """Standard library / third-party imports should not appear."""
    _write_py(tmp_path, "app.py", """\
        import os
        import json
        from pathlib import Path
    """)
    reverse_map, _ = build_import_map(tmp_path)
    assert "os" not in reverse_map
    assert "json" not in reverse_map
    assert "pathlib" not in reverse_map


# --- impact_analysis ---


def test_impact_basic(tmp_path: Path) -> None:
    _write_py(tmp_path, "core/__init__.py", "")
    _write_py(tmp_path, "core/auth.py", """\
        def login():
            pass
    """)
    _write_py(tmp_path, "core/api.py", """\
        from core.auth import login
    """)
    _write_py(tmp_path, "core/views.py", """\
        from core.auth import login
    """)
    result = impact_analysis(["core/auth.py"], tmp_path)
    assert "core/auth.py -> imported by:" in result
    assert "core/api.py" in result
    assert "core/views.py" in result


def test_impact_no_importers(tmp_path: Path) -> None:
    _write_py(tmp_path, "standalone.py", """\
        def isolated():
            pass
    """)
    result = impact_analysis(["standalone.py"], tmp_path)
    assert result == ""


def test_impact_ignores_non_python(tmp_path: Path) -> None:
    result = impact_analysis(["README.md", "config.yaml"], tmp_path)
    assert result == ""


# --- complexity_check ---


def test_complexity_file_too_long(tmp_path: Path) -> None:
    lines = "\n".join(f"x{i} = {i}" for i in range(500))
    (tmp_path / "big.py").write_text(lines, encoding="utf-8")
    warnings = complexity_check(["big.py"], tmp_path, max_file_lines=400)
    assert any("500 lines" in w for w in warnings)


def test_complexity_within_limits(tmp_path: Path) -> None:
    _write_py(tmp_path, "small.py", """\
        def short():
            pass
    """)
    warnings = complexity_check(["small.py"], tmp_path)
    assert warnings == []


def test_complexity_too_many_methods(tmp_path: Path) -> None:
    methods = "\n".join(f"    def method_{i}(self): pass" for i in range(20))
    code = f"class Big:\n{methods}\n"
    (tmp_path / "big_class.py").write_text(code, encoding="utf-8")
    warnings = complexity_check(["big_class.py"], tmp_path, max_methods=15)
    assert any("20 methods" in w for w in warnings)


def test_complexity_too_many_init_attrs(tmp_path: Path) -> None:
    attrs = "\n".join(f"        self.attr_{i} = {i}" for i in range(25))
    code = f"class Wide:\n    def __init__(self):\n{attrs}\n"
    (tmp_path / "wide.py").write_text(code, encoding="utf-8")
    warnings = complexity_check(["wide.py"], tmp_path, max_init_attrs=20)
    assert any("25 attributes" in w for w in warnings)


def test_complexity_skips_missing_files(tmp_path: Path) -> None:
    warnings = complexity_check(["nonexistent.py"], tmp_path)
    assert warnings == []
