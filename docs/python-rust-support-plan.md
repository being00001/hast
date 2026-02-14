# Python + Rust Support Plan

## Objective

Make devfork operate reliably for:

1. Python-only repositories
2. Rust-only repositories
3. Mixed Python + Rust repositories

Without breaking existing Python workflows.

## Done Criteria

1. RED/GREEN loop can detect and validate tests for Python and Rust.
2. Gate can execute language-aware checks for Python and Rust.
3. Goal schema can declare target languages explicitly.
4. Existing Python tests remain green (backward compatibility).

## Phase 1: Config and Schema

1. Add `language_profiles` in config with built-in defaults:
   - `python`: pytest + (optional) mypy/ruff checks
   - `rust`: cargo test/fmt/clippy checks
2. Keep old keys (`test_command`, `gate.mypy_command`, `gate.ruff_command`) working.
3. Extend goal schema with `languages: [python, rust]`.

## Phase 2: RED/GREEN Runtime

1. Resolve active languages per goal:
   - explicit `goal.languages` first
   - otherwise auto-detect from repo/files
2. RED stage:
   - detect changed test files by language profile globs
   - assert meaningful assertions by language patterns
   - run targeted language test command(s)
3. Contract must-pass/must-fail tests use language-aware targeted execution.

## Phase 3: Gate Runtime

1. Keep existing Python gate behavior for compatibility.
2. Add Rust gate checks when Rust is active.
3. Mixed repo runs both language check sets.

## Phase 4: Validation

1. Add/extend tests for:
   - config profile loading
   - goal language parsing
   - RED gate behavior for Rust tests
   - gate behavior with Rust checks
2. Run focused pytest suite and fix regressions.

## Risk Controls

1. Preserve default Python behavior by default profile.
2. Use conservative Rust defaults (`cargo test` fallback) before optimization.
3. Avoid mandatory toolchain assumptions in tests (use configurable commands).
