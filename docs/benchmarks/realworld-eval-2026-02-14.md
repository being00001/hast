# Real-World Pilot Evaluation (2026-02-14)

## Scope
- Tool under test: `devf` (local editable install from `devf-fork`)
- Host: `/home/upopo`
- Benchmark workspace: `~/devf-bench`
- Repositories:
  - Small: `pallets/click` (Python)
  - Large: `astral-sh/uv` (Rust + Python)

## Method
1. `git clone --depth 1` for both repositories.
2. Per repository:
   - Remove prior `.ai` and `docs/generated`.
   - Run:
     - `devf init`
     - `devf map`
     - `devf context --format pack`
     - `devf docs generate --window 14`
   - Measure wall-clock time per command.
   - Collect generated-doc size/line metrics.
3. Stale-doc check:
   - Touch `pyproject.toml` (click) / `Cargo.toml` (uv)
   - Re-run `devf docs generate` and verify stale warning.

Raw data file: `~/devf-bench/benchmark_results.json`

## Objective Results

| Metric | click (small) | uv (large) |
|---|---:|---:|
| Tracked files | 146 | 1,239 |
| Python files | 62 | 83 |
| Rust files | 0 | 561 |
| Python LOC | 21,610 | 8,300 |
| Rust LOC | 0 | 442,421 |
| Repo disk size | 3 MB | 34 MB |
| `devf init` | 1.353s | 1.433s |
| `devf map` | 1.426s | 1.594s |
| `devf context --format pack` | 1.690s | 1.740s |
| `devf docs generate` | 1.413s | 1.460s |
| `devf docs generate` (after touch) | 1.438s | 1.463s |
| Stale warning seen (after touch) | Yes | Yes |

Generated docs output:
- `docs/generated/codemap.md`
  - click: 39,283 bytes / 677 lines
  - uv: 15,189 bytes / 328 lines
- `docs/generated/goal_traceability.md`
  - both: 222 bytes / 7 lines
- `docs/generated/decision_summary.md`
  - both: 356 bytes / 18 lines
- `docs/generated/quality_security_report.md`
  - both: 292 bytes / 20 lines

Indexing summary:
- click: indexed Python files/classes/functions = `32 / 77 / 563`
- uv: indexed Python files/classes/functions = `82 / 39 / 229`

## Interpretation

What is clearly valuable now:
- Fast bootstrap and artifact generation:
  - All core commands finished in ~1.3–1.7s on both repos.
  - 4 generated docs produced automatically with no repo-specific tuning.
- Freshness control works:
  - Stale generated docs were detected immediately after touching tracked source-config files.

What is objectively weak now:
- Rust-heavy projects are under-represented in codemap:
  - `uv` has Rust LOC share ~98.2%, but current codemap/indexing path is Python-AST only.
  - Large multi-language repos therefore get incomplete architectural visibility.
- Traceability/decision/quality docs stay thin without `.ai` operational data:
  - Until goals/decisions/evidence exist, those reports are mostly skeletons.

## Verdict

Current `devf` value is **real** for:
- low-friction project bootstrap,
- fast structured context extraction,
- automatic documentation refresh + stale detection.

Current `devf` is **not yet sufficient** for full-value operation in Rust-heavy repos without:
- Rust symbol indexing,
- richer automatic evidence ingestion for quality/security docs.

## Next Recommended Improvements
1. Add Rust codemap backend (`tree-sitter-rust` or `rust-analyzer` JSON integration).
2. Expand freshness policy with block mode for high-risk paths.
3. Auto-ingest CI/test/gate outputs into `.ai/runs/*/evidence.jsonl` for non-empty quality reports.
