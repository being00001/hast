# MVP Programmatic API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Being이 hast를 Python import로 직접 호출하고, 환경변수로 `.ai/` 경로를 격리할 수 있게 한다.

**Architecture:** `run_auto()` 반환 타입을 `int` → `AutoResult`로 변경. 환경변수 `HAST_AI_DIR`/`HAST_CONFIG_PATH`로 경로 resolve. 기존 `build_auto_summary()`를 재활용하여 `AutoResult` 생성.

**Tech Stack:** Python dataclasses, `os.environ`, `dataclasses.replace()`

---

### Task 1: AutoResult / GoalResult 데이터 모델

**Files:**
- Create: `src/hast/core/result.py`
- Test: `tests/test_result.py`

**Step 1: Write the failing test**

Create `tests/test_result.py`:

```python
"""Tests for AutoResult and GoalResult dataclasses."""

from __future__ import annotations

from hast.core.result import AutoResult, GoalResult


def test_goal_result_fields() -> None:
    gr = GoalResult(id="G1", success=True, classification="advance", phase="merge")
    assert gr.id == "G1"
    assert gr.success is True
    assert gr.classification == "advance"
    assert gr.phase == "merge"
    assert gr.action_taken is None
    assert gr.risk_score is None


def test_auto_result_success_property() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[GoalResult(id="G1", success=True)],
        changed_files=["src/a.py"],
        evidence_summary={"total_rows": 1, "successes": 1, "failures": 0},
        errors=[],
    )
    assert r.success is True
    assert r.exit_code == 0


def test_auto_result_failure() -> None:
    r = AutoResult(
        exit_code=1,
        run_id="run2",
        goals=[GoalResult(id="G1", success=False)],
        changed_files=[],
        evidence_summary={"total_rows": 1, "successes": 0, "failures": 1},
        errors=["test failed"],
    )
    assert r.success is False
    assert r.errors == ["test failed"]


def test_auto_result_to_dict() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[
            GoalResult(id="G1", success=True, classification="advance", phase="merge",
                       action_taken="advance", risk_score=25),
        ],
        changed_files=["src/a.py", "src/b.py"],
        evidence_summary={"total_rows": 2, "successes": 2, "failures": 0},
        errors=[],
    )
    d = r.to_dict()
    assert d["exit_code"] == 0
    assert d["run_id"] == "run1"
    assert len(d["goals_processed"]) == 1
    assert d["goals_processed"][0]["id"] == "G1"
    assert d["goals_processed"][0]["success"] is True
    assert d["goals_processed"][0]["risk_score"] == 25
    assert d["changed_files"] == ["src/a.py", "src/b.py"]
    assert d["errors"] == []


def test_auto_result_to_dict_empty() -> None:
    r = AutoResult(
        exit_code=0,
        run_id="run1",
        goals=[],
        changed_files=[],
        evidence_summary={"total_rows": 0},
        errors=[],
    )
    d = r.to_dict()
    assert d["goals_processed"] == []
    assert d["changed_files"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_result.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hast.core.result'`

**Step 3: Write minimal implementation**

Create `src/hast/core/result.py`:

```python
"""Structured result types for hast auto runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GoalResult:
    """Result of a single goal execution."""

    id: str
    success: bool
    classification: str | None = None
    phase: str | None = None
    action_taken: str | None = None
    risk_score: int | None = None


@dataclass(frozen=True)
class AutoResult:
    """Structured result from run_auto()."""

    exit_code: int
    run_id: str
    goals: list[GoalResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when all goals passed."""
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable dict matching auto --json output schema."""
        return {
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "goals_processed": [
                {
                    "id": g.id,
                    "success": g.success,
                    "classification": g.classification,
                    "phase": g.phase,
                    "action_taken": g.action_taken,
                    "risk_score": g.risk_score,
                }
                for g in self.goals
            ],
            "changed_files": self.changed_files,
            "evidence_summary": self.evidence_summary,
            "errors": self.errors,
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_result.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add src/hast/core/result.py tests/test_result.py
git commit -m "feat: add AutoResult and GoalResult dataclasses"
```

---

### Task 2: Environment variable resolve functions

**Files:**
- Modify: `src/hast/core/config.py` (add `resolve_config_path`, `resolve_ai_dir` at top, before `load_config`)
- Test: `tests/test_env_vars.py`

**Step 1: Write the failing test**

Create `tests/test_env_vars.py`:

