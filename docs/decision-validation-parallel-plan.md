# Decision Validation Parallel Plan

## Goal
Implement "decision and validation parallelization" so goals can converge on a chosen approach before implementation.

## Why
- Reduce rework caused by ambiguous design choices.
- Make winner selection explicit and evidence-backed.
- Keep implementation loops fast by pre-fixing acceptance direction.

## BDD Work Items
- [x] **RED**: add tests for decision ticket evaluation and CLI (`tests/test_decision.py`, `tests/test_cli_decision.py`)
- [x] **GREEN**: implement decision core module (`src/devf/core/decision.py`)
- [x] **GREEN**: add CLI commands (`devf decision new`, `devf decision evaluate`)
- [x] **GREEN**: append decision evidence rows (`.ai/decisions/evidence.jsonl`)
- [x] **GREEN**: high-uncertainty preflight gate in `devf auto` (`decision_file` must be accepted)
- [x] **REFACTOR**: update init templates and docs (`README.md`, `docs/100x-roadmap.md`)

## Artifacts
- Ticket template: `.ai/templates/decision_ticket.yaml`
- Evidence schema: `.ai/schemas/decision_evidence.schema.yaml`
- Runtime ticket: `.ai/decisions/<decision_id>.yaml`
- Runtime evidence: `.ai/decisions/evidence.jsonl`

## Process
1. Create decision ticket from goal.
2. Fill alternatives and criterion scores.
3. Evaluate matrix and select winner.
4. Accept winner (or escalate if threshold fails).
5. Start implementation only after accepted decision.

## Progress Log
- 2026-02-14: Decision module + CLI + template/schema + tests implemented.
