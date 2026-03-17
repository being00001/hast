# hast: AI-Native Development Session Manager

> 3개 명령어 + 규약. Solo developer + AI coding agent를 위한 세션 연속성과 자동화.

---

## 1. Problem Statement

### AI 코딩 도구의 구조적 한계

Claude Code, Codex, Gemini CLI 등 AI 코딩 도구는 **세션이 상태를 갖지 않는다.**

| 사람 개발자 | AI 코딩 에이전트 |
|---|---|
| 어제 뭘 했는지 기억한다 | 매 세션 백지에서 시작 |
| 코드베이스 전체 구조를 안다 | 매번 파일을 열어봐야 안다 |
| "이쯤이면 됐다"를 판단한다 | 완료 기준이 없으면 멈추지 않는다 |
| 작업 품질을 직관으로 검증한다 | 테스트 통과 외에 검증 수단이 없다 |

**결과**: 매 세션마다 2-3턴을 부팅에 쓰고, 컨텍스트가 커지면 품질이 떨어지고, 세션 간 연결이 끊긴다.

### 기존 도구가 못 메우는 갭

| 기존 도구 | 하는 것 | 못 하는 것 |
|---|---|---|
| CLAUDE.md / AGENTS.md | 세션 규칙 정의 | 세션 간 상태 전달 |
| Claude Memory | 인사이트 저장 | 구조화된 작업 맥락 전달 |
| GitHub Projects / Linear | 프로젝트 관리 | AI가 읽기 어려운 포맷 |
| pre-commit hooks | 커밋 전 검증 | 세션 중 검증 |
| CI/CD | 자동 테스트 | 로컬 세션 검증 |

---

## 2. Core Insight: 프로토콜 + 최소 도구

세션 연속성은 **프로토콜 문제이지, 도구 문제가 아니다.**

대부분의 세션 연속성 요구는 규약(convention)으로 해결된다:

| 요구 | 규약으로 해결 |
|---|---|
| 핸드오프 작성 | CLAUDE.md: "작업 후 `.ai/handoffs/`에 핸드오프 작성" |
| 테스트 실행 | CLAUDE.md: "커밋 전 pytest 실행" 또는 pre-commit hook |
| 목표 추적 | goals.yaml 파일 직접 편집 |
| 세션 경계 | git commit |
| 메트릭 | git log 분석 |

**도구가 정당화되는 건 규약만으로 안 되는 것뿐:**

1. **구조화된 컨텍스트 조립** (`hast context`) — 핸드오프 + 목표 + 규칙을 하나의 텍스트로 자동 조립. 여러 파일을 읽어서 조합하는 로직이 필요.
2. **비인터랙티브 자동화 루프** (`hast auto`) — Claude는 세션 밖에서 자신을 재시작할 수 없다. 세션 체이닝, 재시도, 롤백은 외부 프로세스가 해야 한다.

---

## 3. Design Principles

| 원칙 | 설명 |
|---|---|
| **규약 먼저, 도구 나중** | 규약으로 되는 건 도구를 만들지 않는다. |
| **각 명령이 독립적으로 가치 있다** | `hast context`만 써도 유용. 전체를 쓸 필요 없음. |
| **파일이 상태다** | DB 없음, 데몬 없음. `.ai/`의 파일이 전부. git으로 추적. |
| **AI 도구에 무관** | Claude, Codex, Gemini, Cursor — 뭐든 동작. |
| **원인 + 다음 행동** | 모든 메시지는 "무엇이 잘못됐고, 다음에 무엇을 하라" 포함. |

---

## 4. Architecture

```
hast = 3 commands + convention

┌─────────────────────────────────────┐
│  hast auto (자동화 루프)              │
│  goal 선택 → context 조립 → AI 호출  │
│  → 검증 → 판정 → 롤백/다음           │
├─────────────────────────────────────┤
│  hast context (컨텍스트 조립)         │
│  핸드오프 + 목표 + 규칙 → 텍스트      │
├─────────────────────────────────────┤
│  Convention (규약)                   │
│  CLAUDE.md 규칙, 핸드오프 형식,       │
│  goals.yaml, pre-commit hooks       │
└─────────────────────────────────────┘
```

