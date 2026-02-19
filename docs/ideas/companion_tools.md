# Hast Companion Tools Ideas
Being(자율 에이전트)과 Hast(개발 프레임워크)의 시너지를 위한 도구 아이디어 모음.

## 1. 🔮 Idea Incubator (아이디어 인큐베이터) [Selected]
- **컨셉**: '구현(Implementation)' 전 단계인 '발상(Ideation)'을 담당.
- **기능**:
  - 막연한 아이디어(예: "돈 벌고 싶어")를 입력받음.
  - 구체적인 요구사항, 리스크, 성공 기준을 분석.
  - Hast의 `decision` 티켓이나 `goals.yaml` 포맷으로 변환.
- **Being 시너지**: Being이 스스로 목표를 수립하고 구체화하는 '기획자' 역할을 수행하도록 지원.

## 2. 🧪 Chaos Monkey for Agents (에이전트 훈련소)
- **컨셉**: 에이전트의 회복 탄력성(Resilience) 테스트 도구.
- **기능**:
  - 의도적인 에러 주입 (네트워크 단절, 파일 권한 변경, API 500 에러 등).
  - Being이 당황하지 않고 `retry_policy`나 우회 전략을 쓰는지 검증.
- **Being 시너지**: '온실 속의 화초'가 아닌 야생에서도 생존 가능한 강인한 에이전트로 훈련.

## 3. 🕸️ Knowledge Graph Builder (지식 그래프 빌더)
- **컨셉**: 프로젝트의 의미론적 지도(Semantic Map) 구축.
- **기능**:
  - 코드(AST), 문서, 대화 로그를 분석하여 지식 그래프 생성.
  - "User와 Account의 관계는?", "이 코드는 왜 수정되었나?" 같은 질문에 답변.
- **Being 시너지**: 단순 코딩을 넘어 비즈니스 로직과 맥락을 이해하는 '아키텍트'로 성장.
