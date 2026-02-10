# devf Roadmap

> devf의 1차 사용자는 AI 에이전트다. 사람은 goal을 정의하고 결과를 확인한다.
> devf는 CLI 도구가 아니라 오케스트레이션 라이브러리다.

---

## 핵심 관점 전환

### Before: 사람이 CLI를 쓴다

```
사람 → devf auto → claude 세션 1 → claude 세션 2 → ...
         ↑ 사람이 실행
```

### After: AI 오케스트레이터가 모듈을 쓴다

```
사람: "인증 시스템 만들어줘"
  ↓
Claude (오케스트레이터 세션)
  ├── devf.goals로 목표 분해
  ├── devf.context로 컨텍스트 조립
  ├── Task tool로 서브 에이전트에게 각 goal 위임
  ├── devf.git으로 롤백/커밋
  ├── devf.session으로 세션 간 상태 브릿지
  └── 실패하면 실패 컨텍스트 + 재위임
```

### 왜 이게 더 나은가

| | devf auto (현재) | 오케스트레이터 패턴 |
|---|---|---|
| 실패 시 | 같은 프롬프트로 재시도 (같은 실수 반복) | 실패 원인을 프롬프트에 포함 |
| 중간 개입 | 불가 (블로킹) | 오케스트레이터가 매 step 판단 |
| 병렬 실행 | 순차만 가능 | 독립 goal 병렬 위임 가능 |
| 적응성 | 고정 루프 | goal 순서/전략 동적 변경 |

### Claude Code 기존 모드와의 관계

```
Sub-agent (Task tool)    — 하나의 컨텍스트 윈도우 안에서 작업 위임
Team (multi-agent)       — 하나의 세션 안에서 에이전트 간 협업
devf 모듈               — 세션/컨텍스트 윈도우 경계를 넘는 상태 관리
```

devf는 Task tool이나 Team을 대체하지 않는다. **보완한다.**
Task tool 서브 에이전트가 작업하고, devf 모듈이 그 결과를 세션 간 상태로 영속화한다.

---

## Phase 1: Retry Context Injection

**문제**: 현재 `devf auto`에서 실패 후 재시도할 때, AI는 같은 프롬프트를 받는다. 이전에 뭘 시도했고 왜 실패했는지 모르기 때문에 같은 실수를 반복할 가능성이 높다.

**해결**: 실패한 attempt의 diff + test output을 저장하고, 다음 attempt 프롬프트에 주입한다.

### 구현 계획

1. `src/devf/core/attempt.py` (~60 lines) — 새 모듈

   ```python
   @dataclass(frozen=True)
   class AttemptLog:
       goal_id: str
       attempt: int
       classification: str
       reason: str
       diff_stat: str
       test_output: str

   def save_attempt(attempt_dir, goal, attempt_num, outcome, diff_stat, test_output)
   def load_attempts(attempt_dir, goal_id) -> list[AttemptLog]
   def clear_attempts(attempt_dir, goal_id)
   ```

   저장 위치: `.ai/attempts/{goal_id}/attempt_{n}.md`

2. `src/devf/core/auto.py` 수정

   - `evaluate()` 실패 시: `reset_hard` 전에 `save_attempt()` 호출
   - `build_prompt()`: `load_attempts()`로 이전 시도 로드, 프롬프트에 주입
   - `run_auto()`: goal 성공 시 `clear_attempts()` 호출

3. 프롬프트 주입 형식

   ```
   PREVIOUS ATTEMPTS (do NOT repeat these approaches)

   Attempt 1: tests failed
   Approach: src/calc.py +15 -3
   Failure: test_divide_zero — ZeroDivisionError not handled

   Attempt 2: tests failed
   Approach: src/calc.py +22 -3
   Failure: test_overflow — integer overflow on large input
   ```

### 이것만으로 달라지는 것

- 재시도 성공률 대폭 향상 (같은 실수 반복 방지)
- max_retries=3의 가치가 실질적으로 증가
- 기존 CLI (`devf auto`)와 라이브러리 사용 모두에서 효과

### 비용: 작음

auto.py 실패 경로에 파일 쓰기 추가 + build_prompt에 컨텍스트 추가.

---

## Phase 2: Orchestrator API

**문제**: devf의 모듈들은 이미 Python에서 import 가능하지만, AI 오케스트레이터가 사용하기 편한 고수준 API가 없다.

**해결**: 오케스트레이터 패턴을 위한 API 레이어 추가.

### 사용 시나리오

사람이 Claude Code 세션에서 말한다:
```
"이 프로젝트에 사용자 인증 시스템 만들어줘"
```

Claude (오케스트레이터)가 하는 일:

```python
from devf.core.goals import load_goals, update_goal_status
from devf.core.context import build_context
from devf.core.session import generate_session_log, write_session_log
from devf.core.attempt import save_attempt, load_attempts, clear_attempts
from devf.utils.git import get_head_commit, commit_all, is_dirty, reset_hard, get_changed_files

# 1. 코드베이스 분석 → goal tree 생성 → goals.yaml에 쓰기
# 2. 각 goal에 대해:
base_commit = get_head_commit(root)
context = build_context(root, "plain", goal_override=goal)
previous = load_attempts(root / ".ai" / "attempts", goal.id)

# 3. Task tool로 서브 에이전트에게 위임
#    (프롬프트 = context + goal + previous attempts)

# 4. 서브 에이전트 완료 후 평가
changed = get_changed_files(root, base_commit)
test_ok = run_tests(root, config.test_command)

# 5. 성공 → 커밋 + 세션 로그
if test_ok and changed:
    if is_dirty(root):
        commit_all(root, f"feat({goal.id}): {goal.title}")
    log = generate_session_log(root, goal, base_commit, test_output)
    write_session_log(root / ".ai" / "sessions", log)
    clear_attempts(root / ".ai" / "attempts", goal.id)
    update_goal_status(goals_path, goal.id, "done")

# 6. 실패 → attempt 저장 + 롤백 + 다른 전략으로 재위임
else:
    save_attempt(attempt_dir, goal, attempt, outcome, diff, test_output)
    reset_hard(root, base_commit)
    # 오케스트레이터가 판단: 재시도? 다른 접근? skip?
```

### 구현 계획

1. `src/devf/orchestrator.py` (~100 lines) — 고수준 API

   ```python
   class DevfOrchestrator:
       """AI 오케스트레이터를 위한 고수준 API."""

       def __init__(self, root: Path):
           self.root = root
           self.config = load_config(root / ".ai" / "config.yaml")

       def get_active_goals(self) -> list[Goal]
       def build_goal_prompt(self, goal, include_attempts=True) -> str
       def evaluate_result(self, goal, base_commit) -> tuple[Outcome, str]
       def accept(self, goal, base_commit, test_output) -> None
           """성공: 자동 커밋 + 세션 로그 + goal status 업데이트"""
       def reject(self, goal, attempt_num, outcome, base_commit) -> None
           """실패: attempt 저장 + 롤백"""
       def checkpoint(self) -> str
           """현재 HEAD 반환 (base_commit으로 사용)"""
   ```

2. CLAUDE.md 가이드 — 오케스트레이터 패턴 사용법

   ```markdown
   ## devf 오케스트레이션
   이 프로젝트는 devf로 세션 상태를 관리합니다.
   대규모 작업 시 devf.orchestrator API를 사용해
   서브 에이전트에게 goal 단위로 위임하세요.
   ```

### devf auto와의 관계

`devf auto`는 유지한다. DevfOrchestrator의 가장 단순한 사용 패턴:

```python
# devf auto = 이것과 동치
orch = DevfOrchestrator(root)
for goal in orch.get_active_goals():
    base = orch.checkpoint()
    for attempt in range(max_retries):
        prompt = orch.build_goal_prompt(goal)
        run_ai(prompt)  # 외부 프로세스 호출
        outcome, output = orch.evaluate_result(goal, base)
        if outcome.success:
            orch.accept(goal, base, output)
            break
        orch.reject(goal, attempt, outcome, base)
```

AI 오케스트레이터는 같은 API를 더 유연하게 사용:
- `run_ai()` 대신 Task tool 서브 에이전트 사용
- 실패 시 전략 변경 (프롬프트 수정, goal 분해, skip)
- 독립 goal 병렬 실행

### 비용: 중간

기존 모듈을 조합하는 thin wrapper. 로직은 이미 auto.py에 있음.

---

## Phase 3: AI-Driven Goal Decomposition

**문제**: goal tree 작성이 devf 사용의 첫 번째 병목. 사람이 작성하든 AI 오케스트레이터가 작성하든, 코드베이스를 이해한 상태에서 적절한 크기로 쪼개야 한다.

**해결**: 오케스트레이터가 코드베이스 분석 → goal tree 생성을 직접 수행.

### 사용 시나리오

```python
# 오케스트레이터가 직접
context = build_context(root, "plain")
existing_goals = load_goals(goals_path)

# 코드베이스를 분석하고 goal tree를 설계
# (이건 오케스트레이터 자신의 판단)
new_goals = [
    Goal(id="F1.1", title="User model", status="active",
         allowed_changes=["src/models/user.py", "tests/test_user.py"]),
    Goal(id="F1.2", title="Password hashing", status="active",
         allowed_changes=["src/auth/hash.py"]),
    ...
]

# goals.yaml에 쓰기
write_goals(goals_path, new_goals, parent_id="F1")
```

### 구현 계획