| 구성 요소 | 역할 | 구현 |
|---|---|---|
| `hast init` | 프로젝트 초기화 | `.ai/` 생성 + 템플릿 |
| `hast context` | 컨텍스트 조립 | 핸드오프 + 목표 + 규칙 → 텍스트 |
| `hast auto` | 자동화 루프 | goal 순회, AI 호출, 검증, 재시도, 롤백 |
| Convention | 세션 규약 | CLAUDE.md 규칙, 핸드오프 형식 |

---

## 5. Directory Structure

### `.ai/` (프로젝트 루트에 생성)

```
.ai/
├── config.yaml          # 최소 설정 (test command, AI tool)
├── goals.yaml           # 목표 (사람이 편집, auto가 상태 업데이트)
├── handoffs/            # 핸드오프 노트 (AI가 작성)
│   ├── 2026-02-09_143000.md
│   └── ...
└── rules.md             # AI 세션 규약 (CLAUDE.md에서 참조)
```

**git 추적 대상**: 전부. 핸드오프도 git으로 추적한다 (세션 히스토리).

---

## 6. config.yaml

```yaml
test_command: "pytest tests/ -v --tb=short"
ai_tool: "claude -p {prompt}"
```

2줄. 이것만 있으면 `hast auto`가 동작한다.

### 확장 (선택)

```yaml
test_command: "pytest tests/ -v --tb=short"
ai_tool: "claude -p {prompt}"

# 선택 설정
timeout_minutes: 30          # 세션당 타임아웃 (기본: 30)
max_retries: 3               # goal당 재시도 (기본: 3)

# 다른 AI 도구 (hast auto --tool codex)
ai_tools:
  codex: "codex exec {prompt}"
  gemini: "gemini -p {prompt}"
```

---

## 7. goals.yaml

```yaml
goals:
  - id: M4
    title: "MindLoop Intelligence"
    status: active
    children:
      - id: M4.1
        title: "Belief System"
        status: done
      - id: M4.2
        title: "Goal Pursuit"
        status: active
      - id: M4.3
        title: "Strategy Learning"
        status: pending
        # 선택: 자동화 설정
        expect_failure: true
        allowed_changes: ["core/strategy.py", "tests/"]
```

### Goal 상태

| status | 의미 |
|---|---|
| `pending` | 아직 안 함 |
| `active` | 현재 작업 대상 |
| `done` | 완료 |
| `blocked` | 자동화 실패로 차단 (`hast auto`가 설정) |
| `dropped` | 폐기 |

### Goal별 자동화 설정 (선택)

| 필드 | 기본값 | 설명 |
|---|---|---|
| `expect_failure` | false | true면 테스트 실패가 정상 (TDD RED 단계) |
| `allowed_changes` | [] (무제한) | 수정 허용 파일 패턴 |
| `prompt_mode` | null | "adversarial" → 코드를 깨뜨리는 테스트 작성 |
| `mode` | null | "interactive" → auto에서 건너뜀 |
| `tool` | null | AI 도구 오버라이드 |

설정이 없으면 기본값. goal 설정은 config.yaml 전역 설정보다 우선한다.

### Goal 선택 정책

`hast auto --recursive`에서 다음 goal을 선택하는 규칙:

```
1. 최근 핸드오프의 goal_id와 일치하는 active goal (연속성)
2. 가장 깊은(leaf) active goal (구체적 작업 우선)
3. 같은 depth면 goals.yaml에서 먼저 나오는 것 (선언 순서)
```

### 관리 방법

CLI 없음. 에디터로 직접 편집한다.

```bash
# 목표 추가: goals.yaml에 항목 추가
# 목표 완료: status를 done으로 변경
# 목표 폐기: status를 dropped으로 변경
# hast auto는 성공 시 자동으로 status: done 설정
```

---

## 8. Handoff Protocol (규약)

### 형식

```markdown
---
timestamp: "2026-02-09T14:30:00+09:00"
status: complete
goal_id: M4.3.1
---

## Done
- core/mind/nodes/record.py: Strategy extraction 구현
- tests/test_strategy_learning.py: 18개 테스트 작성

## Key Decisions
- 성공 시 STRATEGY belief confidence 0.4로 초기화

## Changed Files
- core/mind/nodes/record.py (수정)
- tests/test_strategy_learning.py (신규)

## Next
M4.3.2 — Reflect 노드에서 STRATEGY 카테고리 쿼리
- core/mind/nodes/reflect.py 수정

## Context Files
1. core/mind/nodes/reflect.py
2. core/memory/belief.py
```

