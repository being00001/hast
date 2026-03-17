# HAST 개선: Dead Code 탐지 + 커버리지 측정 구현 계획

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rhiza 통합을 위해 dead code 탐지(`find_dead_code`)와 테스트 커버리지 측정(`measure_coverage`)을 구현한다.

**Architecture:** 기존 `build_import_map()`을 활용해 cross-module import 그래프를 구축하고, AST 기반으로 미사용 심볼/import을 탐지한다. `coverage.py` 라이브러리를 직접 호출해 변경 파일 범위 커버리지를 측정한다. dead code는 `src/hast/utils/codetools.py`에, coverage는 `src/hast/utils/coverage.py`에 배치.

**Tech Stack:** Python 3.11, ast (stdlib), coverage.py, pytest, Click CLI

---

## 스코프 경계

### 지원하는 것
- 정적 AST 기반 미사용 심볼 탐지 (top-level functions, classes, imports)
- `__init__.py` re-export, `__all__` 선언 처리
- cross-module import 그래프 기반 사용 여부 판정 (모듈 경로 정확 매칭)
- coverage.py API로 커버리지 데이터 수집 및 변경 파일 범위 리포트
- 확신도(confidence) 레벨: high (static proof) / medium (heuristic)

### 지원하지 않는 것 (명시적 제외)
- 동적 참조: `getattr()`, plugin registry, `entry_points`, `__subclasses__()`
- 메서드 단위 dead code (클래스 내부 미사용 메서드) — v2
- 함수 단위 커버리지 (파일 단위만) — v2
- 커버리지 before/after 비교(`CoverageDelta`) — v2
- CLI 커맨드 추가 — v2 (이번에는 라이브러리 API만)
- Phase 3 인터페이스 안정화 (complexity_check 구조체, codemap 어댑터) — v2

### 완료 기준 (Definition of Done)
- [ ] `find_dead_code()` — fixture 프로젝트에서 precision 100% (false positive 0)
- [ ] `measure_coverage()` — 테스트가 있는 프로젝트에서 정확한 커버리지 % 반환
- [ ] 기존 테스트 전부 통과
- [ ] `ruff check` / `mypy` 통과

---

## 파일 구조

| 파일 | 역할 | 변경 유형 |
|------|------|-----------|
| `src/hast/core/result.py` | `DeadCodeEntry`, `FileCoverage`, `CoverageReport` dataclass 추가 | Modify |
| `src/hast/utils/codetools.py` | `find_dead_code()` 함수 추가 | Modify |
| `src/hast/utils/coverage.py` | `measure_coverage()` 함수 (새 파일) | Create |
| `tests/test_dead_code.py` | dead code 탐지 테스트 | Create |
| `tests/test_coverage_measure.py` | 커버리지 측정 테스트 | Create |
| `pyproject.toml` | `coverage` optional 의존성 추가 | Modify |
| `src/hast/__init__.py` | public API export 추가 | Modify |

**실행 순서 제약:** Task 1 (모든 dataclass)을 먼저 완료한 후 나머지 진행. Task 2-4 (dead code)와 Task 5-6 (coverage)은 Task 1 완료 후 병렬 가능.

---

## Chunk 1: 데이터 구조 + Dead Code 탐지

### Task 1: 모든 데이터 구조 정의 (DeadCodeEntry + FileCoverage + CoverageReport)

**Files:**
- Modify: `src/hast/core/result.py`
- Modify: `pyproject.toml`
- Test: `tests/test_dead_code.py`, `tests/test_coverage_measure.py`

- [ ] **Step 1: Write the failing tests for DeadCodeEntry**

```python
# tests/test_dead_code.py
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
```

- [ ] **Step 2: Write the failing tests for FileCoverage + CoverageReport**

```python
# tests/test_coverage_measure.py
"""Tests for coverage measurement."""

from __future__ import annotations

from hast.core.result import CoverageReport, FileCoverage


def test_coverage_report_creation():
    fc = FileCoverage(
        file="src/app.py",
        covered_lines=80,
        total_lines=100,
    )
    assert fc.percent == 80.0

    report = CoverageReport(
        files=[fc],
        overall_percent=80.0,
    )
    assert len(report.files) == 1
    assert report.overall_percent == 80.0


def test_file_coverage_zero_lines():
    fc = FileCoverage(file="empty.py", covered_lines=0, total_lines=0)
    assert fc.percent == 0.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_dead_code.py tests/test_coverage_measure.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement all dataclasses**

`src/hast/core/result.py`에 추가 (기존 `AutoResult` 아래):

```python
@dataclass(frozen=True)
class DeadCodeEntry:
    """A detected dead code symbol."""

    file: str
    symbol: str
    kind: str  # "function", "class", "import"
    confidence: str = "high"  # "high" = static proof, "medium" = heuristic


