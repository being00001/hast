# Opus Guide Alignment Review

## Source
- Reference: `docs/opus_guide.md`
- Date: 2026-02-14

## Alignment Summary
- **Aligned**: contract-first BDD, failure triage, policy-driven retries, evidence logging, risk gates.
- **Previously missing**: automatic pre-implementation enforcement for decision acceptance.
- **Now added**: high-uncertainty decision gate in `devf auto`.

## Implemented Changes
1. `goals.yaml` schema extensions
   - `decision_file: ".ai/decisions/<id>.yaml"`
   - `uncertainty: low|medium|high`
2. Auto-loop preflight decision gate
   - If `uncertainty: high` or `decision_file` set, `devf auto` validates decision ticket.
   - Goal is blocked unless ticket is `status: accepted` with `selected_alternative`.
3. Triage normalization
   - `decision-*` failures map to `spec-ambiguous`.
4. Context propagation
   - Context pack/markdown/plain includes `decision_file` and `uncertainty`.

## Remaining Gaps (Next)
1. Parallel spike execution inside one goal (`A/B/C` spike branches auto-run + auto-compare).
2. Decision-quality metrics in `devf metrics` (e.g., decision churn, decision-to-merge lead time).
3. Automatic uncertainty classifier (infer when decision stage is needed, instead of manual tagging).
4. Emergent goal control plane (proposal inbox + central admission + dynamic invalidation).

## Recommendation
- Keep current default lightweight.
- Enforce decision gate only when `uncertainty: high` or `decision_file` is explicitly declared.
- Add spike-parallel runner as next incremental milestone (not as a hard default).