### 작동 방식

- **인터랙티브 세션**: CLAUDE.md 규약에 따라 AI가 직접 `.ai/handoffs/{timestamp}.md`에 작성
- **자동화 세션**: `hast auto`의 프롬프트에 핸드오프 작성 지시 포함. auto가 파일 존재 여부로 성공 판정
- **품질 보장**: AI가 안 쓰면 → `hast auto`가 실패로 판정 → 롤백 → 재시도. Outer loop가 안전망.

### CLAUDE.md에 추가할 규약

```markdown
## 세션 규약
- 작업 시작 전 `.ai/handoffs/`의 최신 파일을 읽어라.
- 작업 완료 후 `.ai/handoffs/YYYY-MM-DD_HHMMSS.md`에 핸드오프를 작성하라.
- 형식: `.ai/rules.md` 참조
- 테스트를 실행하고 통과를 확인한 후 핸드오프를 작성하라.
```

---

## 9. `hast context` — 컨텍스트 조립

### 역할

핸드오프 + 목표 + 규칙을 **하나의 구조화된 텍스트**로 조립한다.

### 출력 예시

```markdown
# Session Context

## Current Goal
M4.3.2 — Strategy query in Reflect
Parent: M4.3 Strategy Learning (active)

## Previous Session (2026-02-09 14:30)
Status: complete
Done: Strategy extraction in Record node (18 tests pass)
Key Decision: STRATEGY belief confidence 초기화 0.4

## Your Task
M4.3.2 — Reflect 노드에서 STRATEGY 카테고리 쿼리
- core/mind/nodes/reflect.py 수정
- min_confidence=0.4, contamination<0.7 필터

## Context Files (read these first)
1. core/mind/nodes/reflect.py
2. core/memory/belief.py
3. tests/test_strategy_learning.py

## Rules
- 테스트가 통과해야 완료
- 작업 완료 후 .ai/handoffs/ 에 핸드오프 작성
- 커밋 형식: feat(M4.3.2): description
```

### 소스 우선순위

```
1. 최근 핸드오프의 "Next" 섹션 → 가장 구체적인 작업 지시
2. goals.yaml의 현재 active 목표 → 방향
3. 최근 핸드오프의 "Key Decisions" → 이전 맥락
4. 최근 핸드오프의 "Context Files" → 읽어야 할 파일
5. rules.md → 규칙
```

### 사용법

```bash
hast context                          # 터미널에서 확인
hast context --format plain           # 토큰 절약 (자동화용)
hast context --format json            # 프로그래밍적 사용
hast context | pbcopy                 # 클립보드 복사 (macOS)
claude -p "$(hast context)"           # 직접 주입
```

---

## 10. `hast auto` — 자동화 루프

### 설계 원칙

```
AI는 세션 안에서 최고의 판단을 하지만,
세션 밖에서 자신을 재시작할 수 없다.
hast auto는 세션 밖의 루프를 담당한다.
```

### CLI

```bash
hast auto M4.3.2                      # 단일 goal
hast auto M4 --recursive              # 하위 goal 순서대로
hast auto M4.3.2 --dry-run            # 드라이런 요약 출력
hast auto M4.3.2 --dry-run --dry-run-full
                                      # 전체 프롬프트 출력
hast auto M4.3.2 --explain            # 판정 사유를 stderr에 출력
hast auto M4.3.2 --tool codex         # 다른 AI 도구 사용
hast auto M4 --recursive --parallel 3 # 병렬 goal 실행
```

### 루프 구조