```python
"""Tests for environment variable path resolution."""

from __future__ import annotations

from pathlib import Path

from hast.core.config import resolve_ai_dir, resolve_config_path


def test_resolve_config_path_default(tmp_path: Path) -> None:
    result = resolve_config_path(tmp_path)
    assert result == tmp_path / ".ai" / "config.yaml"


def test_resolve_config_path_hast_ai_dir(tmp_path: Path, monkeypatch: object) -> None:
    custom_ai = tmp_path / "custom_ai"
    monkeypatch.setenv("HAST_AI_DIR", str(custom_ai))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == custom_ai / "config.yaml"


def test_resolve_config_path_hast_config_path(tmp_path: Path, monkeypatch: object) -> None:
    custom = tmp_path / "my" / "config.yaml"
    monkeypatch.setenv("HAST_CONFIG_PATH", str(custom))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == custom


def test_resolve_config_path_priority(tmp_path: Path, monkeypatch: object) -> None:
    """HAST_CONFIG_PATH takes priority over HAST_AI_DIR."""
    monkeypatch.setenv("HAST_AI_DIR", str(tmp_path / "ai"))  # type: ignore[attr-defined]
    monkeypatch.setenv("HAST_CONFIG_PATH", str(tmp_path / "direct.yaml"))  # type: ignore[attr-defined]
    result = resolve_config_path(tmp_path)
    assert result == tmp_path / "direct.yaml"


def test_resolve_ai_dir_default(tmp_path: Path) -> None:
    result = resolve_ai_dir(tmp_path)
    assert result == tmp_path / ".ai"


def test_resolve_ai_dir_override(tmp_path: Path, monkeypatch: object) -> None:
    custom = tmp_path / "custom_ai"
    monkeypatch.setenv("HAST_AI_DIR", str(custom))  # type: ignore[attr-defined]
    result = resolve_ai_dir(tmp_path)
    assert result == custom
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_env_vars.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_ai_dir' from 'hast.core.config'`

**Step 3: Write minimal implementation**

Add to `src/hast/core/config.py` — insert after the imports, before `_validate_positive_int`:

```python
import os


def resolve_ai_dir(root: Path) -> Path:
    """Resolve .ai directory, honoring HAST_AI_DIR env var."""
    env_ai_dir = os.environ.get("HAST_AI_DIR")
    if env_ai_dir:
        return Path(env_ai_dir)
    return root / ".ai"


def resolve_config_path(root: Path) -> Path:
    """Resolve config.yaml path with env var fallback chain.

    Priority: HAST_CONFIG_PATH > HAST_AI_DIR/config.yaml > {root}/.ai/config.yaml
    """
    env_config = os.environ.get("HAST_CONFIG_PATH")
    if env_config:
        return Path(env_config)
    return resolve_ai_dir(root) / "config.yaml"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_env_vars.py -v`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add src/hast/core/config.py tests/test_env_vars.py
git commit -m "feat: add resolve_ai_dir and resolve_config_path with env var support"
```

---

### Task 3: Extend load_config() signature

**Files:**
- Modify: `src/hast/core/config.py:346-464` (`load_config` function + new `_apply_overrides`)
- Test: `tests/test_config.py` (add new tests at end)

**Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_load_config_with_root(tmp_path: Path) -> None:
    """load_config(root=...) resolves path automatically."""
    ai = tmp_path / ".ai"
    ai.mkdir()
    p = ai / "config.yaml"
    p.write_text(
        "test_command: pytest\nai_tool: echo {prompt}\n",
        encoding="utf-8",
    )
    config, _ = load_config(root=tmp_path)
    assert config.test_command == "pytest"


def test_load_config_with_overrides(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(
        "test_command: pytest\nai_tool: echo {prompt}\ntimeout_minutes: 30\n",
        encoding="utf-8",
    )
    config, _ = load_config(p, overrides={"timeout_minutes": 10, "max_retries": 5})
    assert config.timeout_minutes == 10
    assert config.max_retries == 5


def test_load_config_requires_path_or_root() -> None:
    import pytest as _pt
    with _pt.raises(HastError, match="either path or root"):
        load_config()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_load_config_with_root tests/test_config.py::test_load_config_with_overrides tests/test_config.py::test_load_config_requires_path_or_root -v`
Expected: FAIL — `TypeError: load_config() missing 1 required positional argument`

**Step 3: Write minimal implementation**

Modify `load_config` in `src/hast/core/config.py`:

Replace the current signature and first few lines:
```python
# OLD:
def load_config(path: Path) -> tuple[Config, list[str]]:
    if not path.exists():
        raise HastError(f"config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
```

With:
```python
def load_config(
    path: Path | None = None,
    *,
    root: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> tuple[Config, list[str]]:
    if path is None:
        if root is None:
            raise HastError("either path or root must be provided to load_config()")
        path = resolve_config_path(root)
    if not path.exists():
        raise HastError(f"config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
```

Then at the end of `load_config`, before `return`, add override application:
```python
    # Apply runtime overrides
    if overrides:
        config = _apply_overrides(config, overrides)

    return (config, warnings)
```

