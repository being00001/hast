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

### Keep in hast core (custom)
- goal/contract/state/evidence model
- retry/triage/risk policy logic
- decision ticket + validation matrix workflow
- orchestrator feedback loop
- emergent goal admission policy (propose vs activate separation)

## Integration Architecture

1. **Gate Adapter Layer** (hast-owned)
- Normalize external tool output into hast evidence fields:
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
- `hast auto` blocks merge when lint/type gate fails.
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
- **Status (2026-02-15): Baseline Complete**
  - `gate.security_commands` and required-check composition are operational.
  - Security policy bundle is supported via `.ai/policies/security_policy.yaml`:
    - scanner toggles/commands (`gitleaks`, `semgrep`, `trivy`, `grype`)
    - dependency scanner mode (`dependency_scanner_mode: either|all`)
    - missing tool behavior (`fail_on_missing_tools: true|false`)
- **Status (2026-02-15): Hardening v1 Implemented**
  - Scanner findings now map into explicit risk-score bonuses and policy action controls:
    - `security_failed_check_bonus`
    - `security_missing_tool_bonus`
    - `security_expired_ignore_bonus`
    - `security_force_block_on_failed_checks`
    - `security_force_block_on_missing_tools`
  - Allowlist/ignore rules with expiry are supported in `security_policy.yaml`:
    - `ignore_rules[].{id,checks,pattern,reason,expires_on}`
    - applied/expired ignore events are logged to `audit_file` (default `.ai/security/audit.jsonl`)
- **Next Hardening**
  - Map tool-native severity levels (ex: critical/high) into finer-grained policy actions.

Acceptance:
- secrets and required security checks block when configured as required checks.
- security gate summary is emitted in gate/evidence artifacts.

## Wave 6E: Parallel Spike Execution (Decision-first)
- **RED**
  - Tests expecting:
    - multiple alternative spikes run
    - comparison evidence written
    - winner auto-selected (or escalated)
- **GREEN**
  - Add `hast decision spike <decision_file> --parallel N`.
  - Execute alternatives in isolated worktrees via Ray.
  - Save outputs to `.ai/decisions/spikes/<decision_id>/`.
- **REFACTOR**
  - Integrate with existing `hast decision evaluate --accept`.

Acceptance:
- for high-uncertainty goals, accepted winner can be produced without manual branch juggling.

## Wave 7A: Emergent Goal Proposals
- **RED**
  - Tests expecting agents can create proposals but cannot modify `goals.yaml` directly.
  - Tests expecting malformed proposal payloads are rejected.
- **GREEN**
  - Add proposal inbox: `.ai/proposals/notes.jsonl`.
  - Add CLI:
    - `hast propose note ...` (worker/critic)
    - `hast propose list ...` (manager view)
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
    - `hast propose promote --window 14 --max-active 5`
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
  - Add `hast docs generate` command.
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
    - `hast docs sync-vault`
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
    - `hast queue claim`
    - `hast queue renew`
    - `hast queue release`
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

## Immediate Next Sprint (Updated 2026-02-15)
1. Wave 6D hardening:
   - map tool-native severity levels into finer policy actions
   - add policy presets for stricter CI vs local iteration modes
2. Wave 6E hardening:
   - robust parallel execution defaults for mixed local/CI environments
   - stronger winner auto-accept safety policies
3. Wave 7 proposal/admission UX polish:
   - improve operator triage views for `accepted|deferred|rejected`
   - reduce noise with better dedupe defaults
4. Wave 8B `.knowledge` vault sync + link integrity checks
5. Wave 10A external orchestrator pilot hardening (LangGraph/OpenHands)

## Progress Log
- 2026-02-14: Wave 6A scaffold implemented in core:
  - gate required-check policy (`gate.required_checks`, `gate.fail_on_skipped_required`)
  - gate evidence details (`gate_checks`, `gate_failed_checks`) in run evidence rows
  - init template added: `.ai/templates/pre-commit-config.yaml`
- 2026-02-15: Wave 6A quality gate bundle operationalized:
  - repository-level `.pre-commit-config.yaml` added (ruff + mypy + pytest + conditional Rust hooks)
  - CI workflow added: `.github/workflows/quality-gates.yml`
  - CI runs both `pre-commit` and `pre-push` stages to enforce local hook parity