```python
def run_auto(goal_id, recursive=False, dry_run=False, explain=False):
    # 0. 고아 세션 복구
    recover_if_dirty(root)

    # 1. 대상 goal 수집
    goals = collect_goals(goal_id, recursive)  # active만, interactive skip

    for goal in goals:
        base_commit = git_rev_parse("HEAD")

        for attempt in range(1, max_retries + 1):
            # 2. 프롬프트 조립
            prompt = build_prompt(root, goal)
            if dry_run:
                print(prompt); break

            # 3. AI 세션 실행
            run_ai(ai_tool, prompt, timeout_minutes)

            # 4. 결과 판정
            outcome = evaluate(root, goal, base_commit)

            if explain:
                log(f"[{goal.id}] attempt={attempt} → {outcome.classification}: {outcome.reason}")

            # 5. 분기
            if outcome.success:
                set_goal_status(goal.id, "done")
                break
            elif outcome.should_retry:
                git_reset_hard(base_commit)  # 롤백 후 재시도
            else:
                set_goal_status(goal.id, "blocked", reason=outcome.reason)
                break
        else:
            # max_retries 소진
            set_goal_status(goal.id, "blocked", reason="max retries exceeded")
```

### 프롬프트 구성

```python
def build_prompt(root, goal):
    context = run("hast context --format plain")

    instructions = """
작업 완료 후:
1. {test_command}를 실행하라. 실패 시 수정 후 재실행 (최대 3회).
2. 모든 테스트가 통과하면 .ai/handoffs/{timestamp}.md에 핸드오프를 작성하라.
   형식: ## Done / ## Key Decisions / ## Changed Files / ## Next / ## Context Files
3. 작업이 불가능하면 핸드오프 status를 blocked으로 작성하고 사유를 기록하라.
"""

    # goal별 추가 지시
    if goal.expect_failure:
        instructions += "\n이 단계는 테스트 작성만. 테스트가 실패하면 정상."
    if goal.allowed_changes:
        instructions += f"\n다음 파일만 수정하라: {goal.allowed_changes}"
    if goal.prompt_mode == "adversarial":
        instructions += "\n이 코드를 깨뜨려라. 악의적 입력, 동시성, 리소스 고갈 등."

    return context + "\n---\n" + instructions
```

### 결과 판정

```python
def evaluate(root, goal, base_commit):
    handoff = find_new_handoff(root, since=base_commit_time)
    test_ok = run(config.test_command).returncode == 0
    has_changes = bool(git_diff(base_commit))

    # expect_failure 모드
    if goal.expect_failure:
        if not test_ok:
            return Outcome(success=True, classification="complete (expected failure)")
        else:
            return Outcome(should_retry=True, reason="테스트가 통과함 — 실패해야 할 테스트가 누락")

    # 일반 모드
    if handoff and test_ok and has_changes:
        return Outcome(success=True, classification="complete")

    if not has_changes:
        return Outcome(should_retry=True, classification="no-progress", reason="파일 변경 없음")

    if handoff and handoff.status == "blocked":
        return Outcome(should_retry=False, classification="blocked", reason=handoff.reason)

    if not test_ok:
        return Outcome(should_retry=True, classification="failed", reason="테스트 실패")

    if not handoff:
        return Outcome(should_retry=True, classification="failed", reason="핸드오프 미작성")
```

### 고아 세션 복구 (Crash Recovery)

이전 `hast auto`가 크래시/타임아웃으로 비정상 종료된 경우:

```
hast auto 시작 시:
1. git status에서 uncommitted changes 확인
2. 이전 실행의 비정상 종료로 판단되면:
   a. 마지막 clean commit으로 롤백
   b. 로그: "이전 실행이 비정상 종료됨. 롤백 후 재시작."
3. 정상 시작 진행
```

### 롤백 정책

| 상황 | 롤백 | 사유 |
|---|---|---|
| 테스트 실패 (변경 있음) | O | 잘못된 변경이 다음 시도를 오염 |
| no-progress (변경 없음) | O | 깨끗한 상태에서 재시도 |
| 핸드오프 미작성 | O | 불완전한 세션 |
| 타임아웃 | O | 불확실한 상태 |
| blocked (AI가 판단) | X | 사람이 봐야 함. 변경 보존 |
| max_retries 초과 | X | 마지막 시도 변경 보존 (디버깅용) |

**원칙**: 재시도할 실패 → 롤백. 사람에게 넘길 실패 → 변경 보존.

---

## 11. `hast init` — 프로젝트 초기화

### 생성되는 파일

```yaml
# .ai/config.yaml
test_command: "pytest"
ai_tool: "claude -p {prompt}"
```

```yaml
# .ai/goals.yaml
goals: []
```

