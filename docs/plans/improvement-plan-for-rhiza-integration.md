# HAST 개선 계획 — Rhiza 통합 준비

## 배경

Rhiza (Being의 자율 코드 개선 시스템)와 통합하여 Being 코드베이스의 닫힌 개선 루프를 만들기 위한 HAST 측 개선 계획.

Rhiza가 HAST에서 필요로 하는 것:
1. AST 기반 정적 분석 (✅ 있음)
2. 보안 스캔 게이트 (✅ 있음)
3. 변경 영향도 분석 (✅ 있음)
4. 관련 테스트 탐지 (✅ 있음)
5. 복잡도 메트릭 (✅ 있음)
6. Dead code 탐지 (✅ v1 완료)
7. 테스트 커버리지 측정 (✅ v1 완료)

## Phase 1: Dead Code 탐지 — ✅ v1 완료

### 목표
사용되지 않는 함수, 클래스, import를 탐지하여 Rhiza가 기술부채 후보를 자동 발견할 수 있게 한다.

### 구현 완료 (v1)
- 미사용 import 탐지 (AST의 Import/ImportFrom 노드 vs 실제 사용)
- 미사용 top-level 함수/클래스 탐지 (파일 내 + cross-module)
- `__init__.py` re-export, `__all__`, decorator 등 false positive 처리
- `(module, name)` 튜플 기반 cross-module import 매칭
- 확신도(confidence): `high` (public, static proof) / `medium` (private, heuristic)
- 결과: `list[DeadCodeEntry]` — 파일, 심볼명, 유형(function/class/import), 확신도

### API
```python
def find_dead_code(root: Path, symbol_map: SymbolMap | None = None) -> list[DeadCodeEntry]
```

### 위치
- 구현: `src/hast/utils/codetools.py`
- 테스트: `tests/test_dead_code.py` (20 tests)

### 명시적 제외 (v2)
- 동적 참조: `getattr()`, plugin registry, `entry_points`, `__subclasses__()`
- 메서드 단위 dead code (클래스 내부 미사용 메서드)

## Phase 2: 테스트 커버리지 측정 — ✅ v1 완료

### 목표
변경된 파일/함수의 테스트 커버리지를 측정하여 Rhiza Verify 단계에서 "커버리지 하락 없음"을 게이트로 사용할 수 있게 한다.

### 구현 완료 (v1)
- `coverage.py` 서브프로세스 실행으로 커버리지 데이터 수집
- 변경 파일 범위의 커버리지에 집중 (`target_files` 파라미터)
- JSON 리포트 파싱 → `CoverageReport` (per-file + overall %)

### API
```python
def measure_coverage(
    root: Path,
    target_files: list[str] | None = None,
    test_command: str | None = None
) -> CoverageReport
```

### 위치
- 구현: `src/hast/utils/coverage.py`
- 테스트: `tests/test_coverage_measure.py` (4 tests)

### 명시적 제외 (v2)
- 함수 단위 커버리지 (파일 단위만)
- 변경 전/후 비교 (`CoverageDelta`)
- `impact_analysis()`와 결합

## Phase 3: Rhiza 통합 인터페이스 안정화

### 목표
Rhiza가 호출할 HAST 함수들의 인터페이스를 안정적으로 유지.

### 체크리스트
- [ ] `build_symbol_map()` 반환 타입 안정화
- [x] `find_dead_code()` API 확정
- [x] `measure_coverage()` API 확정
- [ ] `compare_coverage()` API 확정
- [ ] `complexity_check()` 반환 타입을 구조체로 (현재 `list[str]`)
- [ ] 외부 codemap 경로 지원 (`codemap_path` config 옵션)
- [ ] Being의 `.codemap.json`을 HAST SymbolMap으로 변환하는 어댑터

## v2 로드맵

1. **메서드 단위 dead code** — 클래스 내부 미사용 메서드 탐지
2. **함수 단위 커버리지** — `FileCoverage` → `FunctionCoverage` 확장
3. **`CoverageDelta`** — before/after 커버리지 비교
4. **CLI 커맨드** — `hast dead-code`, `hast coverage`
5. **`ComplexityReport` 구조체** — `complexity_check()` 반환 타입 개선
6. **`.codemap.json → SymbolMap` 어댑터** — Being 연동
7. **`HastError` 에러 코드 체계** — Rhiza에 구조화된 에러 반환

## 우선순위

1. ~~**Dead code 탐지**~~ ✅
2. ~~**커버리지 측정**~~ ✅
3. **인터페이스 안정화** — 통합 시 깨지지 않도록

## 참고
- Rhiza 레포: `~/rhiza`
- Being 레포: `~/being`
- Rhiza 개선 계획: `~/rhiza/docs/plans/improvement-plan-closed-loop.md`
- 상세 구현 계획: `docs/superpowers/plans/2026-03-16-rhiza-integration-deadcode-coverage.md`
- 통합은 HAST/Rhiza 양쪽 개선 후 별도 세션에서 진행
