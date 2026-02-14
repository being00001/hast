# OSS Integration Plan (Python + Rust, Productivity 2x)

## Objective
Use proven open-source tools to close high-impact gaps faster than building custom equivalents.

Priority problems to solve:
1. Test quality cheating / weak RED-GREEN signal
2. Flaky + slow validation loops
3. Security blind spots in autonomous loops
4. Missing same-goal parallel spike execution
5. Noisy emergent goals without central admission control
6. Documentation drift and high manual doc maintenance cost

## Build vs Borrow Decision

### Borrow (now)
- `pre-commit`, `ruff`, `mypy`, `cargo fmt`, `clippy`
- `pytest-xdist`, `pytest-rerunfailures`, `pytest-randomly`
- `mutmut` (Python), `cargo-mutants` (Rust)
- `semgrep`, `gitleaks`, `trivy` (or `grype`)
- `ray` (spike orchestration)

### Keep in devf core (custom)
- goal/contract/state/evidence model
- retry/triage/risk policy logic
- decision ticket + validation matrix workflow
- orchestrator feedback loop
- emergent goal admission policy (propose vs activate separation)

## Integration Architecture

1. **Gate Adapter Layer** (devf-owned)
- Normalize external tool output into devf evidence fields:
  - `classification`
  - `failure_classification`
  - `action_taken`
  - `risk_score`

2. **Language-Aware Gate Profiles**
- Python profile:
  - lint/type: `ruff check .`, `mypy src`
  - test: `pytest -q -n auto`
  - mutation: `mutmut run --paths-to-mutate src`
- Rust profile:
  - lint/type: `cargo fmt --check`, `cargo clippy -- -D warnings`
  - test: `cargo test`
  - mutation: `cargo mutants --timeout 300`

3. **Security Gate Bundle**
- `gitleaks detect --no-git`
- `semgrep --config auto`
- `trivy fs .` (or `grype .`)

4. **Spike Parallel Runner**
- One goal, many alternatives (`A/B/C`) in isolated worktrees.
- Run via Ray tasks and compare decision evidence.

5. **Emergent Goal Admission Layer (Control Plane)**
- Any agent can submit **proposal** events (never direct goal activation).
- Only orchestrator/policy code can promote proposal -> active goal.
- Required proposal payload:
  - `category` (`risk`, `opportunity`, `tech_debt`, `workflow_friction`)
  - `impact`, `risk`, `confidence`, `effort_hint`
  - `why_now`, `evidence_refs`, `affected_goals`
- Admission gates:
  - dedupe (fingerprint + semantic similarity)
  - budget/WIP constraints
  - SLA rules (`risk=high` fast-track)
  - TTL expiry for stale low-signal proposals

6. **Documentation Control Plane (Auto Docgen)**
- Agents are not responsible for writing most docs manually.
- Trigger points:
  - merge to `main`
  - accepted decision update
  - goal lifecycle transition
- Auto-generated outputs (suggested):
  - `docs/generated/codemap.md`
  - `docs/generated/goal_traceability.md` (goal -> contract -> test -> commit)
  - `docs/generated/decision_summary.md`
  - `docs/generated/quality_security_report.md`
- Freshness policy:
  - stale generated docs -> warning by default
  - high-risk goals -> merge block if stale

7. **Event-Driven Async Swarm (Single Operator Control Plane)**
- Keep a single operating agent for policy, budget, and final transitions.
- Move execution to event-driven worker pull model:
  - append-only events: `goal_proposed`, `goal_claimed`, `goal_released`, `attempt_result`, `gate_result`, `escalated`
  - worker claim lease with TTL and renewal
  - reducer builds materialized views (`goal_views`, `operator_inbox`) for low-context control
- Core principle:
  - single decision authority remains centralized
  - execution throughput becomes decentralized and parallel
- Guardrails:
  - idempotency keys on event writes
  - per-goal lease ownership check before state transitions
  - deterministic reducer replay from event log

## Delivery Waves (BDD)

## Wave 6A: Quality Gate Bundle
- **RED**
  - Add tests that fail when quality commands are missing/skipped.
  - Add tests for Python+Rust mixed goals enforcing both stacks.
