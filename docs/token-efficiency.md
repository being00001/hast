# devf auto 토큰 효율·속도·인지부하 분석

> `devf auto`의 AI 세션이 소비하는 턴과 토큰을 분석하고,
> Python이 미리 계산할 수 있는 것들을 식별하여 개선안을 정리한다.

---

## 현황: AI 세션의 턴 소비 구조

전형적인 `devf auto` 한 세션 (1 goal, 1 attempt):

| 단계 | 소요 턴 | 토큰 (approx) | 성격 |
|------|---------|---------------|------|
| 프롬프트 읽기/이해 | 1 | ~4K input | 필수 |
| 코드베이스 탐색 (구조 파악) | 3-5 | ~15K | **낭비** |
| 대상 파일 읽기 | 3-5 | ~10K | **낭비** |
| 관련 테스트 파악 + 읽기 | 2-3 | ~5K | **낭비** |
| 실제 코드 작성 | 2-3 | ~3K output | 핵심 |
| 테스트 실행/디버깅 | 2-4 | ~5K | 필수 |
| 핸드오프 작성 | 2-3 | ~2K output | **낭비** |
| **합계** | **~15-23턴** | **~44K** | |

핵심 작업(코드 작성 + 테스트)은 4-7턴. 나머지 10-15턴이 "이해하기" + "행정 작업"에 소비된다.

재시도 포함 시 (max_retries=3):
- 최악: ~60턴, ~130K 토큰
- 평균: ~30턴, ~70K 토큰

---

## 문제 1: 코드베이스 맹탐색

### 증상

AI가 프롬프트를 받으면 가장 먼저 하는 일이 "이 프로젝트가 뭐지?"를 파악하는 것이다.
`allowed_changes: [src/devf/core/context.py]`라고 알려줘도, AI는:
1. 프로젝트 구조 탐색 (ls, glob) — 1-2턴
2. context.py 읽기 — 1턴
3. context.py가 import하는 모듈 추적 — 1-2턴
4. 관련 테스트 파일 찾기 — 1턴
5. 테스트 파일 읽기 — 1턴

이 5-7턴 동안 AI가 얻는 정보는 전부 Python이 미리 계산할 수 있는 것들이다.

### 근본 원인

`build_prompt()`가 "무엇을 해야 하는지"만 알려주고, "어떤 코드를 다루는지"는 알려주지 않는다.
AI에게 지도 없이 목적지만 알려주는 셈이다.

### 해결안: Pre-read 대상 파일 포함

`build_prompt()`에서 `allowed_changes` 파일들의 실제 소스 코드를 프롬프트에 포함한다.

```
## Target Files

### src/devf/core/context.py (460 lines)
```python
(파일 전문)
```‎
```

**기대 효과**: 파일 읽기 턴 3-5개 → 0. 총 토큰은 동일하거나 감소 (AI가 어차피 읽을 내용).
**추가 고려**: `max_context_bytes` 제한 내에서 파일 크기에 따라 포함 여부 결정.

---

## 문제 2: 테스트 파일 탐색

### 증상

AI가 "이 파일의 테스트가 어디있지?"를 매번 grep/find로 찾는다.
`tests/test_context.py`가 `context.py`의 테스트라는 건 import 관계를 보면 바로 알 수 있는데,
AI는 이걸 매번 2-3턴에 걸쳐 탐색한다.

### 근본 원인

프롬프트에 "관련 테스트"에 대한 정보가 없다. `allowed_changes`는 소스 파일만 명시하고,
그 파일의 테스트가 어디인지는 AI가 스스로 찾아야 한다.

### 해결안: Import 기반 테스트 매핑

`build_import_map()`으로 `source_file → test_file` 매핑을 계산하여 프롬프트에 포함한다.

```
## Related Tests
- src/devf/core/context.py → tests/test_context.py (12 tests)
  Run: pytest tests/test_context.py -v

### tests/test_context.py
```python
(테스트 파일 전문)
```‎
```

**기대 효과**: 테스트 탐색 2-3턴 → 0. AI가 기존 테스트 패턴을 보고 일관된 스타일로 새 테스트 작성.

---

## 문제 3: 재시도 시 컨텍스트 손실

### 증상

AI가 실패하면 `reset_hard` 후 **동일한 프롬프트**로 다시 시작한다.
왜 실패했는지, 어떤 접근을 시도했는지 전혀 전달되지 않는다.

결과:
- 같은 실수를 반복 (테스트 실패 → 같은 코드 → 같은 실패)
- 성공했던 부분까지 다시 작성 (partial progress 소실)
- 3회 재시도 후 blocked → 사람이 개입해야 함

### 근본 원인

`run_auto()`의 재시도 루프가 `evaluate()`의 결과를 다음 `build_prompt()`에 전달하지 않는다.
실패 유형(테스트 실패, scope 위반, 무변경)과 구체적 에러 메시지가 프롬프트에 포함되지 않는다.