```markdown
# .ai/rules.md

## 핸드오프 규약
- 작업 완료 후 `.ai/handoffs/YYYY-MM-DD_HHMMSS.md`에 핸드오프 작성
- 필수 섹션: Done, Key Decisions, Changed Files, Next, Context Files
- YAML frontmatter: timestamp, status (complete/failed/blocked), goal_id

## 검증
- 커밋 전 테스트 실행
- 테스트 통과 후 핸드오프 작성

## 커밋 형식
{type}({goal_id}): {description}
types: feat, fix, refactor, test, docs, chore
```

### 출력

```
hast init
═════════

  Created .ai/
  ├── config.yaml
  ├── goals.yaml
  ├── rules.md
  └── handoffs/

  다음 단계:
  1. .ai/config.yaml에서 test_command를 프로젝트에 맞게 수정하세요.
  2. .ai/goals.yaml에 목표를 추가하세요.
  3. CLAUDE.md에 다음을 추가하세요:

     ## 세션 규약
     이 프로젝트는 .ai/ 디렉토리로 세션을 관리합니다.
     - 작업 전 `.ai/handoffs/`의 최신 파일을 읽으세요.
     - 작업 후 `.ai/handoffs/`에 핸드오프를 작성하세요.
     - 규칙: `.ai/rules.md` 참조
```

---

## 12. CLI

```
hast init                                          프로젝트 초기화
hast context [--format markdown|plain|json]        컨텍스트 조립
hast auto [goal_id] [--recursive] [--dry-run] [--dry-run-full]
         [--explain] [--tool NAME] [--parallel N]  자동화 루프
hast explore "<question>"                          읽기 전용 설계 탐색
hast retry <goal_id>                               blocked goal 복구 + 재실행
hast queue claim --worker W [--role R] [--goal G] 실행 큐 claim (lease/TTL/idempotency/role lane)
hast queue renew <claim_id> --worker W            lease 갱신
hast queue release <claim_id> --worker W          claim 해제 + 선택적 goal 상태 전환
hast queue list [--active-only]                   실행 큐 조회
hast observe baseline [--window N]                관측성 기준선/준비도 리포트
hast events replay [--write/--no-write]          이벤트 로그 리플레이 + 상태 스냅샷 갱신
hast inbox list [--open-only|--include-resolved] operator inbox 조회
hast inbox summary [--top-k N]                    우선순위 기반 inbox 압축 요약
hast inbox act <inbox_id> --action A --operator O [--goal-status S]
                                                  정책 액션(approve/reject/defer)
hast protocol export --adapter A [--goal G] [--role R]
                                                  외부 오케스트레이터 task packet 생성
hast protocol ingest <result_packet.json>         외부 실행 결과 packet 인입(evidence 반영)
hast decision spike <decision_file> [--parallel N] [--backend auto|thread|ray]
                     [--accept] [--accept-if-reason CODE]
                     [--accept-max-diff-lines N] [--accept-max-changed-files N]
                     [--accept-require-eligible] [--explain]
```

초기 설계는 `init/context/auto` 3개 명령어였고, 현재는 운영 자동화 요구를 반영해
보조 명령어(`explore/retry/queue/observe/events/inbox/protocol/decision spike`)가 확장되었다.

### 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 1 | 에러 또는 자동화 실패 |

---

## 13. 규약이 대체하는 것

기존 9스코프 설계를 검토한 결과, 7개 스코프는 규약이나 기존 도구로 대체 가능했다:

| 기존 설계 | 지금 | 이유 |
|---|---|---|
| `hast session start/end` | git commit이 세션 경계 | 별도 세션 상태 불필요 |
| `hast validate` | `hast auto`가 내부에서 test_command 실행 | 사람은 직접 pytest |
| `hast handoff create/check` | AI가 직접 작성 (CLAUDE.md 규약) | CLI로 강제할 필요 없음 |
| `hast goal add/done/list` | goals.yaml 직접 편집 | YAML CRUD CLI는 과잉 |
| `hast status` | goals.yaml 직접 확인 | 트리 출력은 nice-to-have |
| `hast metrics` | git log 분석 | 별도 메트릭 저장 불필요 |
| `hast doctor` | 불필요 | 설정이 2줄이면 진단할 것도 없음 |
| Skills (hast-start/check/done) | 프롬프트에 직접 포함 | 별도 skill 파일 불필요 |
| Hooks (PreToolUse/Stop) | 선택사항, hast 범위 밖 | pre-commit으로 충분 |

