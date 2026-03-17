# hast 공개 준비 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hast를 GitHub + PyPI로 공개할 수 있도록 네이밍/보안/패키징/문서를 정리한다.

**Architecture:** devf→hast 네이밍 통일 후, 보안 취약점(HIGH) 수정, MIT 라이선스/메타데이터 추가, README Security 섹션 작성 순서로 진행. 각 작업 영역을 독립 커밋으로 분리.

**Tech Stack:** Python 3.11+, Click CLI, PyYAML, pytest

---

### Task 1: DevfError → HastError 리네임

**Files:**
- Modify: `src/hast/core/errors.py`
- Modify: `src/hast/__init__.py` (export 확인)
- Modify: src/hast 전체 (replace_all)
- Modify: tests 전체 (replace_all)

- [ ] **Step 1: errors.py 클래스 리네임**

```python
# src/hast/core/errors.py
"""Custom errors for hast."""


class HastError(Exception):
    """Raised for user-facing hast errors."""
```

- [ ] **Step 2: src/hast 전체에서 DevfError → HastError 치환**

Run: `find src/hast -name '*.py' -exec sed -i 's/DevfError/HastError/g' {} +`

- [ ] **Step 3: tests 전체에서 DevfError → HastError 치환**

Run: `find tests -name '*.py' -exec sed -i 's/DevfError/HastError/g' {} +`

- [ ] **Step 4: 치환 누락 확인**

Run: `grep -r "DevfError" src/ tests/`
Expected: 출력 없음

- [ ] **Step 5: 테스트 실행**

