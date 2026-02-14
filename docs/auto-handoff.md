# Auto Handoff

## 현재 문제

AI가 매 세션 끝에 수동으로 `.ai/handoffs/` 파일을 작성해야 함.
- 프롬프트에 템플릿을 줘도 AI가 빼먹거나 형식을 틀리는 경우 많음
- handoff 없으면 다음 세션의 context가 빈약해짐
- evaluate()에서 handoff 유무를 체크하지만, 실패 시 재시도만 함 (직접 생성 안 함)

## 해결

`evaluate()` 성공 시 Python이 자동으로 handoff를 생성.

```python
# auto.py evaluate() 성공 경로에 추가
if outcome.success:
    handoff = auto_generate_handoff(root, goal, base_commit, test_output)
    write_handoff(root / ".ai" / "handoffs", handoff)
```

## auto_generate_handoff() 설계

입력: root, goal, base_commit, test_output
출력: 완성된 handoff 문자열

```
---
timestamp: "2026-02-10T12:00:00+09:00"
status: complete
goal_id: "V1.1"
---

## Done
V1.1 — Fix retry bug (자동 생성)

## Changed Files
(git diff --stat base_commit 결과)

## Test Results
(test_output 마지막 요약 줄)

## Next
(goals.yaml에서 다음 active/pending goal 자동 선택)

## Context Files
(changed_files 목록)
```

## 핵심 포인트

- git diff --stat + git log로 Done/Changed Files 자동 채움
- goals.yaml에서 다음 goal 자동 선택 → Next 섹션
- AI가 쓴 handoff가 있으면 그걸 우선 사용, 없을 때만 자동 생성
- Key Decisions는 AI만 알 수 있으므로 빈칸 또는 생략

## 예상 효과

- AI handoff 작성 턴 2~3개 절약
- handoff 누락으로 인한 context 손실 제거
- evaluate() 성공률에는 영향 없음 (성공 후 처리)