---

## 14. Integration with AI Tools

### Claude Code (인터랙티브)

```bash
# CLAUDE.md에 규약 추가 → AI가 자동으로 따름
# 필요 시 수동 컨텍스트 생성
hast context | pbcopy   # 클립보드에 복사해서 붙여넣기

# 또는 직접 주입
claude -p "$(hast context)"
```

### Claude Code (비인터랙티브)

```bash
hast auto M4.3.2                    # 단일 goal
hast auto M4 --recursive            # 전체 파이프라인
hast retry M4.3.2                   # blocked goal 원커맨드 복구
hast decision spike .ai/decisions/D_M4.yaml --accept --accept-if-reason diff_lines
```

### Codex / Gemini CLI

```yaml
# .ai/config.yaml
ai_tool: "codex exec {prompt}"
```

또는:

```bash
hast auto M4.3.2 --tool codex
```

### AGENTS.md (Codex용)

```markdown
## 세션 규약
- 작업 시작 전 `.ai/handoffs/`의 최신 파일을 읽을 것
- 작업 완료 후 `.ai/handoffs/`에 핸드오프 작성
- 테스트: .ai/config.yaml의 test_command 참조
```

---

## 15. Package Structure

```
hast/
├── pyproject.toml
├── src/hast/
│   ├── __init__.py
│   ├── __main__.py           # python -m hast
│   ├── cli.py                # 3 commands (click)
│   ├── context.py            # 컨텍스트 조립 (~100 lines)
│   ├── auto.py               # 자동화 루프 (~200 lines)
│   ├── init_project.py       # 초기화 (~50 lines)
│   ├── goals.py              # goals.yaml 파서 (~80 lines)
│   ├── handoff.py            # 핸드오프 파서 (~60 lines)
│   └── templates/            # init 템플릿
│       ├── config.yaml
│       ├── goals.yaml
│       └── rules.md
├── tests/
│   ├── test_context.py
│   ├── test_auto.py
│   ├── test_goals.py
│   └── test_init.py
└── docs/
    └── design.md              # 이 문서
```

### 의존성

```toml
[project]
name = "hast"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
pretty = ["rich>=13.0"]

[project.scripts]
hast = "hast.cli:main"
```

2개 필수 의존성. `rich`는 선택.

---

## 16. Implementation Roadmap

### Phase 1: Foundation (1일)

```
hast init      — .ai/ 생성, 템플릿
hast context   — 핸드오프 + 목표 + 규칙 조립
```

이것만으로 `hast context | pbcopy`로 세션 부팅 시간 단축.

### Phase 2: Automation (1-2일)

```
hast auto      — 자동화 루프
```

이 단계에서 `hast auto M4.3.2`로 무인 자동 세션 가능.

### 범위 밖

- 고급 세션 전략 (조건부 분기, 병렬 실행)
- 멀티 LLM 전략 토론
- Web UI / 대시보드
- 다중 사용자/팀 기능
- 코드 참조 그래프

---

## 17. Design Decisions

### 왜 3개 명령어인가? (9스코프가 아닌)

9스코프 설계를 검토한 결과, 7개는 규약으로 대체 가능했다. 도구가 정당화되는 건 규약만으로 안 되는 것뿐: 컨텍스트 조립(여러 파일 조합 로직)과 자동화 루프(외부 프로세스 필요).

### 왜 .ai/ 인가?

- 짧다
- 의도가 명확하다 (AI 세션 관리용)
- 도구 이름이 바뀌어도 디렉토리명 유지

### 왜 데몬이 아닌 CLI인가?

- 파일 기반이면 `cat .ai/goals.yaml`로 즉시 디버깅 가능
- git으로 상태를 추적할 수 있음
- 데몬은 상태 관리, 포트 충돌, 프로세스 관리 복잡성 추가

### 왜 YAML인가?

- goals.yaml, config.yaml — 사람이 직접 편집. YAML이 가독성 좋음
- 핸드오프 — Markdown. AI와 사람 모두에게 자연스러운 형식

### 왜 규약을 도구로 강제하지 않는가?