1. `src/devf/core/goals.py` 확장

   ```python
   def write_goals(path, goals, parent_id=None) -> None
       """goal tree에 새 목표들을 추가한다."""
   ```

2. Goal 분해 가이드라인 (문서)
   - goal 하나 = 서브 에이전트 하나의 컨텍스트 윈도우에 들어가는 크기
   - 테스트 가능한 단위 (독립 검증 가능)
   - `allowed_changes`로 범위 제한 → 서브 에이전트가 엉뚱한 곳 수정 방지
   - TDD 패턴: `expect_failure` goal → 구현 goal 순서

### CLI도 유지

```bash
# 사람이 직접 쓸 때
devf split "인증 시스템" --dry-run
```

하지만 핵심은 CLI가 아니라 `write_goals()` API.

### 비용: 작음

goals.yaml에 쓰기 함수 추가. 분해 로직 자체는 오케스트레이터(AI)의 판단.

---

## Phase 4: PR 자동 생성

**문제**: 여러 goal 완료 후 PR 생성이 수동.

**해결**: 세션 로그를 모아 PR description 생성.

### 구현 계획

1. `src/devf/core/pr.py` (~80 lines)

   ```python
   def collect_session_logs(root, goal_id) -> list[SessionLog]
   def generate_pr_description(logs) -> str
   def create_pr(root, title, body, base_branch) -> str  # gh pr create
   ```

2. 오케스트레이터 사용:

   ```python
   logs = collect_session_logs(root, "F1")
   body = generate_pr_description(logs)
   pr_url = create_pr(root, f"feat(F1): {parent_goal.title}", body, "main")
   ```

3. CLI:

   ```bash
   devf pr F1 --base main
   ```

### 비용: 작음

---

## Phase 5: devf watch (사람 편의)

**위치가 바뀐 이유**: watch는 AI 오케스트레이터에게 불필요하다. 사람이 auto를 돌려놓고 기다릴 때만 유용하다. 오케스트레이터 패턴에서는 오케스트레이터 자신이 진행 상황을 알고 있다.

유지하되 우선순위 낮춤. 기존 계획 그대로:

- `devf watch` — goals.yaml + sessions/ 폴링, 진행 상황 표시
- rich 기반 라이브 업데이트

---

## 아키텍처 요약

```
┌─────────────────────────────────────────────────┐
│  사람                                            │
│  "인증 시스템 만들어줘"                             │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  AI 오케스트레이터 (Claude Code 세션)               │
│                                                  │
│  1. 코드베이스 분석                                │
│  2. Goal 분해 → goals.yaml                       │
│  3. 각 goal을 서브 에이전트에게 위임 (Task tool)     │
│  4. 결과 평가 → 성공/실패 판단                      │
│  5. 실패 시 실패 컨텍스트 포함하여 재위임             │
│  6. 전체 완료 → PR 생성                           │
│                                                  │
│  사용하는 devf 모듈:                               │
│  ┌─────────────┬──────────────┬───────────────┐  │
│  │ goals       │ context      │ session       │  │
│  │ 목표 관리    │ 컨텍스트 조립  │ 세션 상태 영속  │  │
│  ├─────────────┼──────────────┼───────────────┤  │
│  │ attempt     │ git          │ orchestrator  │  │
│  │ 실패 기록    │ 롤백/커밋     │ 고수준 API     │  │
│  └─────────────┴──────────────┴───────────────┘  │
└──────────────────────┬──────────────────────────┘
                       │ Task tool
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     서브 에이전트   서브 에이전트   서브 에이전트
     (goal F1.1)   (goal F1.2)   (goal F1.3)
     독립 컨텍스트   독립 컨텍스트   독립 컨텍스트
```

## 우선순위 요약

| 순위 | 기능 | 누구를 위한 것 | 효과 |
|---|---|---|---|
| 1 | retry context injection | AI (재시도 품질) | 같은 실수 반복 방지 |
| 2 | orchestrator API | AI (유연한 제어) | devf auto의 고정 루프 탈피 |
| 3 | goal decomposition API | AI (작업 계획) | 목표 분해 자동화 |
| 4 | PR 자동 생성 | AI + 사람 | 마지막 마일 자동화 |
| 5 | devf watch | 사람 | 진행 상황 모니터링 |

## 설계 원칙 (개정)

- **1차 사용자는 AI다** — API 우선, CLI는 API의 thin wrapper
- **devf auto는 유지한다** — 가장 단순한 오케스트레이션 패턴으로서
- **컨텍스트 윈도우를 넘는 상태 관리** — 이것이 Claude Code 기존 모드와 겹치지 않는 고유 가치
- **파일이 상태다** — 세션 로그, attempt 로그, goals.yaml 전부 파일
- **모듈은 독립적으로 사용 가능** — 전체를 쓸 필요 없음

> Updated: 2026-02-10
