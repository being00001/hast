# devf 개선 제안 — Being 프로젝트 통합 경험에서

> 작성: Claude (Being 프로젝트 개발 세션, 2026-02-12)
> Being: 32모듈 178파일 15,000줄+ 자율 에이전트 프로젝트

---

## 1. 외부 codemap 지원 (P0)

**문제**: Being은 이미 `make docs`로 `.codemap.json`(모듈 의존성, 이벤트 맵, 부트스트랩 순서, 런타임 플로우)을 생성한다. devf는 이걸 무시하고 매번 자체 AST 분석을 돌린다. 중복 작업 + 정보 손실.

**제안**: `config.yaml`에 `codemap_path` 옵션 추가.
```yaml
codemap_path: ".codemap.json"  # 있으면 자체 분석 대신 이 파일 사용
```

**효과**:
- 프로젝트가 이미 가진 풍부한 메타데이터(이벤트 맵, 부트스트랩 순서 등)를 context에 포함 가능
- 대형 프로젝트에서 context 조립 속도 향상
- codemap 포맷은 프로젝트마다 다를 수 있으므로, `code_overview` 섹션에 raw string으로 삽입하는 게 가장 간단

---

## 2. CLAUDE.md fallback (P0)

**문제**: devf는 `.ai/rules.md`만 읽는다. Being 같은 프로젝트는 이미 `CLAUDE.md`에 상세한 작업 프로토콜이 있다. rules.md에 같은 내용을 중복 작성해야 해서 관리 부담.

**제안**: `_load_rules()`에 fallback 체인 추가.
```python
def _load_rules(root: Path) -> list[str]:
    for name in [".ai/rules.md", "CLAUDE.md"]:
        path = root / name
        if path.exists():
            return _parse_rules(path)
    return []
```

또는 `config.yaml`에서 경로 지정:
```yaml
rules_path: "CLAUDE.md"  # default: ".ai/rules.md"
```

---

## 3. Handoff ↔ Claude Code `/handoff` 통합 (P1)

**문제**: Claude Code에는 `/handoff` 스킬이 있어서 세션 종료 시 핸드오프 노트를 생성한다. 하지만 이 스킬은 devf의 `.ai/handoffs/` 형식을 모른다. 반대로 devf의 `generate_handoff()`는 Claude Code 세션 컨텍스트에 접근 못한다.

**제안**:
1. devf가 handoff 템플릿을 제공하는 CLI 옵션: `devf handoff --template` → YAML frontmatter + 섹션 뼈대 출력
2. Claude Code `/handoff` 스킬이 이 템플릿을 사용하도록 CLAUDE.md에 규칙 추가
3. 장기: devf가 Claude Code hook으로 등록되어 세션 종료 시 자동 handoff 생성

---

## 4. Goal ↔ 기존 문서 동기화 (P1)

**문제**: Being에는 `docs/ROADMAP.md`에 이미 상세한 마일스톤/작업 목록이 있다. `goals.yaml`을 별도로 유지하면 두 문서가 drift한다.

**제안 A**: `devf sync-goals` 명령 — ROADMAP.md의 마크다운 테이블/체크리스트를 파싱해서 goals.yaml로 동기화 (단방향)

**제안 B**: goals.yaml에 `source` 필드 추가
```yaml
goals:
  - id: "P1"
    source: "docs/ROADMAP.md#milestone-1"  # 참조용, 강제하지 않음
```

---

## 5. Interactive 모드 세션의 context 주입 개선 (P1)

**문제**: `devf auto`는 프롬프트를 자동 조립하지만, interactive 세션(Claude Code 직접 사용)에서는 `devf context | pbcopy` 후 수동 붙여넣기가 필요. 불편.

**제안**: Claude Code의 `/user:` 프롬프트 파일 또는 CLAUDE.md에 동적으로 context를 주입하는 방법.
- `devf context --inject-claude-md` → `.ai/context-snapshot.md`를 생성하고, CLAUDE.md에 `<!-- devf:context -->` 마커로 삽입
- 세션 시작 시 Claude Code가 이 파일을 자동으로 읽음
- 또는: Claude Code hook (PreToolUse, session start)에서 `devf context` 실행

---

## 6. Scope guard 실행 시점 (P2)

