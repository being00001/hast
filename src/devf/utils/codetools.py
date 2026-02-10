"""AST-based code analysis utilities."""

from __future__ import annotations

import ast
from pathlib import Path

_SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", ".tox", ".mypy_cache"}


def _iter_py_files(root: Path) -> list[Path]:
    """Find .py files under *root*, skipping common non-project dirs."""
    result: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        result.append(path)
    return result


def code_structure_snapshot(root: Path) -> str:
    """Return a compact overview of classes/functions per Python file."""
    py_files = _iter_py_files(root)
    if not py_files:
        return ""

    lines: list[str] = []
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        total_lines = len(source.splitlines())
        rel = _relpath(path, root)
        entries: list[str] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                entries.append(f"class {node.name} ({len(methods)} methods)")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entries.append(f"fn {node.name}()")

        if entries:
            lines.append(f"{rel} ({total_lines} lines)")
            lines.append("  " + ", ".join(entries))

    return "\n".join(lines)


def build_import_map(root: Path) -> dict[str, list[str]]:
    """Build reverse import map: module_name -> [files that import it].

    Only tracks imports that resolve to files under *root*.
    """
    py_files = _iter_py_files(root)
    # Build set of known project modules
    known_modules: set[str] = set()
    file_for_module: dict[str, str] = {}
    for path in py_files:
        rel = _relpath(path, root)
        module = _file_to_module(rel)
        if module:
            known_modules.add(module)
            file_for_module[module] = rel

    reverse_map: dict[str, list[str]] = {}
    for path in py_files:
        rel = _relpath(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            imported_module: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = alias.name
                    _record_import(imported_module, rel, known_modules, reverse_map)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_module = node.module
                _record_import(imported_module, rel, known_modules, reverse_map)

    return reverse_map


def _record_import(
    module: str, importing_file: str, known: set[str], result: dict[str, list[str]]
) -> None:
    """Record an import if the module is a known project module."""
    # Try exact match and prefix matches
    for known_mod in known:
        if module == known_mod or module.startswith(known_mod + ".") or known_mod.startswith(module + "."):
            if known_mod not in result:
                result[known_mod] = []
            if importing_file not in result[known_mod]:
                result[known_mod].append(importing_file)


def impact_analysis(changed_files: list[str], root: Path) -> str:
    """For each changed .py file, show which project files import it."""
    import_map = build_import_map(root)
    lines: list[str] = []
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        module = _file_to_module(f)
        if not module:
            continue
        importers = import_map.get(module, [])
        # Exclude self-imports
        importers = [imp for imp in importers if imp != f]
        if importers:
            lines.append(f"{f} -> imported by: {', '.join(sorted(importers))}")
    return "\n".join(lines)


def complexity_check(
    files: list[str],
    root: Path,
    *,
    max_file_lines: int = 400,
    max_methods: int = 15,
    max_init_attrs: int = 20,
) -> list[str]:
    """Check changed files for complexity threshold violations."""
    warnings: list[str] = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        path = root / rel
        if not path.exists():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        total_lines = len(source.splitlines())
        if total_lines > max_file_lines:
            warnings.append(f"{rel}: {total_lines} lines (limit {max_file_lines})")

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if len(methods) > max_methods:
                    warnings.append(
                        f"{rel}: class {node.name} has {len(methods)} methods "
                        f"(limit {max_methods})"
                    )
                # Count self.X assignments in __init__
                for m in methods:
                    if m.name == "__init__":
                        attrs = _count_init_attrs(m)
                        if attrs > max_init_attrs:
                            warnings.append(
                                f"{rel}: {node.name}.__init__ has {attrs} attributes "
                                f"(limit {max_init_attrs})"
                            )
    return warnings


def _count_init_attrs(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count unique self.X assignments in an __init__ method."""
    attrs: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    attrs.add(target.attr)
    return len(attrs)


def _file_to_module(rel_path: str) -> str | None:
    """Convert relative file path to dotted module name."""
    if not rel_path.endswith(".py"):
        return None
    parts = rel_path.replace("/", ".").replace("\\", ".")
    if parts.endswith(".__init__.py"):
        parts = parts[: -len(".__init__.py")]
    elif parts.endswith(".py"):
        parts = parts[: -len(".py")]
    return parts or None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
