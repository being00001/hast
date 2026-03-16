"""AST-based code analysis utilities."""

from __future__ import annotations

import ast
from pathlib import Path

from hast.core.result import DeadCodeEntry

_SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", ".tox", ".mypy_cache"}


def _iter_py_files(root: Path, *, skip_tests: bool = False) -> list[Path]:
    """Find .py files under *root*, skipping common non-project dirs."""
    skip = _SKIP_DIRS | {"tests"} if skip_tests else _SKIP_DIRS
    result: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in skip for part in path.parts):
            continue
        result.append(path)
    return result



def _is_dataclass(node: ast.ClassDef) -> bool:
    """Check if a class has the @dataclass decorator."""
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "dataclass":
            return True
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "dataclass":
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == "dataclass":
            return True
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr == "dataclass":
            return True
    return False


def _count_dataclass_fields(node: ast.ClassDef) -> int:
    """Count annotated assignments (fields) in a dataclass body."""
    return sum(1 for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name))


def code_structure_snapshot(root: Path) -> str:
    """Return a compact overview of classes/functions per Python file."""
    py_files = _iter_py_files(root, skip_tests=True)
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
                if _is_dataclass(node):
                    fields = _count_dataclass_fields(node)
                    entries.append(f"class {node.name} ({fields} fields)")
                else:
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


def build_import_map(root: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Build import maps.

    Returns:
        (reverse_map, module_to_file)
        reverse_map: module_name -> [files that import it]
        module_to_file: module_name -> file_path
    """
    py_files = _iter_py_files(root)
    # Build set of known project modules
    known_modules: set[str] = set()
    module_to_file: dict[str, str] = {}
    for path in py_files:
        rel = _relpath(path, root)
        module = file_to_module(rel)
        if module:
            known_modules.add(module)
            module_to_file[module] = rel

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

    return reverse_map, module_to_file


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
    import_map, _ = build_import_map(root)
    lines: list[str] = []
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        module = file_to_module(f)
        if not module:
            continue
        importers = import_map.get(module, [])
        # Exclude self-imports
        importers = [imp for imp in importers if imp != f]
        if importers:
            lines.append(f"{f} -> imported by: {', '.join(sorted(importers))}")
    return "\n".join(lines)


def find_related_tests(root: Path, target_files: list[str]) -> list[str]:
    """Find test files that import any of the target_files."""
    import_map, _ = build_import_map(root)
    related_tests = set()

    for f in target_files:
        module = file_to_module(f)
        if not module:
            continue

        importers = import_map.get(module, [])
        for imp in importers:
            # A file is a test if it's in tests/ dir or starts/ends with test_
            p = Path(imp)
            if "tests" in p.parts or p.name.startswith("test_") or p.name.endswith("_test.py"):
                if imp != f:  # Avoid self-reference
                    related_tests.add(imp)

    return sorted(list(related_tests))


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


def file_to_module(rel_path: str) -> str | None:
    """Convert relative file path to dotted module name."""
    if not rel_path.endswith(".py"):
        return None
    
    # Handle common src/ layout
    if rel_path.startswith("src/"):
        rel_path = rel_path[4:]
    elif rel_path.startswith("src\\"):
        rel_path = rel_path[4:]
        
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


def find_dead_code(
    root: Path,
    symbol_map: "SymbolMap | None" = None,
) -> list[DeadCodeEntry]:
    """Detect unused imports, functions, and classes via static AST analysis.

    Args:
        root: Project root directory to scan.
        symbol_map: Optional pre-built SymbolMap (currently unused, reserved for v2).

    Limitations: does not detect dynamic references (getattr, plugin registries).
    """
    entries: list[DeadCodeEntry] = []
    py_files = _iter_py_files(root)

    for path in py_files:
        rel = _relpath(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        entries.extend(_find_unused_imports(tree, rel))

    return entries


def _find_unused_imports(tree: ast.Module, file: str) -> list[DeadCodeEntry]:
    """Find imports whose bound names are never referenced in the file."""
    imported_names: dict[str, ast.AST] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = node
        elif isinstance(node, ast.ImportFrom):
            if node.names and node.names[0].name == "*":
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = node

    if not imported_names:
        return []

    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_names:
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in imported_names:
                used_names.add(node.value.id)

    entries: list[DeadCodeEntry] = []
    for name in sorted(imported_names.keys() - used_names):
        entries.append(DeadCodeEntry(file=file, symbol=name, kind="import"))
    return entries