- AI 코딩 에이전트는 CLAUDE.md 규약을 높은 확률로 따른다
- 규약을 어기더라도 `hast auto`의 outer loop가 안전망 역할
- 강제 도구는 학습 비용, 채택 장벽, 유지 비용을 동반
- 채택을 가로막는 가장 큰 적은 복잡성이다

---

## 18. Configuration & Validation (추가)

구현 시 가장 먼저 정의해야 할 “명확한 계약”은 설정 파일과 goal 스키마다.

### config.yaml 스키마

필수:
- `test_command` (string) — 테스트 실행 커맨드
- `ai_tool` (string) — AI 호출 커맨드, `{prompt}` 자리 필수

선택 (기본값):
- `timeout_minutes` (int, 기본 30)
- `max_retries` (int, 기본 3)
- `max_context_bytes` (int, 기본 120_000)  # 토큰 폭주 방지
- `ai_tools` (map<string,string>)

검증 규칙:
- `{prompt}` 자리 없으면 에러
- 음수/0 값은 에러 (timeout, max_retries, max_context_bytes)
- 알 수 없는 키는 경고로 출력하고 무시 (미래 호환)

### goals.yaml 스키마

필수:
- `goals` (list)
- 각 goal: `id`, `title`, `status`

선택:
- `children` (list of goals)
- `expect_failure` (bool)
- `allowed_changes` (list of glob patterns)
- `prompt_mode` ("adversarial")
- `mode` ("interactive")
- `tool` (string)

검증 규칙:
- `id`는 전체 트리에서 유일해야 함
- `status`는 {pending, active, done, blocked, dropped}만 허용
- `mode: interactive`는 auto 대상에서 제외
- `tool`은 `config.ai_tools`에 있으면 override, 없으면 에러

---

## 19. Safety & Correctness Details (추가)

### Allowed Changes 강제

`allowed_changes`가 있으면:

1. `git diff --name-only base_commit`으로 변경 파일 수집
2. glob 패턴과 매칭되지 않는 파일이 있으면:
   - classification: `failed`
   - reason: `changes outside allowed scope`
   - 롤백 후 재시도

### Handoff 판정 규칙

- 파일명은 `YYYY-MM-DD_HHMMSS.md` 형식
- 기준 커밋 이후 생성된 파일 중 **가장 최신**을 사용
- frontmatter에 `timestamp`, `status`, `goal_id` 없으면 무효
- status가 `blocked`면 실패가 아니라 “사람에게 넘김”으로 분류

### 타임스탬프 정책

- 파일명 기준: 로컬 타임존 `YYYY-MM-DD_HHMMSS`
- frontmatter: ISO 8601 + offset (`2026-02-09T14:30:00+09:00`)
- 동일 초에 여러 핸드오프 생성 시 `_2`, `_3` 접미사 허용

### 프롬프트 전달 안전성

긴 프롬프트를 안전하게 전달하기 위해:

1. 임시 파일에 prompt 저장
2. `ai_tool`에 `{prompt}`가 있으면 **쉘 이스케이프된 문자열**로 치환
3. `{prompt_file}`를 지원하면 파일 경로를 넘기는 방식 권장

권장 예시:
```
ai_tool: "claude -p {prompt_file}"
```

---

## 20. Concurrency & Crash Recovery (추가)

### 동시 실행 방지

`.ai/auto.lock` 파일을 사용:

```yaml
pid: 12345
started_at: "2026-02-09T14:30:00+09:00"
base_commit: "abc123"
```

- lock 존재 + pid 살아있음 → 즉시 종료 (이미 실행 중)
- lock 존재 + pid 없음 → 크래시로 판단, 복구 절차 진행

### 복구 절차 (보강)

1. uncommitted changes 존재 시
2. `base_commit`으로 롤백 가능하면 롤백
3. 불가능하면 상태 보존 + `blocked` 처리 + 설명 출력

---

## 21. Context Size & Determinism (추가)

컨텍스트는 AI 입력 길이 제한에 민감하므로 상한을 둔다.

### max_context_bytes 정책

기본 120KB. 초과 시:

1. `Rules`는 항상 유지
2. `Current Goal` 유지
3. `Previous Session` 요약만 남기고 상세 섹션은 축약
4. `Context Files`는 상위 5개까지만 유지

### 결정적 출력