(Move the existing `return` into this block.)

Add new helper after `load_config`:
```python
def _apply_overrides(config: Config, overrides: dict[str, Any]) -> Config:
    """Apply runtime overrides to top-level Config fields via dataclasses.replace()."""
    from dataclasses import fields as dc_fields

    valid_names = {f.name for f in dc_fields(Config)}
    filtered = {k: v for k, v in overrides.items() if k in valid_names}
    if not filtered:
        return config
    return Config(**{**{f.name: getattr(config, f.name) for f in dc_fields(Config)}, **filtered})
```

Note: We can't use `dataclasses.replace()` directly because `Config` is `frozen=True` — but we can reconstruct. Actually, `dataclasses.replace()` works fine with frozen dataclasses. Let me simplify:

```python
from dataclasses import replace as dc_replace

def _apply_overrides(config: Config, overrides: dict[str, Any]) -> Config:
    """Apply runtime overrides to top-level Config fields."""
    from dataclasses import fields as dc_fields

    valid_names = {f.name for f in dc_fields(Config)}
    filtered = {k: v for k, v in overrides.items() if k in valid_names}
    if not filtered:
        return config
    return dc_replace(config, **filtered)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASSED (existing + 3 new)

**Step 5: Commit**

```bash
git add src/hast/core/config.py tests/test_config.py
git commit -m "feat: extend load_config with root, overrides parameters"
```

---

### Task 4: Wire AutoResult into run_auto()

**Files:**
- Modify: `src/hast/core/auto.py:1-10` (imports), `auto.py:148-297` (`run_auto` function)
- Test: `tests/test_auto.py` (update 16 assertions)

**Step 1: Modify run_auto() to return AutoResult**

In `src/hast/core/auto.py`:

1. Add import at top (after existing imports):
```python
from hast.core.auto_summary import build_auto_summary
from hast.core.result import AutoResult, GoalResult
```

2. Change `run_auto` return annotation (line 160):
```python
) -> AutoResult:
```

3. Change config loading (line 161):
```python
# OLD:
config, warnings = load_config(root / ".ai" / "config.yaml")
# NEW:
config, warnings = load_config(root=root)
```

4. Replace `return exit_code` (line 297) and the lines before it. The new end of `run_auto` (after `_release_lock` finally block and feedback inference):

```python
    summary = build_auto_summary(root, run_id, exit_code)
    return AutoResult(
        exit_code=exit_code,
        run_id=run_id,
        goals=[
            GoalResult(
                id=g["id"],
                success=g.get("success", False),
                classification=g.get("classification"),
                phase=g.get("phase"),
                action_taken=g.get("action_taken"),
                risk_score=g.get("risk_score"),
            )
            for g in summary.get("goals_processed", [])
        ],
        changed_files=summary.get("changed_files", []),
        evidence_summary=summary.get("evidence_summary", {}),
        errors=[],
    )
```

5. For the dry-run early return (line 183 `return 0`):
```python
    return AutoResult(exit_code=0, run_id=run_id or "")
```

But wait — `run_id` hasn't been set yet at line 183 (it's set at line 196-197). Need to move the `run_id` resolution earlier, or just return a placeholder. Since dry-run doesn't produce evidence, use empty run_id:

```python
    return AutoResult(exit_code=0, run_id=run_id or "dry-run")
