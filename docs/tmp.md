# 피쳐별 반복 (→ design.md Appendix B + S2 GoalConfig + S3 expect_failure로 반영됨)

## 1. 피쳐 설계
인터페이스 + 계약 정의
함수 시그니처, 타입 힌트
기대 동작 명세 (입력 → 출력)
다른 모듈과의 의존성 정의
interface_N.md + handoff

## 2. 해피패스 테스트
— 구현 없이 스펙 기반으로
설계 기반으로 정상 동작 테스트 작성. 구현 안 봄.
전부 FAIL (RED) = 정상
tests/test_N.py

## 3. 구현
— "이 테스트들을 통과시켜"
Claude -p
코드 작성 + 정적 검증
테스트가 목표 (방향 이탈 최소화)
mypy, ruff 통과까지 같은 세션에서
다른 모듈 파일 수정 금지
core/module_N.py (GREEN 목표) + handoff

## 4. 엣지케이스 테스트
Codex (적대적 프롬프트)
"이 코드를 깨뜨려봐." 악의적 입력, 타이밍, 리소스 고갈, 동시성.
FAIL (RED) = 다시 구현(3으로 이동)
tests/test_N_edge.py

## 5. 검증 파이프라인
### 결정론적 자동화
5단계 검증
① 정적 검증 (mypy, ruff)
② 계약 검증 (스펙 vs 실제 인터페이스)
③ 유닛 테스트 (pytest — 해피패스 + 엣지케이스)
④ 통합 스모크 테스트 (docker compose up → 실제 실행)
⑤ 전체 회귀 테스트 (기존 테스트 전부 재실행)

### 실패 처리
🔄 실패 → 에러 로그 + 관련 파일 + 변경 diff 포함해서 수정 세션 진입
🛑 같은 에러 3회 반복 → 중단, 사람에게 넘김
✅ 전체 통과 → git commit + 다음 피쳐