- **GREEN**
  - Add `.ai/templates/pre-commit-config.yaml` scaffold.
  - Add gate executor that runs configured commands and writes evidence rows.
- **REFACTOR**
  - Deduplicate gate command wiring with existing `language_profiles`.

Acceptance:
- `devf auto` blocks merge when lint/type gate fails.
- Evidence rows include per-gate command outcome.

## Wave 6B: Flaky/Parallel Test Reliability
- **RED**
  - Failing tests for flake detection routing (`env-flaky`).
- **GREEN**
  - Add optional profile flags:
    - `pytest -n auto`
    - rerun on fail for suspect flakes
    - randomized order when enabled
- **REFACTOR**
  - Tune retry policy mapping for flaky signatures.

Acceptance:
- repeated flaky failures classify as `env-flaky`, not `impl-defect`.

## Wave 6C: Mutation Quality Gate
- **RED**
  - Tests expecting mutation stage evidence and threshold enforcement.
- **GREEN**
  - Add optional mutation stage after RED/GREEN success.
  - Config thresholds:
    - `min_mutation_score_python`
    - `min_mutation_score_rust`
- **REFACTOR**
  - Cache mutation runs per changed module to control cost.

Acceptance:
- high-risk goals with low mutation score are blocked/escalated.

## Wave 6D: Security Gate
- **RED**
  - Tests expecting block on secret leak and high-risk findings.
- **GREEN**
  - Integrate `gitleaks + semgrep + trivy/grype` adapters.
  - Map findings into risk score bonus and policy action.
- **REFACTOR**
  - Add allowlist/ignore files with explicit evidence logging.

Acceptance:
- secrets always block.
- security finding summary appears in evidence and triage.

## Wave 6E: Parallel Spike Execution (Decision-first)
- **RED**
  - Tests expecting:
    - multiple alternative spikes run
    - comparison evidence written
    - winner auto-selected (or escalated)
- **GREEN**
  - Add `devf decision spike <decision_file> --parallel N`.
  - Execute alternatives in isolated worktrees via Ray.
  - Save outputs to `.ai/decisions/spikes/<decision_id>/`.
- **REFACTOR**
  - Integrate with existing `devf decision evaluate --accept`.

Acceptance:
- for high-uncertainty goals, accepted winner can be produced without manual branch juggling.

## Wave 7A: Emergent Goal Proposals
- **RED**
  - Tests expecting agents can create proposals but cannot modify `goals.yaml` directly.
  - Tests expecting malformed proposal payloads are rejected.
- **GREEN**
  - Add proposal inbox: `.ai/proposals/notes.jsonl`.
  - Add CLI:
    - `devf propose note ...` (worker/critic)
    - `devf propose list ...` (manager view)
  - Persist normalized proposal schema + evidence refs.
- **REFACTOR**
  - Reuse feedback fingerprinting/dedup primitives where possible.

Acceptance:
- proposal capture is cheap and distributed.
- direct goal activation from worker path is impossible.

## Wave 7B: Admission + Promotion Engine
- **RED**
  - Tests for dedupe, TTL expiry, and frequency thresholds.
  - Tests for WIP/budget cap enforcement.
- **GREEN**
  - Add policy file:
    - `.ai/policies/admission_policy.yaml`
  - Add command:
    - `devf propose promote --window 14 --max-active 5`
  - Promotion outputs:
    - `accepted` -> goal candidates
    - `deferred` -> wait for more evidence
    - `rejected` -> explicit reason code
- **REFACTOR**
  - Align score fields with orchestrator metrics pipeline.

Acceptance:
- noisy proposals do not flood active goals.
- high-risk proposals can bypass normal thresholds with traceable reason.

## Wave 7C: Dynamic Replan + Invalidation
- **RED**
  - Tests for automatic `obsolete/superseded/merged_into` transitions after key goals complete.
- **GREEN**
  - Add post-goal replan hook:
    - evaluate remaining goals against newly completed outcomes.
  - Add invalidation reason codes to evidence rows.
- **REFACTOR**
  - Ensure compatibility with dependency scheduler and decision gating.

Acceptance:
- goal graph remains fresh; stale goals are auto-retired.
- post-completion drift is visible and auditable.

## Wave 8A: Auto Docgen Baseline
- **RED**
  - Tests expecting generated docs to update after merge events.
  - Tests expecting stale-doc detection to emit warnings.
