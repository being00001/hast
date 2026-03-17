# hast 공개 준비 설계

**날짜**: 2026-03-18
**버전**: 0.1.0 (pre-alpha)
**공개 범위**: GitHub 오픈소스 + PyPI 배포

## 목표

hast를 외부 사용자가 설치하고 사용할 수 있는 상태로 정리한다.

## 작업 영역

### 1. 네이밍 통일 (devf → hast)

- `DevfError` → `HastError` 리네임 (errors.py 정의 + 27개 import 지점)
- `.pre-commit-config.yaml`: `src/devf` → `src/hast` (4줄)
- `.github/workflows/docs-generate.yml`: `devf` → `hast` (3줄)
- docs 파일 내 "devf" 용어 치환 (design.md, roadmap.md, opus_guide.md, pain-points-and-desired-tools.md)

### 2. 보안 수정 (HIGH까지)

- `src/hast/core/runners/local.py`: DEBUG print 문 전부 제거
- `src/hast/utils/file_parser.py`: path traversal 검사를 `startswith` → `Path.relative_to()` 방식으로 교체
- `src/hast/core/config.py`: API 키에 `$` prefix 없으면 warning 로그 출력
- README.md에 Security 섹션 추가 (위협 모델 + untrusted repo 경고)

### 3. 패키징/메타데이터

- `LICENSE` 파일 추가 (MIT)
- `pyproject.toml`에 `authors`, `urls` 추가
- PyPI 이름 `hast` 충돌 확인
- `docs/tmp.md` 삭제
- `scripts/mock_langgraph_worker.py` 정리 판단
- `notes/` 정리

### 4. README 정비

- 설치 방법 (`pip install hast`) 추가/업데이트
- Security 섹션 (위협 모델 + untrusted repo 경고)
- Quick Start 검증

## 스코프 밖

- CONTRIBUTING.md, 이슈 템플릿
- MEDIUM 보안 항목 (파일 락, env var 경계, token 탈취 방어)
- CI/CD 인프라 셋업
- 커뮤니티 운영 도구

## 실행 순서

네이밍 → 보안 → 패키징 → README (의존성 순서)