- 2026-02-15: Wave 6B flaky/parallel reliability bundle implemented:
  - `gate.pytest_*` options added:
    - `pytest_parallel`, `pytest_workers`, `pytest_reruns_on_flaky`, `pytest_random_order`
  - pytest command augmentation shared across auto/gate paths (`-n`, `--random-order`, `--reruns`)
  - suspect flaky failures trigger rerun flow and preserve `env-flaky` routing signals
- 2026-02-15: Wave 6C mutation quality gate implemented:
  - `gate` mutation options added:
    - `mutation_enabled`, `mutation_high_risk_only`
    - `mutation_python_command`, `mutation_rust_command`
    - `min_mutation_score_python`, `min_mutation_score_rust`
  - gate stage now enforces mutation score thresholds per language
  - high-risk filtering defaults to `goal.uncertainty == high`; low-risk goals are skipped by policy
- 2026-02-14: Wave 6D minimal security baseline implemented:
  - `gate.security_commands` config parsing/validation in `config.yaml`
  - gate executes security checks (named scanners + generic `security_check_n`)
  - required-check policy now composes with security checks (ex: `required_checks: ["gitleaks"]`)
- 2026-02-15: Wave 6D security policy bundle implemented:
  - new policy template: `.ai/policies/security_policy.yaml` (initialized by `hast init`)
  - gate now runs policy-driven scanners:
    - `gitleaks`, `semgrep`
    - dependency scanner via `dependency_scan` (`either`) or `trivy` + `grype` (`all`)
  - missing tool handling is policy-controlled via `fail_on_missing_tools`
- 2026-02-15: Wave 6D hardening v1 implemented:
  - gate supports expiry-aware security `ignore_rules` with audit logging to `audit_file`
  - gate summary/evidence now include security signal fields:
    - `security_failed_checks`
    - `security_missing_tool_checks`
    - `security_ignored_checks`
    - `security_expired_ignore_rules`
  - risk policy now supports security signal bonuses and force-block controls
- 2026-02-14: Wave 6E spike runner skeleton implemented:
  - new command: `hast decision spike <decision_file> --parallel N --backend {auto|thread|ray}`
  - isolates alternatives in dedicated worktrees, executes per-alt spike command, stores artifacts under `.ai/decisions/spikes/<decision_id>/<timestamp>/`
  - appends `decision_spike` rows to `.ai/decisions/evidence.jsonl` and links summary into ticket `evidence_refs`
- 2026-02-14: Wave 7A proposal inbox scaffold implemented:
  - new command group: `hast propose`
  - `hast propose note ...` appends normalized proposal rows to `.ai/proposals/notes.jsonl`
  - `hast propose list` provides manager-readable inbox view without mutating `goals.yaml`
- 2026-02-14: Wave 7B admission + promotion engine implemented:
  - new policy template: `.ai/policies/admission_policy.yaml`
  - new command: `hast propose promote --window 14 --max-active 5`
  - promotion output persists to `.ai/proposals/backlog.yaml` with `accepted|deferred|rejected` + reason codes
  - accepted proposals become managed goals under policy root (default `PX_2X`)
- 2026-02-14: Wave 7C dynamic replan + invalidation implemented:
  - post-merge replan hook auto-applies `obsolete|superseded|merged_into` transitions for pending/active goals
  - supports explicit completed-goal invalidation lists (`obsoletes`, `supersedes`, `merges`)
  - heuristic invalidation for duplicate proposal fingerprints (`duplicate_proposal_resolved`)
  - writes auditable invalidation evidence rows (`phase=replan`, `invalidation_reason_code`, `invalidated_by_goal`)
- 2026-02-14: Proposal signal metrics integrated into `hast metrics`:
  - proposal note volume (`proposal_notes`)
  - backlog distribution (`proposal_backlog_total`, `accepted`, `deferred`, `rejected`)
  - promotion count (`proposal_promoted`) and signal ratio (`proposal_accept_ratio`)
- 2026-02-14: Wave 8A auto docgen baseline implemented:
  - new command: `hast docs generate --window N [--warn-stale/--no-warn-stale]`
  - generates 4 artifacts under `docs/generated/`:
    - `codemap.md`
    - `goal_traceability.md`
    - `decision_summary.md`
    - `quality_security_report.md`
  - stale-doc detection emits warnings before refresh, with high-risk stale-path block support
  - post-merge trigger scaffold added: `.github/workflows/docs-generate.yml`