@dataclass(frozen=True)
class FileCoverage:
    """Coverage data for a single file."""

    file: str
    covered_lines: int
    total_lines: int

    @property
    def percent(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return round(self.covered_lines / self.total_lines * 100, 1)


@dataclass(frozen=True)
class CoverageReport:
    """Aggregated coverage report."""

    files: tuple[FileCoverage, ...] = ()
    overall_percent: float = 0.0
```

Note: `CoverageReport.files`를 `tuple`로 해서 frozen dataclass의 immutability와 일관성 유지.

- [ ] **Step 5: Update test to use tuple**

`tests/test_coverage_measure.py`의 `test_coverage_report_creation` 수정:

```python
def test_coverage_report_creation():
    fc = FileCoverage(
        file="src/app.py",
        covered_lines=80,
        total_lines=100,
    )
    assert fc.percent == 80.0

    report = CoverageReport(
        files=(fc,),
        overall_percent=80.0,
    )
    assert len(report.files) == 1
    assert report.overall_percent == 80.0
```

- [ ] **Step 6: Add coverage optional dependency to pyproject.toml**

`pyproject.toml`의 `[project.optional-dependencies]` 섹션에 추가:

```toml
[project.optional-dependencies]
pretty = ["rich>=13.0"]
coverage = ["coverage>=7.0"]
dev = [
    ...existing...,
    "coverage>=7.0",
]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_dead_code.py tests/test_coverage_measure.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/hast/core/result.py pyproject.toml tests/test_dead_code.py tests/test_coverage_measure.py
git commit -m "feat: add DeadCodeEntry, FileCoverage, CoverageReport dataclasses"
```

---

### Task 2: 미사용 import 탐지

**Files:**
- Modify: `src/hast/utils/codetools.py`
- Test: `tests/test_dead_code.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dead_code.py (append)
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
    # Should still detect unused import in good.py, not crash on bad.py
    assert any(e.symbol == "os" for e in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dead_code.py -k "import or empty or syntax" -v`
Expected: FAIL — `ImportError: cannot import name 'find_dead_code'`

- [ ] **Step 3: Implement `find_dead_code` — import 분석 부분**

`src/hast/utils/codetools.py` 파일 상단에 import 추가:

```python
from hast.core.result import DeadCodeEntry
```

하단에 함수 추가:

```python
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
    imported_names: dict[str, ast.AST] = {}  # bound_name -> node

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = node
        elif isinstance(node, ast.ImportFrom):
            if node.names and node.names[0].name == "*":
                continue  # skip star imports
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = node

    if not imported_names:
        return []

    # Collect all Name references in Load/Del context
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_names:
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            # e.g. os.path — "os" is used
            if node.value.id in imported_names:
                used_names.add(node.value.id)

    entries: list[DeadCodeEntry] = []
    for name in sorted(imported_names.keys() - used_names):
        entries.append(DeadCodeEntry(file=file, symbol=name, kind="import"))
    return entries
```

Note: `SymbolMap`은 string annotation으로 처리하여 circular import 방지. `from hast.core.analysis import SymbolMap`을 TYPE_CHECKING 블록에 넣거나 string으로 처리.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dead_code.py -k "import or empty or syntax" -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/hast/utils/codetools.py tests/test_dead_code.py
git commit -m "feat: detect unused imports in find_dead_code"
```

---

### Task 3: 미사용 함수/클래스 탐지 (파일 내)

**Files:**
- Modify: `src/hast/utils/codetools.py`
- Test: `tests/test_dead_code.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dead_code.py (append)

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
    # _helper is private but still dead — should be flagged with medium confidence
    assert any(e.symbol == "_helper" and e.confidence == "medium" for e in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dead_code.py -k "function or class or dunder or decorated or async or private" -v`
Expected: FAIL — `find_dead_code` doesn't detect functions/classes yet

- [ ] **Step 3: Extend `find_dead_code` with symbol analysis**

`find_dead_code()` 함수의 for loop 안에 한 줄 추가 + 새 helper 함수:

```python
# find_dead_code() 안의 for loop에 추가:
        entries.extend(_find_unused_imports(tree, rel))
        entries.extend(_find_unused_symbols(tree, rel))  # <-- 이 줄 추가


def _find_unused_symbols(tree: ast.Module, file: str) -> list[DeadCodeEntry]:
    """Find top-level functions/classes never referenced in the same file."""
    # Collect top-level definitions
    definitions: dict[str, tuple[str, str]] = {}  # name -> (kind, confidence)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip dunder names (e.g. __init__, __all__)
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            # Skip decorated functions (likely framework-registered)
            if node.decorator_list:
                continue
            # Single-underscore = medium confidence (convention-private, not guaranteed dead)
            confidence = "medium" if node.name.startswith("_") else "high"
            definitions[node.name] = ("function", confidence)
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if node.decorator_list:
                continue
            confidence = "medium" if node.name.startswith("_") else "high"
            definitions[node.name] = ("class", confidence)

    if not definitions:
        return []

    # Collect all Name usages in Load/Del context
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            used_names.add(node.value.id)

    entries: list[DeadCodeEntry] = []
    for name, (kind, confidence) in sorted(definitions.items()):
        if name not in used_names:
            entries.append(DeadCodeEntry(
                file=file, symbol=name, kind=kind, confidence=confidence,
            ))
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dead_code.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/hast/utils/codetools.py tests/test_dead_code.py
git commit -m "feat: detect unused functions and classes in find_dead_code"
```

---

### Task 4: Cross-module 미사용 탐지

**Files:**
- Modify: `src/hast/utils/codetools.py`
- Test: `tests/test_dead_code.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dead_code.py (append)

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
    # mod_a.utils.process is imported — not dead
    # mod_b.utils.process is NOT imported — dead
    assert len(dead_process) == 1
    assert dead_process[0].file == "src/mod_b/utils.py"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dead_code.py -k "cross_module or reexport or all_export or same_name" -v`
Expected: FAIL — current implementation is file-local only

- [ ] **Step 3: Refactor `find_dead_code` to 2-pass cross-module**

Replace entire `find_dead_code()` function:

```python
def find_dead_code(
    root: Path,
    symbol_map: "SymbolMap | None" = None,
) -> list[DeadCodeEntry]:
    """Detect unused imports, functions, and classes via static AST analysis.

    Two-pass approach:
    1. Per-file: find unused imports, collect top-level definition candidates
    2. Cross-module: filter out definitions that are imported elsewhere or in __all__

    Args:
        root: Project root directory to scan.
        symbol_map: Optional pre-built SymbolMap (currently unused, reserved for v2).
    """
    entries: list[DeadCodeEntry] = []
    py_files = _iter_py_files(root)

    # Pass 1: parse all files
    file_trees: dict[str, ast.Module] = {}  # rel -> tree
    for path in py_files:
        rel = _relpath(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        file_trees[rel] = tree
        entries.extend(_find_unused_imports(tree, rel))

    # Build cross-module index: (source_module, symbol_name) -> set of importing files
    # This tracks WHERE the import comes from, not just the name
    cross_imports: dict[tuple[str, str], set[str]] = {}  # (from_module, name) -> {files}
    all_exports: dict[str, set[str]] = {}  # module -> {names in __all__}

    for rel, tree in file_trees.items():
        module = file_to_module(rel)

        # Collect __all__ entries
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__all__"
                            for t in node.targets)
                    and isinstance(node.value, (ast.List, ast.Tuple))):
                names: set[str] = set()
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        names.add(elt.value)
                if module:
                    all_exports[module] = names

        # Collect ImportFrom with source module info
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name != "*":
                        key = (node.module, alias.name)
                        cross_imports.setdefault(key, set()).add(rel)

    # Pass 2: check each file's top-level definitions
    for rel, tree in file_trees.items():
        module = file_to_module(rel)
        for candidate in _find_unused_symbols(tree, rel):
            # Check if this specific module's symbol is imported anywhere
            if module and (module, candidate.symbol) in cross_imports:
                continue
            # Check if in this file's __all__
            if module and module in all_exports and candidate.symbol in all_exports[module]:
                continue
            entries.append(candidate)

    return entries
```

Key fix from review: `cross_imports` 는 `(source_module, name)` 튜플을 키로 사용하여, 같은 이름의 심볼이 다른 모듈에 있어도 혼동하지 않음.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dead_code.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite for regression**

Run: `pytest tests/ -x -q`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/hast/utils/codetools.py tests/test_dead_code.py
git commit -m "feat: cross-module dead code detection with module-aware import matching"
```

---

## Chunk 2: 커버리지 측정

### Task 5: `measure_coverage()` 구현

**Files:**
- Create: `src/hast/utils/coverage.py`
- Test: `tests/test_coverage_measure.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coverage_measure.py (append)
from pathlib import Path
import textwrap

from hast.utils.coverage import measure_coverage


def _write_py(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_measure_coverage_basic(tmp_path: Path) -> None:
    """Measure coverage of a simple project."""
    _write_py(tmp_path, "src/calc.py", """\
        def add(a, b):
            return a + b

        def unused(x):
            return x * 2
    """)
    _write_py(tmp_path, "tests/test_calc.py", """\
        import sys
        sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'src'))
        from calc import add

        def test_add():
            assert add(1, 2) == 3
    """)

    report = measure_coverage(
        root=tmp_path,
        target_files=["src/calc.py"],
        test_command="pytest tests/ -q",
    )
    assert len(report.files) == 1
    assert report.files[0].file == "src/calc.py"
    # add() is covered, unused() is not — so coverage < 100%
    assert 0 < report.overall_percent < 100


def test_measure_coverage_no_tests(tmp_path: Path) -> None:
    """Project with no test files returns 0% coverage."""
    _write_py(tmp_path, "src/app.py", """\
        def main():
            pass
    """)
    (tmp_path / "tests").mkdir()
    report = measure_coverage(
        root=tmp_path,
        target_files=["src/app.py"],
        test_command="pytest tests/ -q",
    )
    assert report.overall_percent == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coverage_measure.py -k "measure" -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `measure_coverage()`**

```python
# src/hast/utils/coverage.py
"""Test coverage measurement using coverage.py."""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from pathlib import Path

from hast.core.result import CoverageReport, FileCoverage


def measure_coverage(
    root: Path,
    target_files: list[str] | None = None,
    test_command: str | None = None,
) -> CoverageReport:
    """Run tests with coverage and return a report for target files.

    Args:
        root: Project root directory.
        target_files: Relative paths to measure coverage for. If None, all .py files.
        test_command: Test command (e.g. "pytest tests/ -q"). Defaults to "pytest tests/ -q".

    Returns:
        CoverageReport with per-file and overall coverage data.
    """
    test_cmd = test_command or "pytest tests/ -q"

    with tempfile.TemporaryDirectory() as tmpdir:
        data_file = Path(tmpdir) / ".coverage"
        json_file = Path(tmpdir) / "coverage.json"

        source_dir = str(root / "src")

        # Build coverage run command as a list to avoid shell injection
        # coverage run --source=<src> -m pytest tests/ -q
        cmd_parts = [
            "coverage", "run",
            f"--data-file={data_file}",
            f"--source={source_dir}",
            "-m",
        ] + shlex.split(test_cmd)

        try:
            subprocess.run(
                cmd_parts,
                cwd=str(root),
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return CoverageReport()

        if not data_file.exists():
            return CoverageReport()

        # Export to JSON
        try:
            subprocess.run(
                [
                    "coverage", "json",
                    f"--data-file={data_file}",
                    "-o", str(json_file),
                ],
                cwd=str(root),
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return CoverageReport()

        if not json_file.exists():
            return CoverageReport()

        return _parse_coverage_json(json_file, root, target_files)


def _parse_coverage_json(
    json_path: Path,
    root: Path,
    target_files: list[str] | None,
) -> CoverageReport:
    """Parse coverage.py JSON output into CoverageReport."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    files_data = data.get("files", {})

    file_coverages: list[FileCoverage] = []
    total_covered = 0
    total_lines = 0

    for abs_path, info in files_data.items():
        # Normalize to relative path
        try:
            rel = str(Path(abs_path).relative_to(root))
        except ValueError:
            continue

        if target_files and rel not in target_files:
            continue

        summary = info.get("summary", {})
        covered = summary.get("covered_lines", 0)
        num_statements = summary.get("num_statements", 0)

        file_coverages.append(FileCoverage(
            file=rel,
            covered_lines=covered,
            total_lines=num_statements,
        ))
        total_covered += covered
        total_lines += num_statements

    overall = round(total_covered / total_lines * 100, 1) if total_lines > 0 else 0.0

    return CoverageReport(
        files=tuple(file_coverages),
        overall_percent=overall,
    )
```

Key fixes from review:
- `shlex.split()` + list args 대신 `shell=True` — 경로 공백 안전
- `CoverageReport(files=tuple(...))` — frozen dataclass와 일관

- [ ] **Step 4: Install coverage and run tests**

Run: `pip install -e ".[dev]" && pytest tests/test_coverage_measure.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/hast/utils/coverage.py tests/test_coverage_measure.py
git commit -m "feat: measure_coverage() with coverage.py integration"
```

---

## Chunk 3: 마무리 — API Export + 품질 게이트

### Task 6: Public API Export

**Files:**
- Modify: `src/hast/__init__.py`

- [ ] **Step 1: Update `__init__.py`**

기존 import 라인 아래에 추가:

```python
from hast.core.result import AutoResult, CoverageReport, DeadCodeEntry, FileCoverage, GoalResult
```

`__all__` 업데이트:

```python
__all__ = [
    "AutoResult",
    "Config",
    "CoverageReport",
    "DeadCodeEntry",
    "FileCoverage",
    "GoalResult",
    "load_config",
    "resolve_ai_dir",
    "resolve_config_path",
]
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from hast import DeadCodeEntry, CoverageReport, FileCoverage; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/hast/__init__.py
git commit -m "feat: export DeadCodeEntry, CoverageReport, FileCoverage from public API"
```

---

### Task 7: Linting + Type Check

- [ ] **Step 1: Run ruff**

Run: `ruff check src/hast/utils/codetools.py src/hast/utils/coverage.py src/hast/core/result.py src/hast/__init__.py`
Fix any issues.

- [ ] **Step 2: Run mypy**

Run: `mypy src/hast/utils/codetools.py src/hast/utils/coverage.py src/hast/core/result.py`
Fix any type errors.

- [ ] **Step 3: Full test suite**

Run: `pytest tests/ -x -q`
Expected: All PASS

- [ ] **Step 4: Commit fixes if any**

```bash
git add -u
git commit -m "fix: lint and type check fixes for dead code + coverage features"
```

---

### Task 8: 기존 계획 문서 업데이트

**Files:**
- Modify: `docs/plans/improvement-plan-for-rhiza-integration.md`

- [ ] **Step 1: Update the original plan**

변경 사항:
- Phase 1 (Dead Code): `✅ v1 완료` 마크
- Phase 2 (Coverage): `✅ v1 완료` 마크
- Phase 3 체크리스트에서 완료 항목 체크:
  - `[x] find_dead_code() API 확정`
  - `[x] measure_coverage() API 확정`
- v2 로드맵 섹션 추가:
  - 메서드 단위 dead code
  - 함수 단위 커버리지 + CoverageDelta
  - CLI 커맨드 (`hast dead-code`, `hast coverage`)
  - `complexity_check()` → `ComplexityReport` 구조체 반환
  - `.codemap.json → SymbolMap` 어댑터
  - `HastError` 에러 코드 체계

- [ ] **Step 2: Commit**

```bash
git add docs/plans/improvement-plan-for-rhiza-integration.md
git commit -m "docs: update rhiza integration plan with v1 completion status"
```

---

## 실행 순서 요약

```
Task 1 → 모든 dataclass 정의 (result.py)     ── 선행 필수
  ├── Task 2 → 미사용 import 탐지              ── 병렬 가능
  ├── Task 3 → 미사용 함수/클래스 탐지          ── Task 2 후
  ├── Task 4 → Cross-module 인식              ── Task 3 후
  └── Task 5 → measure_coverage() 구현        ── 병렬 가능 (Task 2-4와 독립)
Task 6 → Public API export                   ── Task 1-5 완료 후
Task 7 → Lint + type check                   ── Task 6 후
Task 8 → 문서 업데이트                         ── 마지막
```

총 8개 Task. Task 2-4 (dead code 구현)와 Task 5 (coverage 구현)는 **Task 1 완료 후 병렬 실행 가능**.
