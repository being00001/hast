# Real LLM Worker Goal Experiment (2026-02-14)

## Goal
Verify whether `hast` can run a concrete goal stably in real project context using real CLI LLM workers (`codex`, `claude`, `gemini`), and measure behavior via evidence rows.

## Scope
- Workspace: `/home/upopo/hast-real-llm-e2e`
- Tool: `/home/upopo/hast-bench/.venv/bin/hast`
- Repositories:
  - Small: `pallets/click`
  - Large: `astral-sh/uv`
- Task (same across runs):
  - Create exactly one file under `docs/devf_real_llm/<provider>_<repo>.md`
  - Required content:
    - `# Devf Real LLM Experiment`
    - `status=ok`
  - `allowed_changes` restricted to that file
  - Test command: `bash .ai/tools/check_goal.sh`

## Raw Data
- First pass (includes config quoting failure for claude/gemini):
  - `/home/upopo/hast-real-llm-e2e/real_llm_goal_runs.json`
- Fixed pass (corrected YAML quoting):
  - `/home/upopo/hast-real-llm-e2e/real_llm_goal_runs_fixed.json`

## Important Failure Found (and Fixed)
- Initial `claude/gemini` runs failed before execution due invalid YAML quoting in `ai_tool`.
- Broken form:
  - `ai_tool: "claude ... -p "$(cat {prompt_file})""`
- Fixed form:
  - `ai_tool: 'claude ... -p "$(cat {prompt_file})"'`
  - same fix applied to gemini command.

This was an integration/config error, not model behavior.

## Final Measured Results (Valid Runs)

| Provider | Repo | Exit | Goal Status | Attempts | Elapsed |
|---|---|---:|---|---:|---:|
| codex | click | 0 | done/merged | 1 | 57.131s |
| codex | uv | 0 | done/merged | 1 | 82.776s |
| claude | click | 0 | done/merged | 1 | 59.442s |
| claude | uv | 0 | done/merged | 1 | 63.657s |
| gemini | click | 0 | done/merged | 1 | 38.213s |
| gemini | uv | 0 | done/merged | 1 | 35.112s |

Provider aggregates:
- codex: success 2/2 (100%), avg 69.95s
- claude: success 2/2 (100%), avg 61.55s
- gemini: success 2/2 (100%), avg 36.66s
- overall: success 6/6 (100%)

Additional blocked-run probe:
- `codex_click_guardrail`:
  - result: `blocked`
  - attempts: 2
  - action pattern: `retry -> escalate`
  - elapsed: 221.197s
  - data: `/home/upopo/hast-real-llm-e2e/real_llm_guardrail_run.json`

## Observed Loop Behavior (Evidence)
Common evidence pattern in all successful runs:
1. `phase=legacy`, `classification=complete`, `action_taken=advance`, `risk_score=25`
2. `phase=merge`, `classification=merged`, `action_taken=advance`, `risk_score=40`

Blocked probe evidence pattern (`codex_click_guardrail`):
1. attempt 1: `classification=failed-unknown`, `action_taken=retry`
2. attempt 2: `classification=failed-unknown`, `action_taken=escalate`
3. final goal status: `blocked`

Example evidence files:
- codex/click:
  - `/home/upopo/hast-real-llm-e2e/codex_click_success/.ai/runs/20260214T233818+0900/evidence.jsonl`
- claude/click:
  - `/home/upopo/hast-real-llm-e2e/claude_click_success_fixed/.ai/runs/20260214T234146+0900/evidence.jsonl`
- gemini/click:
  - `/home/upopo/hast-real-llm-e2e/gemini_click_success_fixed/.ai/runs/20260214T234358+0900/evidence.jsonl`

## Practical Notes
- `hast auto` enforces clean working tree before start; setup must be committed.
- In codex runs, model output reported that it could not commit due its own sandboxed git lock-file limitation, but `hast` still completed/merged because merge/commit control is orchestrator-side.
- The blocked guardrail probe failed due a malformed shell snippet in `test_command` (`/bin/sh: Syntax error: "(" unexpected`), not due scope policy rejection; this is still useful as a real failure-to-escalation trace but should not be interpreted as a scope-violation benchmark.

## Conclusion
- In this controlled goal class (single-file constrained write + deterministic test), `hast` executed stably across all three real LLM workers on both small and large repositories.
- Evidence rows gave auditable, machine-readable process traces for each run.
- Main operational fragility found was command-string/YAML integration, not orchestration logic.