**문제**: `allowed_changes`는 현재 `devf auto`에서만 체크된다. interactive 세션에서는 내(AI)가 아무 파일이나 수정할 수 있다.

**제안**: `devf check-scope` 명령 — `git diff --name-only`를 `allowed_changes` glob과 대조해서 범위 이탈 경고.
- pre-commit hook으로 등록 가능
- `devf check-scope --goal P1.1` → 현재 변경 파일이 goal의 allowed_changes 안에 있는지 검증

---

## 7. Retry context에 기존 테스트 실패 목록 포함 (P2)

**문제**: Being은 기존 23개 테스트 실패가 있다 (이전 개발에서 남은 것). devf auto가 retry할 때 이 실패들을 "새 실패"로 오해할 수 있다.

**제안**: `config.yaml`에 `known_failures` 또는 `baseline_test_output` 옵션.
```yaml
known_failures:
  - "tests/test_cosmos_wallet.py::*"
  - "tests/test_meta_cognition.py::*"
```
또는 baseline 파일:
```yaml
test_baseline: ".ai/test-baseline.txt"  # pytest 출력 스냅샷
```

---

## 8. Context 크기 문제 — 대형 프로젝트 (P2)

**문제**: Being의 code overview만으로 120KB를 쉽게 초과. `max_context_bytes: 150_000`으로 올려도 빠듯.

**제안**:
- `context_strategy: "goal_scoped"` — goal의 `allowed_changes` + `test_files`에 해당하는 파일만 code overview 생성
- 현재는 전체 프로젝트를 분석한 뒤 트리밍하는데, 처음부터 scope 안의 파일만 분석하면 훨씬 효율적
- Being의 `.codemap.json`같은 외부 codemap이 있으면 overview 대신 그걸 포함 (§1과 연결)

---

## 9. `devf done <goal_id>` 명령 (P0)

**문제**: goal 완료 시 goals.yaml을 직접 열어서 `status: done`으로 수동 편집해야 한다. 번거롭고 오타 위험.

**제안**:
```bash
devf done P1.0                    # status → done
devf done P1.0 --next P1.1       # P1.0 done + P1.1 active로 전환
```

**동작**:
- goals.yaml에서 해당 id 찾아 `status: done` 설정
- `--next`가 있으면 다음 goal을 `active`로 전환
- children이 전부 done이면 parent도 자동으로 done 처리 (옵션)
- 존재하지 않는 goal_id면 에러

---

## 10. allowed_changes 경로 검증 (P0)

**문제**: goals.yaml에 `allowed_changes: ["core/survival/vitals.py"]`라고 잘못 쓰면 (실제 경로: `core/vitals.py`) warning만 나오고 context에 파일이 포함되지 않는다. 오타를 알아차리기 어렵다.

**제안**: `devf context` 실행 시 또는 별도 `devf validate` 명령으로 경로 검증.
```bash
devf validate          # goals.yaml의 모든 경로 glob을 실제 파일과 대조
```

**동작**:
- `allowed_changes`, `test_files`의 각 패턴에 대해 `glob.glob()` 실행
- 매칭 파일이 0개인 패턴이 있으면 **ERROR** (warning이 아니라)
- `devf context`에서도 동일 검증을 기본으로 실행 (매칭 0개 → stderr에 에러 + 비정상 종료)
- `--no-validate` 플래그로 스킵 가능

**효과**: 경로 오타로 인한 "왜 context에 파일이 안 들어가지?" 디버깅 시간 제거.

---

## 요약: 우선순위

| # | 제안 | 난이도 | 영향도 |
|---|------|--------|--------|
| 1 | 외부 codemap 지원 | 낮음 | 높음 |
| 2 | CLAUDE.md fallback | 낮음 | 높음 |
| 9 | `devf done` 명령 | 낮음 | 높음 |
| 10 | allowed_changes 경로 검증 | 낮음 | 높음 |
| 3 | Handoff 통합 | 중간 | 높음 |
| 4 | Goal ↔ ROADMAP 동기화 | 중간 | 중간 |
| 5 | Interactive context 주입 | 중간 | 높음 |
| 6 | Scope guard 명령 | 낮음 | 중간 |
| 7 | Known failures baseline | 낮음 | 중간 |
| 8 | Goal-scoped context 전략 | 중간 | 높음 |