Run: `pytest tests/ -x -q`
Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/hast/core/errors.py src/hast/ tests/
git commit -m "refactor: rename DevfError to HastError"
```

---

### Task 2: pre-commit / CI 경로 수정

**Files:**
- Modify: `.pre-commit-config.yaml` (lines 15, 22-25)
- Modify: `.github/workflows/docs-generate.yml` (lines 24, 30, 33, 39, 47)

- [ ] **Step 1: .pre-commit-config.yaml 수정**

Line 15: `src/devf` → `src/hast`
Lines 22-25: `src/devf/core/` → `src/hast/core/`

- [ ] **Step 2: docs-generate.yml 수정**

Line 24: `Install devf` → `Install hast`
Line 30: `devf docs generate` → `hast docs generate`
Line 33: `devf docs sync-vault` → `hast docs sync-vault`
Line 39: `devf-generated-docs` → `hast-generated-docs`
Line 47: `devf-knowledge-vault` → `hast-knowledge-vault`

- [ ] **Step 3: 커밋**

```bash
git add .pre-commit-config.yaml .github/workflows/docs-generate.yml
git commit -m "fix: update devf references to hast in CI configs"
```

---

### Task 3: docs 내 devf 용어 치환

**Files:**
- Modify: `docs/design.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/opus_guide.md`
- Modify: `docs/pain-points-and-desired-tools.md`
- Modify: `docs/benchmarks/goal-context-experiment-2026-02-14.md`
- Modify: `docs/benchmarks/real-llm-worker-goal-experiment-2026-02-14.md`
- Delete: `docs/tmp.md`

- [ ] **Step 1: docs 파일들에서 devf → hast 치환**

Run: `find docs -name '*.md' -not -path 'docs/superpowers/*' -exec sed -i 's/devf/hast/g; s/Devf/Hast/g; s/DEVF/HAST/g' {} +`

- [ ] **Step 2: 치환 결과 확인 (오치환 없는지)**

Run: `grep -rn "hast" docs/design.md | head -5`
수동으로 문맥 확인

- [ ] **Step 3: docs/tmp.md 삭제**

Run: `rm docs/tmp.md`

- [ ] **Step 4: 커밋**

```bash
git add docs/
git commit -m "docs: rename devf references to hast"
```

---

### Task 4: 보안 수정 — DEBUG 로그 제거

**Files:**
- Modify: `src/hast/core/runners/local.py` (lines 51-54, 69-72)

- [ ] **Step 1: DEBUG print 문 제거**

`local.py`에서 다음 6줄 삭제:
- Line 51: `import sys`
- Line 52: `print(f"[DEBUG] command=...`
- Line 53: `print(f"[DEBUG] cwd=...`
- Line 54: `print(f"[DEBUG] prompt_len=...`
- Line 69: `print(f"[DEBUG] returncode=...`
- Line 70: `print(f"[DEBUG] stdout_len=...`
- Line 71: `print(f"[DEBUG] stdout=...`
- Line 72: `print(f"[DEBUG] stderr=...`

- [ ] **Step 2: 테스트 실행**

Run: `pytest tests/ -x -q -k "local or runner"`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add src/hast/core/runners/local.py
git commit -m "security: remove debug print statements from LocalRunner"
```

---

### Task 5: 보안 수정 — Path traversal 강화

**Files:**
- Modify: `src/hast/utils/file_parser.py` (line 83)
- Modify: `tests/test_file_parser.py` (path traversal 테스트 추가)

- [ ] **Step 1: 기존 path traversal 테스트 확인**

Run: `grep -n "traversal\|startswith\|relative_to" tests/test_file_parser.py`

- [ ] **Step 2: path traversal bypass 테스트 추가**

```python
def test_apply_rejects_prefix_bypass(tmp_path):
    """root=/tmp/app 일 때 /tmp/application/evil.py 를 차단해야 함."""
    root = tmp_path / "app"
    root.mkdir()
    # 'app' 접두사를 공유하는 sibling 디렉토리
    sibling = tmp_path / "application"
    sibling.mkdir()
    changes = [FileChange(path=f"../application/evil.py", content="pwned")]
    with pytest.raises(HastError, match="traversal"):
        apply_file_changes(root, changes)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/test_file_parser.py::test_apply_rejects_prefix_bypass -v`
Expected: FAIL (현재 startswith 로직이 이 케이스를 놓칠 수 있음)

- [ ] **Step 4: file_parser.py 수정**

`apply_file_changes()` line 81-87을 교체:

```python
        # 3. Jail check: Must be within root
        try:
            target_path.relative_to(root_abs)
        except ValueError:
            raise DevfError(
                f"Security Alert: Path traversal detected! "
                f"Attempted to write outside root: {change.path} -> {target_path}"
            )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_file_parser.py -v`
Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/hast/utils/file_parser.py tests/test_file_parser.py
git commit -m "security: fix path traversal bypass using Path.relative_to()"
```

---

### Task 6: 보안 수정 — API 키 평문 경고

**Files:**
- Modify: `src/hast/core/config.py` (_parse_model_config 함수)

- [ ] **Step 1: _parse_model_config에 경고 추가**

`config.py` line 137-139 뒤에 경고 로직 삽입:

```python
    import warnings
    if api_key is not None and not api_key.startswith("$"):
        warnings.warn(
            f"{field_name}.api_key: plaintext API key detected. "
            f"Use '$ENV_VAR_NAME' format to reference environment variables.",
            UserWarning,
            stacklevel=2,
        )
```

- [ ] **Step 2: 테스트 실행**

Run: `pytest tests/test_config.py -x -q`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add src/hast/core/config.py
git commit -m "security: warn when plaintext API key is used in config"
```

---

### Task 7: LICENSE 파일 + pyproject.toml 메타데이터

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml`

- [ ] **Step 1: MIT LICENSE 파일 생성**

표준 MIT 라이선스 텍스트, copyright holder: hast contributors

- [ ] **Step 2: pyproject.toml에 메타데이터 추가**

```toml
[project.urls]
Homepage = "https://github.com/being00001/hast"
Repository = "https://github.com/being00001/hast"
Issues = "https://github.com/being00001/hast/issues"
```

- [ ] **Step 3: PyPI 이름 충돌 확인**

Run: `pip index versions hast 2>/dev/null || curl -s https://pypi.org/pypi/hast/json | head -5`

충돌 시 대안 이름 논의 필요.

- [ ] **Step 4: 커밋**

```bash
git add LICENSE pyproject.toml
git commit -m "chore: add MIT license and project metadata"
```

---

### Task 8: README Security 섹션 + 정리

**Files:**
- Modify: `README.md`
- Delete: `notes/being-integration-feedback.md` + `notes/` 디렉토리

- [ ] **Step 1: README.md에 Security 섹션 추가**

Quick Start 아래에 추가:

```markdown
## Security

hast executes commands defined in `.ai/config.yaml` (such as `ai_tool`, `test_command`).
**Never run `hast auto` in a repository with an untrusted `.ai/` directory.**

If you clone a repository that already contains `.ai/config.yaml`, review its contents before running hast commands.
```

- [ ] **Step 2: README.md에 Installation 섹션 추가/업데이트**

```markdown
## Installation

```bash
pip install hast
```
```

- [ ] **Step 3: notes/ 정리**

Run: `rm -rf notes/`

- [ ] **Step 4: scripts/mock_langgraph_worker.py 정리**

Run: `rm -rf scripts/`

- [ ] **Step 5: 커밋**

```bash
git add README.md
git rm -r notes/ scripts/
git commit -m "docs: add security section, clean up notes and scripts"
```

---

### Task 9: 최종 검증 + push

- [ ] **Step 1: 전체 테스트**

Run: `pytest tests/ -x -q`
Expected: 전체 PASS

- [ ] **Step 2: devf 잔존 확인**

Run: `grep -rn "devf\|DevfError" src/ tests/ .pre-commit-config.yaml .github/ --include='*.py' --include='*.yaml' --include='*.yml'`
Expected: 출력 없음 (superpowers 계획 문서 제외)

- [ ] **Step 3: git status 확인 후 push**

Run: `git status && git push`