- 2026-02-14: Mermaid doc visualization integrated into doc automation:
  - `hast docs generate` now also scans markdown Mermaid blocks and renders SVG to `docs/generated/mermaid/`
- 2026-02-15: Control-plane evidence contract baseline implemented:
  - evidence rows are normalized with `event_type` and `contract_version` (`cp.v1`)
  - semantic mismatches are captured in non-blocking `contract_warnings`
  - init now scaffolds `.ai/schemas/control_plane_evidence.schema.yaml`
- 2026-02-15: Wave 9B lease-queue baseline implemented:
  - new queue commands:
    - `hast queue claim`
    - `hast queue renew`
    - `hast queue release`
    - `hast queue list`
    - `hast queue sweep`
  - queue semantics include lease TTL expiry, per-worker active-claim caps, and idempotent claim reuse via `idempotency_key`
  - claim metadata is synchronized to `goals.yaml` (`claimed_by`, `claim_id`, `claim_expires_at`)
- 2026-02-15: Wave 9A event bus + reducer shadow mode implemented:
  - new event bus core: `.ai/events/events.jsonl` append-only writer + replay reducer
  - new snapshots:
    - `.ai/state/goal_views.yaml`
    - `.ai/state/operator_inbox.yaml`
  - duplicate `event_id` entries are ignored during replay (idempotent reducer behavior)
  - queue/evidence/orchestrator now emit shadow events when `event_bus_policy.enabled: true`
  - new command: `hast events replay [--write/--no-write]`
- 2026-02-15: Wave 9C operator inbox policy-action loop implemented:
  - new inbox commands:
    - `hast inbox list`
    - `hast inbox summary`
    - `hast inbox act`
  - policy template added: `.ai/policies/operator_inbox_policy.yaml`
  - `inbox act` enforces policy-authorized goal transitions (`approve/reject/defer`)
  - unauthorized transitions are hard-rejected before state mutation
- 2026-02-15: Wave 9D parallel consumer role flow implemented:
  - new role policy template: `.ai/policies/consumer_role_policy.yaml`
  - `hast queue claim` now supports role lanes via `--role implement|test|verify`
  - claim selection enforces deterministic phase-to-role mapping
  - role-mismatch / role-no-goal rejections are explicit (`role_phase_mismatch`, `role_no_claimable_goals`)
- 2026-02-15: Wave 9E orchestration protocol adapters implemented:
  - new protocol bridge commands:
    - `hast protocol export`
    - `hast protocol ingest`
  - new policy template: `.ai/policies/protocol_adapter_policy.yaml`
  - task export emits `protocol_task.v1` packets for `langgraph` / `openhands`
  - result ingest validates `protocol_result.v1`, writes evidence row, and appends protocol inbox trace
  - `ProtocolRunner` added for `hast auto --tool langgraph|openhands` auto roundtrip:
    - task export -> wait for result packet -> ingest -> evidence
- 2026-02-15: Observability baseline guard implemented:
  - new command: `hast observe baseline --window N`
  - emits readiness verdict and writes `.ai/reports/observability_baseline.json`
  - tracks first-pass success, block/security rates, MTTR, and queue collision/reuse signals against `observability_policy.yaml`
  - `hast orchestrate` now supports baseline-aware gating via `--enforce-baseline`
  - new command: `hast docs mermaid --glob "docs/**/*.md" [--open-index]`
  - renderer dependency (`mmdc`) is optional; missing binary results in warnings, not hard failure
- 2026-02-15: Wave 8B WikiLink vault sync implemented:
  - new command: `hast docs sync-vault [--check-links/--no-check-links] [--strict]`
  - generates `.knowledge/` note groups from source artifacts:
    - `Goal/G_*.md`
    - `Decision/D_*.md`
    - `Run/R_*.md`
    - `Contract/C_*.md`
  - includes broken wikilink/orphan note inspection for local review and strict CI-style failure mode
- 2026-02-15: Wave 8 CI link integrity gate enabled:
  - `.github/workflows/docs-generate.yml` now runs on `pull_request` and `push`
  - CI executes `hast docs sync-vault --check-links --strict`
  - workflow uploads both `docs/generated/` and `.knowledge/` artifacts for debugging
