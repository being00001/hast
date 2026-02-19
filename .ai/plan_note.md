# Codex Tool-Improvement Plan Note

## Intent
- Primary objective of this Codex session: improve hast itself for LLM operators.
- If a task does not improve operator throughput, safety, or cognitive load, deprioritize it.
- Interpersonal preference: call assistant "Frost" and use informal Korean tone (banmal) by default.

## Session Start Protocol (always)
- Step 0: Read this note first.
- Step 1: Inspect latest friction signals (.ai/feedback/backlog.yaml, recent no-progress attempts, scope violations).
- Step 2: Pick one smallest high-leverage fix that can be validated by tests.
- Step 3: Ship the fix with explicit guardrails and low-risk rollout.

## Improvement Priorities
- P1: Question queue + resume loop (workers ask instead of repeating no-progress retries).
- P2: Strict write boundary enforcement with narrow generated-file exceptions only.
- P3: Retry strategy by failure class (scope/env/spec/test) instead of blind retries.
- P4: Low-token session handoff format (focus pack + JSON outputs + explicit next action).
- P5: Telemetry -> backlog -> publish pipeline with explicit human/manager trigger.

## Decision Heuristics
- Prefer smaller diff with clear verification over broad refactor.
- If ambiguity blocks progress, ask a concrete multiple-choice question.
- Keep safety invariants stronger than speed.

## Claude Code Friction Log
- [High] Scope exceptions for auto-generated files are too manual.
  - Symptom: pre-commit updates (docs/ARCHITECTURE.md, core/protocols.py, .codemap.json) trigger out-of-scope failures.
  - Direction: keep global allowlist in config (always_allow_changes) with narrow patterns.
- [High] Scope failure diagnosis is not explicit enough.
  - Symptom: "changes outside allowed scope" without immediate violating-file list in operator-facing output.
  - Direction: print violating file paths directly in failure reason/summary.
- [Medium] Clean-tree enforcement is too strict for .ai operational artifacts.
  - Symptom: init/run artifacts create dirty state and force extra commit churn.
  - Direction: treat operational .ai generated files as ignored/non-blocking by default where safe.
- [Medium] Recovery after failed attempt is too manual.
  - Symptom: blocked -> re-activate -> commit hygiene -> rerun is multi-step.
  - Direction: add one-command recovery path (scope fix + retry flow).
- [Low] Non-interactive runs still produce clarification questions from worker model.
  - Symptom: worker asks questions and makes no edits -> no-progress.
  - Direction: strengthen non-interactive execution contract in context/prompt and add ask-via-queue behavior.

## Claude Design-Support Ideas (Classified)
- [Accepted / Done] Global generated-file exceptions.
  - Idea: config-level always-allowed list for pre-commit generated files.
  - Decision: completed via `always_allow_changes` + gate/auto integration.
- [Accepted / Next] `hast explore` for design-question analysis.
  - Idea: codebase impact map + candidate approaches + trade-off report before auto.
  - Why accepted: expands hast from "mechanical execution" to "design support".
  - Guardrail: read-only command, no file writes by default.
- [Accepted / Next] plan intelligence for decision-aware decomposition.
  - Idea: classify goals into `auto_eligible` vs `decision_required`, mark blocked_by decision.
  - Why accepted: lowers operator cognitive load and prevents blind auto retries.
- [Accepted / Next] failure -> learning assist loop.
  - Idea: on failure, suggest decision ticket creation and prerequisite-goal insertion.
  - Why accepted: converts dead-end failures into explicit next actions.
  - Guardrail: suggestion-first; no automatic mutation of goal graph without confirmation.
- [Accepted with Constraints / Later] stronger decision spike with code-level prototypes.
  - Idea: compare alternatives by real diffs/tests/impact in structured table.
  - Why partially deferred: high implementation/safety cost without strict isolation.
  - Prerequisite: robust per-alternative sandbox/worktree isolation and deterministic scoring.

## Execution Queue (Design Support Track)
- [Done] Q1: Add `hast explore` (read-only) with JSON + markdown report output.
- [Done] Q2: Extend `hast plan` with `auto_eligible`, `decision_required`, `blocked_by` annotations.
- [Done] Q3: Add failure-assist prompts in auto (`create decision?`, `add prerequisite goal?`).
- [Done] Q4: Upgrade decision spike comparator with diff-aware ranking and surfaced metrics.
- [Done] Q5: Add spike comparator policy (`spike_policy.yaml`) for deterministic defaults + optional duration tie-break.
- [Done] Q5.1: Add one-line winner explanation surfaced in spike summary/CLI/JSON/evidence.
- [Done] Q5.2: Keep default reason short (`why:<code>`) and expose structured comparison + opt-in `--explain` detail.
- [Done] Q6: Add guarded auto-accept for decision spike (`--accept-if-*`) with conservative checks and explicit skip reasons.
- [Done] Q7: Add bundled security gate policy (`security_policy.yaml`) with gitleaks/semgrep/trivy|grype checks and missing-tool policy.
