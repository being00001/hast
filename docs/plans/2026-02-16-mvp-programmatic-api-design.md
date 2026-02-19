# MVP: Programmatic API + Environment Variable Support

> Being 통합 로드맵 MVP 단계. `AutoResult` 반환 타입과 환경변수 기반 설정 유연성 도입.

## 배경

이전 세션에서 완료한 4개 조치(`.hast-metadata`, `.gitignore`, JSONL rotation, `auto --json`)는
파일시스템 레벨의 통합이었다. 이번 MVP는 **코드 레벨 통합**을 열어주는 단계:
- Being이 hast를 subprocess가 아닌 Python import로 직접 호출
- 환경변수로 `.ai/` 디렉토리와 설정 파일 경로를 격리

## 데이터 모델

### `GoalResult`

```python
@dataclass(frozen=True)
class GoalResult:
    id: str
    success: bool
    classification: str | None = None
    phase: str | None = None
    action_taken: str | None = None
    risk_score: int | None = None
```

### `AutoResult`

```python
@dataclass(frozen=True)
class AutoResult:
    exit_code: int
    run_id: str
    goals: list[GoalResult]
    changed_files: list[str]
    evidence_summary: dict[str, Any]
    errors: list[str]

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for CLI --json output."""
        ...
```

**설계 결정**: `run_auto()` 반환 타입을 `int` → `AutoResult`로 직접 변경.
- 외부 사용자가 `run_auto()`를 직접 호출하는 경우 없음 (아직 public API 아님)
- CLI의 `sys.exit()` 호출 1곳만 `sys.exit(result.exit_code)`로 변경
- `__int__` 매직은 불필요 (명시적 `.exit_code` 접근이 더 명확)

## 환경변수 지원

### 변수 목록

| 환경변수 | 용도 | 기본값 |
|----------|------|--------|
| `HAST_CONFIG_PATH` | config.yaml 경로 직접 지정 | 없음 |
| `HAST_AI_DIR` | `.ai/` 디렉토리 경로 교체 | `{root}/.ai` |

우선순위: `HAST_CONFIG_PATH` > `HAST_AI_DIR/config.yaml` > `{root}/.ai/config.yaml`

### 해석 함수

```python
def resolve_config_path(root: Path) -> Path:
    """env var fallback chain for config path."""

def resolve_ai_dir(root: Path) -> Path:
    """env var fallback for .ai directory."""
```

### `load_config()` 시그니처 확장

```python
def load_config(
    path: Path | None = None,
    *,
    root: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> tuple[Config, list[str]]:
```

- `path` positional 그대로 동작 → 기존 호출 하위 호환
- `root=` 지정 시 `resolve_config_path(root)` 자동 적용
- `overrides=` 로 top-level Config 필드 런타임 교체 (`dataclasses.replace()`)

## auto.py 변경

- `run_auto()` 반환: `int` → `AutoResult`
- 내부에서 `load_config(root / ".ai" / "config.yaml")` → `load_config(root=root)`
- `_lock_path(root)`: `resolve_ai_dir(root)` 사용
- run 종료 시 `build_auto_summary()` → `AutoResult` 변환
- DevfError catch 시에도 `AutoResult(exit_code=1, errors=[...])` 반환

## CLI 변경

- `auto_command`: `sys.exit(result.exit_code)`
- `--json` 시: `result.to_dict()` 출력 (기존 `build_auto_summary()` 직접 호출 제거)

## Public API (`__init__.py`)

```python
from hast.core.result import AutoResult, GoalResult
from hast.core.auto import run_auto
from hast.core.config import Config, load_config, resolve_ai_dir, resolve_config_path
```

Being 사용 예시:
```python
import hast

result = hast.run_auto(
    root=Path("/path/to/being"),
    goal_id="G_login",
    recursive=False, dry_run=False, explain=False, tool_name=None,
)
if result.success:
    print(f"Changed: {result.changed_files}")
```

## 수정 파일 요약

| 파일 | 변경 유형 |
|------|----------|
| `src/hast/core/result.py` | 신규 — `AutoResult`, `GoalResult` |
| `src/hast/core/config.py` | 수정 — `resolve_*()`, `load_config()` 시그니처 확장 |
| `src/hast/core/auto.py` | 수정 — 반환 `AutoResult`, `.ai/` resolve |
| `src/hast/cli.py` | 수정 — `sys.exit(result.exit_code)`, `--json` |
| `src/hast/__init__.py` | 수정 — public API export |
| `tests/test_result.py` | 신규 — AutoResult 단위 테스트 |
| `tests/test_env_vars.py` | 신규 — resolve 함수 + 환경변수 테스트 |
| `tests/test_auto.py` | 수정 — 반환값 타입 업데이트 |
| `tests/test_config.py` | 수정 — load_config 시그니처 테스트 추가 |

## 범위 외 (v1/v2로 미룸)

- 에러 코드 체계 (`HastError`, `ErrorCode`) → v1
- 이벤트 callback 구독 → v1
- context.py의 `.ai/` 경로 전면 교체 → v2
- path sandbox → v2