### 해결안: 재시도 프롬프트에 실패 컨텍스트 추가

```
## Previous Attempt (FAILED — attempt 1/3)
Classification: tests failed
Reason: tests failed

Test output (last 50 lines):
  FAILED test_context.py::test_trim_code_overview_first
  AssertionError: assert 'Code Overview' not in result
  ...

Do NOT repeat the same approach. Analyze the failure and try a different strategy.
```

**기대 효과**: 재시도 성공률 향상. 평균 재시도 3회 → 1-2회. 총 세션 수 자체가 줄어듦.

---

## 문제 4: 핸드오프 수동 작성

### 증상

프롬프트에 핸드오프 템플릿(~20줄)을 포함하고, AI에게 "이 템플릿으로 핸드오프를 작성하라"고 요구한다.
AI는 이를 위해 2-3턴을 소비하고, 포맷을 실수하기도 한다.

한편 `devf handoff` 커맨드가 이미 git 데이터에서 핸드오프를 자동 생성할 수 있다.

### 근본 원인

`build_prompt()`가 핸드오프 작성을 AI의 책임으로 지정하고 있다.
`evaluate()` 성공 후 자동 생성하면 AI는 이 작업을 할 필요가 없다.

### 해결안: evaluate() 성공 시 핸드오프 자동 생성

1. `build_prompt()`에서 핸드오프 템플릿 섹션 제거
2. `evaluate()` 또는 `run_auto()` 성공 시 `generate_handoff()` 호출
3. AI의 프롬프트는 "테스트 실행 → 커밋"만 지시

```
작업 완료 후:
1. 테스트 실행: pytest
2. 통과하면 커밋: {type}({goal_id}): {description}
   (핸드오프는 자동 생성됩니다)
```

**기대 효과**: 프롬프트 ~500토큰 축소 + AI 턴 2-3개 절약 + 핸드오프 품질 일관성 보장.

---

## 문제 5: 무차별 컨텍스트 주입

### 증상

`code_structure_snapshot`이 전체 프로젝트 구조를 프롬프트에 포함한다.
파일이 20개일 때 ~40줄, 100개면 ~200줄. 대부분 현재 goal과 무관하다.

예: V1.3(context.py 리팩토링)을 작업할 때, `codetools.py`, `handoff.py`, `session.py`의
구조 정보는 불필요하다.

### 근본 원인

`code_structure_snapshot()`이 `allowed_changes`를 고려하지 않는다.
전체 프로젝트를 스캔한 결과를 그대로 프롬프트에 넣는다.

### 해결안: Goal-scoped context pruning

`allowed_changes` 파일 + 그 파일의 importer만 code overview에 포함한다.

```
## Code Overview (goal scope)

src/devf/core/context.py (460 lines)
  class ContextData (7 fields), fn build_context_data(), fn render_plain(), ...
  ← imported by: src/devf/core/auto.py, src/devf/cli.py

src/devf/core/auto.py (370 lines)
  fn build_prompt(), fn evaluate(), fn run_auto()
```

전체 20개 파일 대신 관련 2-3개만 → code overview 토큰 70% 감소.

---

## 종합 임팩트 추정

| # | 문제 | 해결안 | 턴 절감 | 토큰 절감 | 난이도 |
|---|------|--------|---------|-----------|--------|
| 1 | 코드 맹탐색 | Pre-read 대상 파일 | -5턴 | ±0 (재배치) | 낮음 |
| 2 | 테스트 탐색 | Import 기반 매핑 | -3턴 | ±0 (재배치) | 중간 |
| 3 | 재시도 컨텍스트 손실 | 실패 정보 전달 | -3~6턴 | -30% | 낮음 |
| 4 | 핸드오프 수동 작성 | 자동 생성 | -3턴 | -10% | 낮음 |
| 5 | 무차별 컨텍스트 | Goal-scoped pruning | -1턴 | -40% context | 중간 |

### Before vs After

|  | Before | After |
|--|--------|-------|
| 1 attempt | ~20턴, ~44K tokens | ~7턴, ~30K tokens |
| 3 retries (worst) | ~60턴, ~130K tokens | ~12턴, ~45K tokens |
| 재시도 필요 빈도 | ~50% | ~20% (추정) |

**총 효율**: 턴 기준 ~5-7x, 토큰 기준 ~3x, 재시도 포함 시 ~7-8x.

---

## 우선순위 추천

구현 난이도와 효과를 고려한 순서:

1. **핸드오프 자동 생성** — 이미 `generate_handoff()` 코드가 있어서 가장 빠름
2. **Pre-read 대상 파일** — 가장 큰 단일 턴 절감 (5턴)
3. **재시도 실패 컨텍스트** — 재시도 비용을 절반으로
4. **테스트 매핑** — 2번과 같은 원리의 확장
5. **Goal-scoped pruning** — 마무리 최적화
