# hast + Being Integration Guide

Being의 executor/planner에 hast를 연결할 때 필요한 조치와 위험 완화 방법을 정리한다.

## 배경

- **Being**: 자율 에이전트. MindLoop(sense→reflect→plan→execute→record), 47개 인스턴스 속성, 20개 core 모듈.
- **hast**: Being 개발 세션 관리자. Goal 기반 자율 TDD/BDD 실행, `.ai/` 디렉토리에 메타데이터 생성.
- **통합 시나리오**: Being의 executor가 hast를 "개발 도구"로 호출하여 자기 코드를 자율 수정.

## 1. 컨텍스트 오염 방지

### 문제

Being의 MindLoop가 작업 디렉토리를 스캔할 때 hast가 생성한 `.ai/` 아티팩트를 Being의 코드/지식으로 오인할 수 있다.

### `.ai/` 아티팩트 전체 목록

| 경로 | 유형 | 생성 트리거 | 성장 패턴 |
|------|------|-----------|----------|
| `.ai/goals.yaml` | YAML | `hast plan`, `hast propose promote` | 덮어쓰기 |
| `.ai/config.yaml` | YAML | `hast init` (1회) | 정적 |
| `.ai/rules.md` | MD | 수동 작성 | 정적 |
| `.ai/plan_note.md` | MD | 수동 작성 | 정적 |
| `.ai/runs/<run_id>/evidence.jsonl` | JSONL | `hast auto` | 무한 증가 |
| `.ai/attempts/<goal_id>/attempt_N.yaml` | YAML | `hast auto` | 시도당 1파일 |
| `.ai/sessions/<goal_id>/*.md` | MD | `hast auto` | 실행당 1파일 |
| `.ai/handoffs/*.md` | MD | 수동/`hast handoff` | 핸드오프당 1파일 |
| `.ai/feedback/notes.jsonl` | JSONL | `hast feedback` | 무한 증가 |
| `.ai/feedback/backlog.yaml` | YAML | `hast feedback backlog` | 덮어쓰기 |
| `.ai/proposals/notes.jsonl` | JSONL | `hast propose note` | 무한 증가 |
| `.ai/proposals/backlog.yaml` | YAML | `hast propose promote` | 덮어쓰기 |
| `.ai/decisions/*.yaml` | YAML | `hast decision new` | 의사결정당 1파일 |
| `.ai/decisions/evidence.jsonl` | JSONL | `hast decision evaluate/spike` | 무한 증가 |
| `.ai/decisions/spikes/` | JSON+logs | `hast decision spike` | spike당 디렉토리 |
| `.ai/events/events.jsonl` | JSONL | Event Bus (auto/gate/queue) | 무한 증가 |
| `.ai/state/goal_views.yaml` | YAML | `hast events replay` | 덮어쓰기 |
| `.ai/state/operator_inbox.yaml` | YAML | `hast events replay` | 덮어쓰기 |
| `.ai/state/operator_actions.jsonl` | JSONL | `hast inbox act` | 무한 증가 |
| `.ai/protocols/outbox/*.json` | JSON | `hast protocol export` | 패킷당 1파일 (50-200KB) |
| `.ai/protocols/inbox/results.jsonl` | JSONL | `hast protocol ingest` | 무한 증가 |
| `.ai/security/audit.jsonl` | JSONL | Gate 보안 검사 | 무한 증가 |
| `.ai/immune/audit.jsonl` | JSONL | Immune 정책 평가 | 무한 증가 |
| `.ai/immune/grant.yaml` | YAML | `hast immune grant` | 덮어쓰기 |
| `.ai/queue/state.json` | JSON | `hast queue claim/release` | 덮어쓰기 |

### 필수 조치

#### Being 측 (core/mind, core/tools)

**A. 파일 스캐너에 `.ai/` exclude 추가**

Being의 tool이 코드를 읽거나 분석할 때 `.ai/` 하위를 제외해야 한다.
적용 위치: `core/tools/` 내 파일 탐색 로직, `core/mind/` 내 컨텍스트 수집 로직.

```python
HAST_METADATA_DIRS = {".ai"}

def should_skip(path: Path) -> bool:
    return any(part in HAST_METADATA_DIRS for part in path.parts)
```

**B. Hippocampus/Memory에 `.ai/` 내용 기록 방지**

Being의 기억 시스템이 `.ai/goals.yaml` 같은 파일 내용을 장기 기억에 저장하면,
이후 MindLoop가 hast의 개발 goal을 Being의 operational goal로 혼동할 수 있다.

조치: `hippocampus.remember()` 호출 시 `.ai/` 경로에서 유래한 내용을 태깅하거나 필터링.

**C. GoalStore와 hast goals의 네임스페이스 분리**

Being의 `core/goals/` 시스템과 hast의 `.ai/goals.yaml`은 완전히 별개의 목표 체계다.
Being의 planner가 `.ai/goals.yaml`을 자신의 goal로 읽지 않도록 명시적 분리 필요.

#### hast 측 (이 프로젝트)

**D. `.gitignore` 강화**

현재 Being의 `.gitignore`에는 `.ai/sessions/`, `.ai/handoffs/`, `.ai/attempts/`만 있다.
나머지 런타임 아티팩트도 추가해야 한다:

```gitignore
# hast runtime artifacts (append-only logs, never commit)
.ai/runs/
.ai/events/
.ai/feedback/
.ai/proposals/
.ai/decisions/spikes/
.ai/decisions/evidence.jsonl
.ai/protocols/
.ai/security/
.ai/immune/audit.jsonl
.ai/state/
.ai/queue/
.ai/auto.lock
.ai/.pre-commit-cache/
```

**E. JSONL rotation 정책**

9개의 append-only JSONL 파일이 무한 증가한다. 장기 운용 시:
- 디스크 사용량 증가
- Being의 파일 인덱서가 대용량 파일을 읽으려 시도할 때 토큰/메모리 폭발

권장: `.ai/archive/` 로테이션 유틸리티 추가. 기준: 파일 크기 > 5MB 또는 age > 30일.

**F. 메타데이터 마커 파일**

`.ai/.hast-metadata` 같은 마커를 두어 외부 도구가 "이 디렉토리는 코드가 아니라
개발 세션 메타데이터"임을 기계적으로 판별할 수 있게 한다.

## 2. 작업 공간 충돌 방지

### 문제

hast의 `auto --parallel`이 git worktree를 생성/삭제하고,
Being의 executor도 동일 repo에서 git 작업을 수행하면 상태 충돌 가능.

### 조치

| 시나리오 | 위험 | 조치 |
|----------|------|------|
| hast worktree 생성 중 Being이 `git status` 조회 | 낮음 | hast의 `auto.lock` 파일이 존재하면 Being은 git 쓰기 작업을 대기 |
| hast spike가 4개 worktree 동시 생성 | 중간 | Being의 executor가 worktree 목록을 인식하고 main만 작업하도록 제한 |
| Being이 코드 수정 후 hast가 같은 파일을 수정 | 높음 | 동시 쓰기 금지. Being의 execute_task와 hast auto를 순차 실행하거나, 파일 잠금 프로토콜 도입 |

### 권장 패턴: 순차 위임

```
Being MindLoop
  → plan: "login 기능 추가 필요"
  → execute: hast plan "Add login feature"  (hast가 goal 생성)
  → execute: hast auto G_login             (hast가 TDD 실행)
  → record: hast 결과를 Being 기억에 기록
  → (Being의 다음 cycle에서 다른 작업)
```

Being의 executor가 hast를 subprocess로 호출하고, 완료될 때까지 Being 자체는
동일 repo에 쓰기 작업을 하지 않는다.

## 3. LLM 호출 격리

### 문제

hast와 Being 모두 LLM API를 호출한다. API 키나 rate limit을 공유하면:
- 비용 추적이 불분명해짐
- rate limit 경합

### 조치

| 항목 | 방법 |
|------|------|
| API 키 | Being과 hast에 별도 API 키 할당 (또는 최소 별도 `x-request-id` 태깅) |
| 비용 추적 | hast의 evidence에 토큰 사용량이 기록됨. Being 측에서도 hast 호출을 `expense_tracker`에 기록 |
| Rate limit | hast의 `circuit_breakers.max_cycles_per_session`으로 폭주 방지. Being 측에서도 hast 호출 횟수에 예산 설정 |

## 4. 의미론적 경계

### goal 충돌

| Being의 goal | hast의 goal | 관계 |
|-------------|-------------|------|
| "login 기능 개선" (operational) | "G_login: Add login feature" (development) | Being이 hast goal을 생성하는 것. 1:1 매핑 |
| "시스템 안정성 유지" (survival) | 없음 | hast와 무관 |

Being의 planner가 "개발 작업이 필요하다"고 판단하면 → hast plan 호출 → hast goal 생성.
Being의 goal과 hast goal은 계층이 다르다: Being goal이 상위, hast goal이 하위 실행 단위.

### impact 필드 활용

hast의 goal에는 `impact: being | code | both` 필드가 있다.
- `being`: Being의 행동/능력이 바뀌는 변경 → Being의 자기 인식에 반영 필요
- `code`: 내부 구현만 바뀌는 변경 → Being 입장에서 투명
- `both`: 양쪽 모두 영향

Being의 record 단계에서 hast goal의 impact를 확인하고,
`being`이면 self_awareness/introspection에 변경 사실을 알린다.

## 5. 통합 체크리스트

### Being 프로젝트에서

- [ ] `core/tools/` 파일 탐색에 `.ai/` exclude 규칙 추가
- [ ] `core/mind/` 컨텍스트 수집에 `.ai/` exclude 규칙 추가
- [ ] `hippocampus.remember()` 에 `.ai/` 출처 필터 추가
- [ ] GoalStore가 `.ai/goals.yaml`을 읽지 않도록 확인
- [ ] executor에 hast CLI subprocess 호출 핸들러 추가
- [ ] `auto.lock` 파일 존재 시 git 쓰기 대기 로직
- [ ] hast 호출 비용을 `expense_tracker`에 기록
- [ ] hast goal의 `impact: being` 결과를 self_awareness에 반영

### hast 프로젝트에서

- [ ] Being repo용 `.gitignore` 템플릿 제공 (또는 `hast init` 시 자동 추가)
- [ ] JSONL rotation 유틸리티 구현
- [ ] `.ai/.hast-metadata` 마커 파일 규약 정의
- [ ] `hast auto` 종료 시 머신 판독 가능 결과 요약 출력 (Being의 record 단계 소비용)
