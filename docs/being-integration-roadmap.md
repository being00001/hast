# hast-Being 통합 개선 로드맵

> 이미 완료된 4개 조치(`.hast-metadata`, `.gitignore`, JSONL rotation, `auto --json`)를 전제로,
> hast 측에서 추가로 개선해야 할 영역을 정리한다.

## HIGH 우선순위

### 1. 컨텍스트 오염 격리

**현재 상태**: `context.py`가 `.ai/` 하위의 session 로그, handoff, git history, rules를 무차별 로드.

**문제**: Being과 같은 workspace에서 실행 시 Being의 실행 흔적(커밋, 세션 로그)이 hast LLM 컨텍스트에 혼입.

- `context.py:103-171` — session/handoff 자동 로드
- `context.py:200-215` — `rules.md`, `plan_note.md` 전역 로드
- `context.py:218-223` — git history 분리 없이 전체 포함
- `context.py:235-294` — Tier 1/2 파일 자동 탐색에 namespace 없음

**필요 조치**:
- `.ai/` 경로를 환경변수(`HAST_AI_DIR`)로 오버라이드 가능하게
- session 소유자 태깅 (hast vs Being 구분)
- context builder에 `exclude_patterns` 옵션 추가

---

### 2. 파일시스템 경계 강화

**현재 상태**: goal runner가 project root 전체에 full access. glob 패턴에 경로 탈출 방어 없음.

**문제**:
- `runners/local.py:37-46` — LocalRunner가 `cwd=root`로 임의 shell 명령 실행
- `context.py:743-784` — `_expand_paths()`의 glob이 `../` 패턴으로 외부 탈출 가능
- `git.py:206-220` — worktree 격리는 되지만 Being이 같은 repo일 때 충돌 가능

**필요 조치**:
- path validation에 `resolve()` + `is_relative_to(root)` 검사 추가
- runner sandbox에 허용 경로 whitelist
- worktree 네이밍에 `hast-` prefix 추가로 Being worktree와 구분

---

### 3. Programmatic API 제공

**현재 상태**: `run_auto()` → exit code(0/1)만 반환. 모든 결과는 파일시스템에 기록.

**문제**:
- `auto.py:148-160` — 반환값이 `int` (exit code)뿐
- `cli.py:2640-2683` — JSON 출력은 CLI stdout에만
- Being이 매번 subprocess + JSON 파싱 필요, config 재로드 오버헤드

**필요 조치**:
```python
@dataclass
class AutoResult:
    exit_code: int
    run_id: str
    goals: list[GoalResult]
    changed_files: list[str]
    evidence_summary: dict[str, Any]
    errors: list[StructuredError]
```
- `run_auto()` 반환 타입을 `AutoResult`로 확장 (하위 호환: `.exit_code` 속성)
- `hast/__init__.py`에 public API export

---

### 4. 이벤트 구독 메커니즘

**현재 상태**: `event_bus.py`는 shadow mode JSONL 로그만 (fire-and-forget).

**문제**:
- `event_bus.py:58-97` — emit만 있고 subscribe 없음
- `event_bus.py:18-24` — 기본 disabled, shadow mode only
- Being이 goal 완료/실패를 알려면 파일 polling 필요

**필요 조치**:
- callback 등록 API: `register_listener(event_type, callback)`
- 또는 최소한 streaming event reader (tail -f 방식)
- `EventBusPolicy.enabled` 기본값을 `True`로 전환 검토

---

## MEDIUM 우선순위

### 5. 설정 유연성

**현재 상태**: `.ai/config.yaml` 경로 하드코딩, runtime override 없음.

**문제**:
- `config.py:346-349` — `load_config(path)` 고정 경로만 수용
- `context.py:724-728` — root 탐색도 `.ai` 디렉토리 기반 하드코딩
- Being이 호출마다 다른 설정(timeout, retry, context 크기)을 줄 수 없음

**필요 조치**:
- 환경변수 지원: `HAST_AI_DIR`, `HAST_CONFIG_PATH`, `HAST_ROOT`
- `load_config()` + `run_auto()`에 `config_overrides: dict` 파라미터 추가
- `Config.from_dict()` 클래스 메서드로 programmatic 생성

---

### 6. 에러 분류 체계

**현재 상태**: 단일 `HastError` 클래스, 에러 코드 없음.

**문제**:
- `errors.py:4-6` — 모든 실패가 같은 exception
- `auto.py:288` — exit code 0/1만 (어떤 goal이 왜 실패했는지 불명)
- Being이 lock 충돌 vs 테스트 실패 vs 구문 오류를 구분 불가

**필요 조치**:
```python
class ErrorCode(enum.Enum):
    LOCK_CONFLICT = "lock_conflict"
    DIRTY_STATE = "dirty_state"
    TEST_FAILURE = "test_failure"
    POLICY_BLOCK = "policy_block"
    TIMEOUT = "timeout"
    RUNNER_ERROR = "runner_error"

class HastError(Exception):
    code: ErrorCode
    goal_id: str | None
    detail: str
```

---

### 7. 동시성/락 강화

**현재 상태**: PID 기반 `.ai/auto.lock`, dirty state 시 hard reset.

**문제**:
- `auto.py:2998-3026` — PID 체크가 컨테이너 환경에서 불안정
- `auto.py:3006-3018` — Being 커밋 중 hast가 hard reset 가능
- `auto.py:249-270` — ThreadPool은 thread-safe지만 process-level 동기화 없음

**필요 조치**:
- `fcntl.flock()` 기반 원자적 파일 락 (PID 대신)
- dirty state reset 전 `HAST_SKIP_RESET=1` 환경변수 또는 확인 프로토콜
- Being과의 mutual exclusion을 위한 cross-process lock 인터페이스

---

### 8. 리소스 제한

**현재 상태**: context 바이트 제한, subprocess timeout, circuit breaker 존재.

**문제**:
- `runners/llm.py:47-69` — 누적 토큰 사용량 미추적
- 디스크 쿼터 없음 (events JSONL 무한 성장)
- goal별 phase timeout 없음 (전체 run timeout만)

**필요 조치**:
- per-goal 토큰 budget: `Config.token_budget_per_goal`
- 디스크 사용량 체크: `rotate_files()` 자동 호출 threshold
- LLM API 타임아웃 명시: `Config.llm_timeout_seconds`

---

## 구현 로드맵

| 단계 | 작업 | 수정 파일 | Being 측 효과 |
|------|------|----------|--------------|
| **MVP** | `HAST_AI_DIR` 환경변수 (#5) + `AutoResult` 반환 (#3) | config.py, auto.py, `__init__.py` | 격리된 상태에서 in-process 호출 가능 |
| **v1** | 에러 코드 (#6) + callback 이벤트 훅 (#4) + flock 락 (#7) | errors.py, event_bus.py, auto.py | 실패 유형 판별 + 실시간 이벤트 수신 |
| **v2** | context 격리 (#1) + path sandbox (#2) + 토큰 budget (#8) | context.py, runners/, config.py | 완전한 안전 격리 통합 |

---

## 관련 문서

- [being-integration-guide.md](./being-integration-guide.md) — 현재 통합 조치 상세 (완료된 4개 포함)
- [ARCHITECTURE.md](./ARCHITECTURE.md) — hast 아키텍처 개요