- **GREEN**
  - Add `devf docs generate` command.
  - Add CI hook for post-merge doc generation.
  - Generate baseline artifacts:
    - codemap
    - goal traceability
    - decision summary
    - quality/security report
- **REFACTOR**
  - Incremental generation (changed modules only) for speed.

Acceptance:
- developers/agents can focus on code + commit.
- generated docs update automatically without manual authoring.

## Wave 8B: WikiLink Vault Sync
- **RED**
  - Tests for broken wikilinks and orphan notes.
- **GREEN**
  - Add `.knowledge/` vault sync command:
    - `devf docs sync-vault`
  - Auto-generate wikilink pages:
    - `Goal/G_*.md`, `Decision/D_*.md`, `Run/R_*.md`, `Contract/C_*.md`
- **REFACTOR**
  - Add backlink cache and freshness index.

Acceptance:
- knowledge navigation improves without adding manual burden.
- vault remains synchronized with source-of-truth artifacts.

## Wave 9A: Event Bus + Shadow Mode
- **RED**
  - tests for append-only event schema validation and replay determinism.
  - tests for duplicate event idempotency handling.
- **GREEN**
  - add event writer/reader for `.ai/events/events.jsonl`.
  - emit events in parallel with current orchestrator flow (shadow mode only).
  - add reducer to derive:
    - `.ai/state/goal_views.yaml`
    - `.ai/state/operator_inbox.yaml`
- **REFACTOR**
  - normalize existing evidence fields into event payload references.

Acceptance:
- replaying event log reproduces identical derived state.
- shadow mode does not change production execution behavior.

## Wave 9B: Lease Claim + Worker Pull
- **RED**
  - tests for lease acquire/renew/release, expiration, and collision handling.
  - tests for stale lease recovery without duplicate merge actions.
- **GREEN**
  - implement claim protocol:
    - `devf swarm claim`
    - `devf swarm renew`
    - `devf swarm release`
  - workers pull tasks from derived state instead of central push assignment.
- **REFACTOR**
  - remove direct assignment coupling from orchestrator core path.

Acceptance:
- independent goals can run concurrently without central dispatch bottleneck.
- claim collision rate remains below target threshold.

## Wave 9C: Operator Inbox + Policy-Only Centralization
- **RED**
  - tests for policy-required escalations entering inbox.
  - tests for unauthorized transition attempts being rejected.
- **GREEN**
  - single operator agent consumes only:
    - escalations
    - budget exceptions
    - high-risk transition requests
  - add policy actions:
    - approve / reject / defer with reason codes.
- **REFACTOR**
  - compress inbox summary for low-context decisioning.

Acceptance:
- central operator handles policy decisions, not task-level scheduling.
- same-goal repeated failures decrease with faster asynchronous triage.

## Metrics (must improve)
- First-pass success rate: +20%+
- Same-failure-repeat ratio: -30%+
- Merge-time regression failures: -40%+
- Avg retries/goal: -25%+
- Decision-to-merge lead time (high uncertainty goals): -30%+
- Proposal-to-accepted ratio (signal quality): +25%+
- Goal invalidation latency after major completion: -50%+
- Active goal churn without evidence: 0
- Documentation freshness SLA: >95%
- Manual documentation touch ratio: <20%
- Goal queue wait p95: -30%+
- Claim collision rate: <2%
- Lease timeout recovery success: >99%
- Cost growth vs throughput growth ratio: <=0.7

## 2X Idea Backlog (Exploration)
- Context delta packing instead of full context replay each attempt
- Failure signature memory cache with known-good fix playbooks
- Fast->strong model escalation routing by risk/failure class
- Parallel pre-implementation spec/test decomposition workers
- Impacted-test-first loop with merge-time full regression gate
- Worker lease balancing and anti-starvation claim scheduling
- Operator inbox compression (Top-K high-impact escalations only)
- Move heavy gates to async background pipelines where safe
- Rule-based autofix stage before model invocation
- Goal archetype templates for repetitive implementation patterns

## Rollout Strategy
1. Start opt-in by config flags.
2. Promote to default only after two consecutive green weeks.
3. Keep kill switches per external gate:
   - `gates.quality.enabled`
   - `gates.mutation.enabled`
   - `gates.security.enabled`
   - `gates.spike.enabled`

