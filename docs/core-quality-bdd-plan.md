# Core Quality BDD Plan

## Scope
- 목표: 자동 루프의 실패 원인/시도 이력을 추적 가능한 증거(evidence)로 남긴다.
- 방식: BDD (RED -> GREEN -> REFACTOR)

## Backlog
- [x] Q2-1: `run_auto` 실행 시 `.ai/runs/<run_id>/evidence.jsonl` 생성
- [x] Q2-2: 각 attempt 결과를 evidence로 기록 (classification, reason, diff_stat, changed_files)
- [x] Q2-3: test output 요약과 해시 저장 (재현 추적)
- [x] Q2-4: 테스트 추가 (`tests/test_evidence_bdd.py`)
- [x] Q3-1: goal 상태 머신 확장 (`planned`, `red_verified`, `green_verified`, `review_ready`, `merged`)
- [x] Q3-2: evidence와 상태 전이를 연결하는 정책 함수 추가
- [x] Q4-1: triage/retry/risk 정책 모듈 추가 (`triage.py`, `retry_policy.py`, `risk_policy.py`)
- [x] Q4-2: auto loop에 retry action 정책 연동 (`retry|escalate|block`)
- [x] Q4-3: evidence 확장 (`policy_version`, `failure_classification`, `action_taken`, `risk_score`)
- [x] Q4-4: `hast init` 정책 템플릿 생성 (`.ai/policies/*.yaml`)
- [x] Q4-5: `hast metrics` 명령 추가 (evidence 집계)
- [x] Q5-1: dependency scheduler 추가 (`depends_on` + DAG batch 실행)
- [x] Q5-2: `hast auto --parallel N` 실행 추가
- [x] Q5-3: role-based write scope guard (`owner_agent`)
- [x] Q5-4: 병렬 머지 충돌 방지(세션 로그 suffix)
- [x] Q5-5: pre-apply hard policy 추가 (변경 적용 전 경로 차단)
- [x] Q6-1: merge-train 제어 추가 (`merge_train.pre/post_merge_command`)
- [x] Q6-2: risk threshold 자동 차단 (`risk_policy.block_threshold`)
- [x] Q6-3: post-merge smoke 실패 시 auto rollback (`risk_policy.rollback_threshold`)
- [x] Q6-4: contract 기반 docs/security 업데이트 강제 (`required_docs`, `required_security_docs`)
- [x] Q7-1: feedback note 캡처 루프 추가 (`hast feedback note`)
- [x] Q7-2: evidence 기반 inferred note 생성 (`hast feedback analyze`)
- [x] Q7-3: manager 승격 backlog (`hast feedback backlog --promote`)
- [x] Q7-4: feedback 정책 템플릿 추가 (`feedback_policy.yaml`)
- [x] Q7-5: manager-only Codeberg issue publish (`hast feedback publish`)
- [x] Q8-1: one-shot productivity orchestrator (`hast orchestrate`)

## Current Sprint (Q2)
1. RED: evidence 파일/레코드 기대 테스트 추가
2. GREEN: evidence writer 구현 및 auto 루프 연결
3. REFACTOR: 코드 정리 및 문서 갱신

## Progress Log
- 2026-02-14: Q1(Contract 연동) 완료.
- 2026-02-14: Q2 시작. BDD로 evidence 기능 구현 예정.
- 2026-02-14: Q2 완료. evidence jsonl 기록/해시/시도 분류 저장 구현 + 테스트 통과.
- 2026-02-14: Q3 완료. `Goal.state` 스키마/파서 추가 + 상태 전이 정책(`state_policy`) 구현.
- 2026-02-14: evidence row에 `state_from/state_to/state_changed`를 추가하고 merge 이벤트까지 기록.
- 2026-02-14: Q4 완료. triage/retry/risk 정책 엔진 추가 및 auto retry 의사결정 연동.
- 2026-02-14: Q4 완료. init 정책 템플릿 + metrics 집계 커맨드 + 정책/메트릭 테스트 추가.
- 2026-02-14: Q5 완료. goal dependency scheduler/parallel 실행/role guardrail 구현 + 테스트 통과.
- 2026-02-14: Q5 완료. hard file-access policy(적용 전 차단) 구현 + 통합 테스트 추가.
- 2026-02-14: Q6 완료. merge-train/risk block/auto rollback 구현 + 리스크 머지 테스트 추가.
- 2026-02-14: Q6 완료. contract 기반 docs/security 업데이트 강제 규칙 추가 + 통합 테스트 추가.
- 2026-02-14: Q7 완료. feedback note/infer/backlog manager 루프 + 정책 템플릿 + CLI 추가.
- 2026-02-14: Q7 완료. Codeberg manager-only issue publisher 추가 + publish 테스트 추가.
- 2026-02-14: Q8 완료. feedback->goal 동기화 오케스트레이터(`hast orchestrate`) 추가.
