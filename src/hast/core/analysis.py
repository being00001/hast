"""Codebase analysis and symbol mapping."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SymbolMap:
    files: dict[str, FileSummary] = field(default_factory=dict)


@dataclass
class FileSummary:
    classes: list[ClassSummary] = field(default_factory=list)
    functions: list[FunctionSummary] = field(default_factory=list)


@dataclass
class ClassSummary:
    name: str
    methods: list[FunctionSummary] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)


@dataclass
class FunctionSummary:
    name: str
    args: list[str] = field(default_factory=list)
    returns: str | None = None


def build_symbol_map(root: Path, include_files: list[str] | None = None) -> SymbolMap:
    """Scan the codebase and build a map of all symbols."""
    symbol_map = SymbolMap()
    
    # Only scan python files for now
    if include_files is not None:
        files_to_scan = [root / f for f in include_files if (root / f).exists()]
    else:
        files_to_scan = root.rglob("*.py")

    for py_file in files_to_scan:
        if not py_file.name.endswith(".py"):
            continue
        if _is_ignored(py_file, root):
            continue
            
        rel_path = str(py_file.relative_to(root))
        try:
            summary = analyze_python_file(py_file)
            if summary:
                symbol_map.files[rel_path] = summary
        except Exception:  # pylint: disable=broad-except
            continue
            
    return symbol_map


def analyze_python_file(path: Path) -> FileSummary | None:
    """Analyze a single Python file using AST."""
    content = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    summary = FileSummary()
    
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            summary.classes.append(_analyze_class(node))
        elif isinstance(node, ast.FunctionDef):
            summary.functions.append(_analyze_function(node))
            
    return summary


def _analyze_class(node: ast.ClassDef) -> ClassSummary:
    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(f"{_get_attr_name(base)}")

    methods = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef):
            methods.append(_analyze_function(item))
            
    return ClassSummary(name=node.name, methods=methods, bases=bases)


def _analyze_function(node: ast.FunctionDef) -> FunctionSummary:
    args = []
    for arg in node.args.args:
        arg_name = arg.arg
        if arg.annotation:
            arg_name += f": {_get_annotation_label(arg.annotation)}"
        args.append(arg_name)
        
    returns = _get_annotation_label(node.returns) if node.returns else None
    
    return FunctionSummary(name=node.name, args=args, returns=returns)


def _get_annotation_label(node: Any) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        return _get_attr_name(node)
    if isinstance(node, ast.Subscript):
        value = _get_annotation_label(node.value)
        slice_val = _get_annotation_label(node.slice)
        return f"{value}[{slice_val}]"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_get_annotation_label(node.left)} | {_get_annotation_label(node.right)}"
    return "Any"


def _get_attr_name(node: ast.Attribute) -> str:
    if isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return node.attr


def _is_ignored(path: Path, root: Path) -> bool:
    ignored_parts = {".venv", "venv", "__pycache__", ".git", "tests", "references"}
    parts = path.relative_to(root).parts
    return any(p in ignored_parts for p in parts)


def format_symbol_map(symbol_map: SymbolMap) -> str:
    """Format the symbol map as a concise YAML-like string for AI."""
    lines = ["# Codebase Map"]
    
    for path, summary in sorted(symbol_map.files.items()):
        if not summary.classes and not summary.functions:
            continue
            
        lines.append(f"{path}:")
        
        for cls in summary.classes:
            base_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"  class {cls.name}{base_str}:")
            for method in cls.methods:
                args = ", ".join(method.args)
                ret = f" -> {method.returns}" if method.returns else ""
                lines.append(f"    - {method.name}({args}){ret}")
                
        for func in summary.functions:
            args = ", ".join(func.args)
            ret = f" -> {func.returns}" if func.returns else ""
            lines.append(f"  def {func.name}({args}){ret}")
            
    return "\n".join(lines)