- goals.yaml 순서와 규칙을 그대로 반영
- 동일 입력이면 항상 동일 출력 (파일 mtime 사용 금지)

---

## 22. CLI UX & Exit Codes (추가)

### 표준 출력 규칙

- `hast context`: 결과는 stdout, 오류는 stderr
- `--format json`: 기계 파싱용 (필드 고정)

JSON 예시:

```json
{
  "current_goal": {"id":"M4.3.2","title":"Strategy query","parent":"M4.3"},
  "previous_session": {"timestamp":"2026-02-09T14:30:00+09:00","status":"complete"},
  "task": ["Reflect 노드에서 STRATEGY 카테고리 쿼리"],
  "context_files": ["core/mind/nodes/reflect.py","core/memory/belief.py"],
  "rules": ["테스트 통과 후 핸드오프 작성", "..."]
}
```

### 종료 코드

- `hast init`: 0 성공, 1 실패
- `hast context`: 0 성공, 1 실패
- `hast auto`: 
  - 0: 모든 goal 성공
  - 1: blocked 또는 실패 발생

---

## 23. Test Strategy (추가)

### 단위 테스트

- goals 파서: 트리 구성, status 검증, id 유일성
- handoff 파서: frontmatter 검증, 최신 선택
- context 조립: 우선순위 적용, max_context_bytes 절삭

### 통합 테스트

- `hast init` → 파일 생성 확인
- `hast auto` dry-run → 프롬프트 출력 확인
- `allowed_changes` 위반 → 롤백 + 재시도 분기 확인

---

## Appendix A: Quick Start — 인터랙티브

```bash
# 1. 설치
pip install hast

# 2. 초기화
cd my-project
hast init

# 3. CLAUDE.md에 규약 추가 (hast init의 안내 참조)

# 4. 목표 정의 (.ai/goals.yaml 편집)
#   goals:
#     - id: M1
#       title: "User Auth"
#       status: active

# 5. AI 세션에 컨텍스트 제공
hast context | pbcopy   # 클립보드에 복사

# 또는
claude -p "$(hast context)"

# 6. AI가 작업 + 핸드오프 작성 (규약에 따라)

# 7. 다음 세션
hast context   # 이전 핸드오프 기반 컨텍스트 자동 조립
```

## Appendix B: Quick Start — 자동화

```bash
# 1. 설치 + 초기화 (Appendix A 참조)

# 2. 단일 goal 자동 실행
hast auto M1.1

# 3. 무슨 일이 벌어지는가?
#    hast auto가:
#      a. hast context로 프롬프트 조립 + 자동화 지시 추가
#      b. claude -p "$prompt" 실행
#      c. pytest 실행 → 통과 확인
#      d. .ai/handoffs/ 에 핸드오프 존재 확인
#      e. 실패 시 git reset --hard → 재시도 (최대 3회)

# 4. 전체 파이프라인 자동 실행
hast auto M1 --recursive

# 5. 프롬프트만 확인
hast auto M1.1 --dry-run

# 6. 판정 과정 확인
hast auto M1.1 --explain
```

## Appendix C: Workflow Pattern — 피쳐 파이프라인

hast가 강제하지 않지만, goals.yaml로 구현 가능한 TDD 워크플로우:

```yaml
goals:
  - id: F1
    title: "User Authentication"
    children:
      - id: F1.1
        title: "Interface design"
        mode: interactive           # auto에서 건너뜀
      - id: F1.2
        title: "Happy path tests"
        expect_failure: true        # 테스트 실패 = 정상 (RED)
      - id: F1.3
        title: "Implementation"
        allowed_changes: ["core/auth.py"]
      - id: F1.4
        title: "Edge case tests"
        tool: codex
        prompt_mode: adversarial
      - id: F1.5
        title: "Verification"      # 기본 설정 = 전체 검증
```

```bash
hast auto F1 --recursive
# F1.1: skip (interactive)
# F1.2: 테스트 작성 (expect_failure)
# F1.3: 구현 (allowed_changes 제한)
# F1.4: 적대적 테스트 (codex)
# F1.5: 전체 검증
```

> **이 문서는 구현 전 설계 문서입니다.**
> Phase 1부터 구현을 시작하면, 실전 피드백으로 설계를 수정합니다.
>
> Created: 2026-02-09