## Operational Risks and Mitigations
- Tool runtime cost too high:
  - run heavy gates on high-risk goals only.
- False positives in security scanners:
  - allowlist with expiry + evidence trail.
- CI instability from plugin mix:
  - staged rollout, one wave per sprint.

## Immediate Next Sprint
1. Wave 6A implementation
2. Wave 6D minimal security baseline (`gitleaks` first)
3. Wave 6E spike runner skeleton (single machine, Ray local mode)
4. Wave 7A proposal inbox scaffold (`devf propose note/list`)
5. Wave 8B `.knowledge` vault sync + link integrity checks
6. Wave 9A event bus + reducer shadow mode

## Progress Log
- 2026-02-14: Wave 6A scaffold implemented in core:
  - gate required-check policy (`gate.required_checks`, `gate.fail_on_skipped_required`)
  - gate evidence details (`gate_checks`, `gate_failed_checks`) in run evidence rows
  - init template added: `.ai/templates/pre-commit-config.yaml`
- 2026-02-14: Wave 6D minimal security baseline implemented:
  - `gate.security_commands` config parsing/validation in `config.yaml`
  - gate executes security checks (named scanners + generic `security_check_n`)
  - required-check policy now composes with security checks (ex: `required_checks: ["gitleaks"]`)
- 2026-02-14: Wave 6E spike runner skeleton implemented:
  - new command: `devf decision spike <decision_file> --parallel N --backend {auto|thread|ray}`
  - isolates alternatives in dedicated worktrees, executes per-alt spike command, stores artifacts under `.ai/decisions/spikes/<decision_id>/<timestamp>/`
  - appends `decision_spike` rows to `.ai/decisions/evidence.jsonl` and links summary into ticket `evidence_refs`
- 2026-02-14: Wave 7A proposal inbox scaffold implemented:
  - new command group: `devf propose`
  - `devf propose note ...` appends normalized proposal rows to `.ai/proposals/notes.jsonl`
  - `devf propose list` provides manager-readable inbox view without mutating `goals.yaml`
- 2026-02-14: Wave 7B admission + promotion engine implemented:
  - new policy template: `.ai/policies/admission_policy.yaml`
  - new command: `devf propose promote --window 14 --max-active 5`
  - promotion output persists to `.ai/proposals/backlog.yaml` with `accepted|deferred|rejected` + reason codes
  - accepted proposals become managed goals under policy root (default `PX_2X`)
- 2026-02-14: Wave 7C dynamic replan + invalidation implemented:
  - post-merge replan hook auto-applies `obsolete|superseded|merged_into` transitions for pending/active goals
  - supports explicit completed-goal invalidation lists (`obsoletes`, `supersedes`, `merges`)
  - heuristic invalidation for duplicate proposal fingerprints (`duplicate_proposal_resolved`)
  - writes auditable invalidation evidence rows (`phase=replan`, `invalidation_reason_code`, `invalidated_by_goal`)
- 2026-02-14: Proposal signal metrics integrated into `devf metrics`:
  - proposal note volume (`proposal_notes`)
  - backlog distribution (`proposal_backlog_total`, `accepted`, `deferred`, `rejected`)
  - promotion count (`proposal_promoted`) and signal ratio (`proposal_accept_ratio`)
- 2026-02-14: Wave 8A auto docgen baseline implemented:
  - new command: `devf docs generate --window N [--warn-stale/--no-warn-stale]`
  - generates 4 artifacts under `docs/generated/`:
    - `codemap.md`
    - `goal_traceability.md`
    - `decision_summary.md`
    - `quality_security_report.md`
  - stale-doc detection emits warnings before refresh (warn-default policy; block mode pending)
  - post-merge trigger scaffold added: `.github/workflows/docs-generate.yml`
- 2026-02-14: Mermaid doc visualization integrated into doc automation:
  - `devf docs generate` now also scans markdown Mermaid blocks and renders SVG to `docs/generated/mermaid/`
  - new command: `devf docs mermaid --glob "docs/**/*.md" [--open-index]`
  - renderer dependency (`mmdc`) is optional; missing binary results in warnings, not hard failure