```

**Step 2: Update all test assertions in test_auto.py**

In `tests/test_auto.py`, replace all 16 occurrences of `assert ret == 0` / `assert ret == 1`:

```
assert ret == 0  →  assert ret.exit_code == 0
assert ret == 1  →  assert ret.exit_code == 1
```

Lines: 415, 434, 458, 512, 544, 656, 695, 762, 814, 852, 940, 967, 1013, 1082, 1132, 1195.

**Step 3: Update other test files with run_auto assertions**

`tests/test_auto_hard_policy.py` line 76:
```
assert code == 1  →  assert code.exit_code == 1
```

`tests/test_auto_parallel.py` line 79:
```
assert code == 0  →  assert code.exit_code == 0
```

`tests/test_auto_replan.py` line 64:
```
assert code == 0  →  assert code.exit_code == 0
```

`tests/test_auto_risk_merge.py` lines 96, 136, 201:
```
assert code == 1  →  assert code.exit_code == 1
```

`tests/test_evidence_bdd.py` lines 103, 146, 175:
```
assert code == 0  →  assert code.exit_code == 0
assert code == 1  →  assert code.exit_code == 1
assert code == 0  →  assert code.exit_code == 0
```

**Step 4: Run tests to verify**

Run: `pytest tests/test_auto.py tests/test_auto_hard_policy.py tests/test_auto_parallel.py tests/test_auto_replan.py tests/test_auto_risk_merge.py tests/test_evidence_bdd.py tests/test_result.py -v`
Expected: ALL PASSED

**Step 5: Commit**

```bash
git add src/hast/core/auto.py tests/test_auto.py tests/test_auto_hard_policy.py tests/test_auto_parallel.py tests/test_auto_replan.py tests/test_auto_risk_merge.py tests/test_evidence_bdd.py
git commit -m "feat: run_auto returns AutoResult instead of int"
```

---

### Task 5: Update CLI auto_command

**Files:**
- Modify: `src/hast/cli.py:2640-2683` (`auto_command` function)

**Step 1: Modify auto_command**

Replace the `auto_command` body (lines 2650-2683):

```python
def auto_command(
    goal_id: str | None,
    recursive: bool,
    dry_run: bool,
    dry_run_full: bool,
    explain: bool,
    tool_name: str | None,
    parallelism: int,
    json_output: bool,
) -> None:
    """Run automated loop."""
    try:
        if dry_run_full and not dry_run:
            raise click.ClickException("--dry-run-full requires --dry-run")
        root = find_root(Path.cwd())

        result = run_auto(
            root=root,
            goal_id=goal_id,
            recursive=recursive,
            dry_run=dry_run,
            dry_run_full=dry_run_full,
            explain=explain,
            tool_name=tool_name,
            parallelism=parallelism,
        )
    except HastError as exc:
        if json_output:
            _emit_json({"exit_code": 1, "error": str(exc)})
            raise SystemExit(1) from exc
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _emit_json(result.to_dict())

    raise SystemExit(result.exit_code)
```

Key changes:
- Remove `new_run_id()` import and `supplied_run_id` logic — `run_auto()` now always generates `run_id` internally
- `exit_code = run_auto(...)` → `result = run_auto(...)`
- `--json` always uses `result.to_dict()` (no conditional `build_auto_summary` call)
- `SystemExit(exit_code)` → `SystemExit(result.exit_code)`

**Step 2: Run CLI-related tests**

Run: `pytest tests/test_cli_auto.py -v`
Expected: ALL PASSED

**Step 3: Commit**

```bash
git add src/hast/cli.py
git commit -m "feat: CLI auto_command uses AutoResult directly"
```

---

### Task 6: Public API exports

**Files:**
- Modify: `src/hast/__init__.py`

**Step 1: Update __init__.py**

Replace content of `src/hast/__init__.py`:

```python
"""hast — AI-native development session manager."""

__version__ = "0.1.0"

from hast.core.config import Config, load_config, resolve_ai_dir, resolve_config_path
from hast.core.result import AutoResult, GoalResult

__all__ = [
    "AutoResult",
    "Config",
    "GoalResult",
    "load_config",
    "resolve_ai_dir",
    "resolve_config_path",
]
```

Note: `run_auto` is NOT exported here — it has too many parameters and dependencies for casual import. Being should use `from hast.core.auto import run_auto` explicitly. The data types and config functions are the public API.

**Step 2: Write a smoke test**

Add to `tests/test_result.py`:

```python
def test_public_api_imports() -> None:
    """Verify public API is accessible from top-level package."""
    import hast

    assert hasattr(hast, "AutoResult")
    assert hasattr(hast, "GoalResult")
    assert hasattr(hast, "Config")
    assert hasattr(hast, "load_config")
    assert hasattr(hast, "resolve_ai_dir")
    assert hasattr(hast, "resolve_config_path")
```

**Step 3: Run tests**

Run: `pytest tests/test_result.py::test_public_api_imports -v`
Expected: PASSED

**Step 4: Commit**

```bash
git add src/hast/__init__.py tests/test_result.py
git commit -m "feat: export public API from hast package"
```

---

### Task 7: Full test suite verification

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASSED (no regressions)

**Step 2: If any failures, fix and re-run**

Common issues:
- Test files that import `from hast.core.evidence import new_run_id` inside `auto_command` — removed in Task 5, check if other tests depend on that import pattern.
- Any test that calls `run_auto()` and compares return to `int` — should all be caught in Task 4.

**Step 3: Final commit (if fixes needed)**

```bash
git add -A
git commit -m "fix: resolve test regressions from AutoResult migration"
```

---

## Summary of all commits

1. `feat: add AutoResult and GoalResult dataclasses` — Task 1
2. `feat: add resolve_ai_dir and resolve_config_path with env var support` — Task 2
3. `feat: extend load_config with root, overrides parameters` — Task 3
4. `feat: run_auto returns AutoResult instead of int` — Task 4
5. `feat: CLI auto_command uses AutoResult directly` — Task 5
6. `feat: export public API from hast package` — Task 6
7. `fix: resolve test regressions from AutoResult migration` — Task 7 (if needed)
