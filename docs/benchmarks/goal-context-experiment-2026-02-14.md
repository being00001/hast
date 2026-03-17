# Goal-in-Context Experiment (2026-02-14)

## Question
Can `hast` execute concrete goals stably inside real project context, and can we observe/measure the loop behavior?

## Setup
- Tool: `/home/upopo/hast-bench/.venv/bin/hast`
- Workspace: `/home/upopo/hast-e2e`
- Repos:
  - `pallets/click` (small)
  - `astral-sh/uv` (large)
- Goal type: legacy single-goal flow (`hast auto <goal_id> --explain`)
- Runner: `LocalRunner` with deterministic worker script (`.ai/tools/fake_worker.py`)
- Test gate: deterministic shell check (`.ai/tools/check_goal.sh`)
- Guardrail: `allowed_changes` only to `docs/hast_experiments/*.md`

Raw results: `/home/upopo/hast-e2e/goal_context_experiment.json`

## Important Precondition Found
- `hast auto` requires clean working tree at start.
- If `.ai` setup changes are uncommitted, execution is blocked with:
  - `Error: working tree is dirty; commit or stash changes before hast auto`
- After adding setup commit, all scenarios executed as designed.

## Scenarios and Outcomes

| Scenario | Repo | Mode | Exit | Elapsed | Attempts | Final Status | Merge |
|---|---|---|---:|---:|---:|---|---|
| `click_success` | click | success | 0 | 1.880s | 1 | `done` (`merged`) | Yes |
| `click_retry_recover` | click | retry_recover | 0 | 2.223s | 2 | `done` (`merged`) | Yes |
| `uv_success` | uv | success | 0 | 2.825s | 1 | `done` (`merged`) | Yes |
| `uv_retry_recover` | uv | retry_recover | 0 | 3.269s | 2 | `done` (`merged`) | Yes |
| `click_scope_violation` | click | scope_violation | 1 | 2.226s | 2 | `blocked` | No |

## Evidence-Level Behavior

### Success path (`*_success`)
- evidence sequence:
  - `legacy: complete` (`action=advance`)
  - `merge: merged` (`action=advance`)
- merge commit observed:
  - `merge: <goal_id>`

### Retry-recover path (`*_retry_recover`)
- evidence sequence:
  - attempt 1: `legacy: failed-unknown` (`action=retry`, `failure_classification=impl-defect`)
  - attempt 2: `legacy: complete` (`action=advance`)
  - merge: `merged`
- result: automatic retry and recovery without manual intervention.

### Scope-violation path
- worker intentionally modified disallowed file (`README.md`).
- evidence sequence:
  - attempt 1: `legacy: failed` (`action=retry`)
  - attempt 2: `legacy: failed` (`action=escalate`)
- result:
  - no merge,
  - goal status moved to `blocked`,
  - worktree cleanup removed invalid output from target path.

## What This Proves
1. Goal loop stability:
   - deterministic success and deterministic recovery both worked in small and large repos.
2. Policy/guardrail effectiveness:
   - out-of-scope write attempts are blocked and escalated.
3. Auditable process:
   - run-level evidence captures attempt, classification, action, risk score.

## Limits of This Experiment
- Worker was deterministic script, not a stochastic external LLM.
- Task complexity was intentionally low-risk (doc artifact generation) to isolate orchestration behavior.
- It validates loop reliability and controls, not coding quality on complex feature implementation.

## Next Experiment (recommended)
1. Replace deterministic worker with real CLI model (`codex`/`gemini`/`claude`) on same scenarios.
2. Add one BDD goal (`spec_file` + RED/GREEN gate) per repo and compare:
   - retries,
   - failure classification accuracy,
   - completion latency.
3. Add mutation/security gate commands and measure false block vs useful block ratio.
