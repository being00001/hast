# DEVF 100x Roadmap

## Objective
Shift from "code generation loop" to a policy-driven autonomous development system:
- high parallel throughput
- low rework
- evidence-backed decisions
- safe merge behavior

## Delivery Waves

### Wave 1 (Completed: policy foundation)
- [x] Failure triage taxonomy module
- [x] Retry policy module and decision engine
- [x] Risk scoring policy module
- [x] Evidence schema extensions for policy metadata
- [x] `.ai/policies/*` init templates
- [x] `hast metrics` command for evidence aggregation

### Wave 2 (Next)
- [x] Goal DAG + parallel scheduler (`depends_on`, dependency batches, `--parallel`)
- [x] Role separation enforcement (role-based write scope via `owner_agent`)
- [x] File access policy hard-fail rules (pre-apply path block)

### Wave 3 (Next)
- [x] Merge train + integration regression gate (`merge_train.pre/post_merge_command`)
- [x] Risk threshold actions (`block_threshold`, `rollback_threshold`, auto-revert)
- [x] Docs/security-required update enforcement

### Wave 4 (Feedback Intelligence Loop)
- [x] Worker explicit feedback note capture (`hast feedback note`)
- [x] Evidence-based inferred friction notes (`hast feedback analyze`)
- [x] Manager promotion backlog (`hast feedback backlog --promote`)
- [x] Feedback policy template (`.ai/policies/feedback_policy.yaml`)
- [x] Codeberg issue publisher (manager-only, `hast feedback publish`)
- [x] One-shot orchestrator (`hast orchestrate`: analyze -> backlog -> goals -> publish)

### Wave 5 (Decision + Validation Parallelization)
- [x] Decision ticket template (`.ai/templates/decision_ticket.yaml`)
- [x] Decision evidence schema template (`.ai/schemas/decision_evidence.schema.yaml`)
- [x] Decision CLI scaffold (`hast decision new`)
- [x] Validation matrix scoring + winner selection (`hast decision evaluate`)
- [x] Decision evidence logging (`.ai/decisions/evidence.jsonl`)

### Wave 6 (OSS Leverage Integration, Planned)
- [x] Quality gate bundle via `pre-commit` + Python/Rust linters/type checks
- [x] Flaky reliability bundle via pytest plugins
- [x] Mutation gate via `mutmut` + `cargo-mutants`
- [x] Security gate via `gitleaks` + `semgrep` + `trivy/grype`
- [x] Parallel spike runner skeleton (`hast decision spike`, thread backend + Ray local mode fallback)
- Plan document: `docs/oss-integration-plan.md`

### Wave 7 (Emergent Goal Control Plane, Planned)
- [x] Proposal inbox scaffold (`hast propose note/list`) for all agents
- [x] Central admission engine (`hast propose promote`) with dedupe/TTL/budget
- [x] Dynamic replan + invalidation states (`obsolete`, `superseded`, `merged_into`)
- [x] Evidence reason codes for promotion/rejection/invalidation
- [x] Proposal signal quality metrics in `hast metrics`
- Plan document: `docs/oss-integration-plan.md`

### Wave 8 (Documentation Control Plane, Planned)
- [x] Auto docgen baseline (`hast docs generate`) for codemap/traceability/decision/quality
- [x] Post-merge CI trigger for generated docs refresh
- [x] Stale-doc freshness policy (warn default, block on high-risk paths)
- [x] WikiLink vault sync (`hast docs sync-vault`) for `.knowledge/`
- [x] Broken-link/orphan-note checks in CI
- Plan document: `docs/oss-integration-plan.md`

### Wave 9 (Event-Driven Async Swarm, Planned)
- [x] Event log schema + append-only bus (`.ai/events/*.jsonl`)
- [x] Goal claim lease protocol (`claim/renew/release`) for worker pull model
- [x] State reducer snapshots (`.ai/state/goal_views.yaml`, `inbox.yaml`)
- [x] Policy-only central control (single operator agent as admission/gatekeeper)
- [x] Parallel consumer roles (implement/test/verify) with deterministic transitions
- [x] Shadow mode rollout + Go/No-Go metrics gate
- Plan document: `docs/oss-integration-plan.md`

## Core Metrics
- First-pass success rate
- Retry count per goal
- Same-failure-repeat ratio
- Average risk score by phase
- Block/escalate/retry action distribution
- Feedback notes per window
- Accepted backlog ratio
- Proposal-to-accepted ratio
- Goal invalidation latency
- Documentation freshness SLA
- Manual documentation touch ratio
- Goal queue wait time (p50/p95)
- Claim collision rate
- Lease timeout recovery rate

## 2X Idea Backlog (Discovery)
- Context delta-only prompts instead of full context replay per attempt
- Failure signature memory with auto-remediation templates
- Two-stage model routing (fast model first, strong model on escalation)
- Spec/test-first parallel workers before implementation starts
- Impacted-test-first execution and full suite only at merge gate
- Lease/claim queue optimization to reduce idle wait and duplicate work
- Operator inbox Top-K prioritization instead of full-log review
- Background async gates for heavy checks (docgen/security/reporting)
- Rule-based autofix-first pass before LLM invocation
- Golden path goal templates for repetitive task families
