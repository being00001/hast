# CLAUDE.md

## Project Overview

devf is an AI-native development session manager — a minimal CLI tool (3 commands) for solo developers working with AI coding agents (Claude Code, Codex, Gemini CLI, etc).

Core value: **context assembly** (bridging stateless AI sessions) + **automation loop** (unattended multi-session execution).

Design philosophy: convention over tooling. Most session management is handled by CLAUDE.md rules and file conventions. The tool only does what conventions can't: assembling context from multiple files, and running an external automation loop.

## Architecture

```
devf = 3 commands + convention

devf init       .ai/ 디렉토리 + 템플릿 생성
devf context    핸드오프 + 목표 + 규칙 → 하나의 텍스트로 조립
devf auto       자동화 루프 (goal 순회, AI 호출, 검증, 재시도, 롤백)
```

Full design: `docs/design.md`

## Tech Stack

- Python 3.11+
- click (CLI)
- PyYAML (config)
- rich (optional, terminal output)
- No database, no daemon — files only

## File Structure

```
.ai/
├── config.yaml      # test_command + ai_tool (2 lines)
├── goals.yaml       # hierarchical goals (human-edited)
├── handoffs/        # session handoff notes (AI-written)
└── rules.md         # session conventions (referenced by CLAUDE.md)
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Code Style

- Type hints required
- Dataclasses for models (not Pydantic)
- Functions over classes where possible
- ~500 lines total target
