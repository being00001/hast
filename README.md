# devf

AI-native development session manager.

Session continuity, project state tracking, and verification pipeline for solo developer + AI coding agent workflows.

## Key Features (AI-Native)

- **Code Map (Symbol Graph)**: AST-based project summary providing classes, methods, and signatures to reduce AI navigation cost.
- **Context Pack (XML)**: AI-optimized structured context format for higher instruction following accuracy.
- **Smart Scoping (Tier 1 & 2)**: Intelligent context pruning using bidirectional dependency analysis and priority-based filtering (src > tests > docs).
- **Contract Enforcement**: Mandatory test files and acceptance criteria defined in `goals.yaml`.
- **Policy-Driven Retry/Triage**: Failure classes are normalized and retried/blocked by policy (`.ai/policies/retry_policy.yaml`).
- **Risk Scoring**: Every attempt receives a `risk_score` for safer merge decisions.
- **Evidence Logging**: Attempts are logged in `.ai/runs/<run_id>/evidence.jsonl` with state/policy metadata.
- **Decision Parallelization**: Decision tickets + validation matrix scoring (`devf decision`) before implementation.
- **Feedback Intelligence Loop**: Explicit worker notes + inferred friction notes + manager promotion backlog.
- **Impact-Based Test Suggestion**: Automatically identifies and suggests tests impacted by code changes.
- **Retry Context Injection**: Injects failures, diffs, and logs from previous attempts to prevent repetitive mistakes.
- **Runner Interface**: Pluggable architecture for executing sessions (Local, OpenHands, Docker).

## Status

Pre-alpha. Active development of Swarm Orchestration.

## Quick Start

```bash
devf init
devf map        # See the codebase map
devf context --format pack  # Get AI-optimized context
devf auto       # Run automated loop
devf auto ROOT --recursive --parallel 3
devf metrics    # Aggregate evidence metrics (7-day default)
devf triage --run-id <id>  # Show per-attempt policy triage rows
devf feedback note --category workflow_friction --impact medium --expected "..." --actual "..."
devf feedback analyze --run-id <id>
devf feedback backlog --window 14 --promote
devf feedback publish --limit 10 --dry-run
devf orchestrate --run-id <id> --window 14 --max-goals 5
devf propose note --category risk --impact high --risk high --title "..." --why-now "..."
devf propose list --window 30
devf propose promote --window 14 --max-active 5
devf decision new G_LOGIN --question "Which auth strategy?" --alternatives A,B
devf decision evaluate .ai/decisions/D_G_LOGIN_*.yaml --accept
devf decision spike .ai/decisions/D_G_LOGIN_*.yaml --parallel 3 --backend auto
devf immune grant --allow "src/**/*.py" --approved-by supervisor
devf docs generate --window 14
devf docs mermaid --open-index
devf docs sync-vault
```

Machine-readable output is available on major commands with `--json`
(for example: `devf metrics --json`, `devf docs generate --json`,
`devf decision evaluate <file> --json`).

## Quality Gates

Repository quality gates are bundled through pre-commit:

```bash
pip install -e .[dev]
pre-commit install
pre-commit install --hook-type pre-push
pre-commit run --all-files
pre-commit run --all-files --hook-stage pre-push
```

The default bundle runs:
- ruff lint (Python)
- mypy type checks (core gate/config modules)
- pytest suite
- conditional Rust gates (`cargo fmt --check`, `cargo clippy -- -D warnings`) when `Cargo.toml` exists

## Tool Routing (CLI + API)

`devf auto` and `devf plan` can run either:

- local CLI tools via `ai_tool` / `ai_tools` (e.g. Codex CLI, Gemini CLI, Claude CLI)
- API models via `roles.*.model` (LiteLLM path)

Example:

```yaml
test_command: "pytest"
ai_tool: "claude -p {prompt_file}"
ai_tools:
  codex: "codex exec {prompt_file}"
  gemini: "gemini -p {prompt_file}"
  claude: "claude -p {prompt_file}"
language_profiles:
  rust:
    targeted_test_command: "cargo test"
    gate_commands:
      - "cargo test"
      - "cargo fmt --check"
      - "cargo clippy -- -D warnings"
gate:
  required_checks: ["pytest", "ruff", "mypy"]
  fail_on_skipped_required: true
  pytest_parallel: true
  pytest_workers: "auto"
  pytest_reruns_on_flaky: 2
  pytest_random_order: false
  security_commands:
    - "gitleaks detect --no-git --source ."
```

```bash
devf plan "Add login feature" --tool codex
devf auto G_LOGIN --tool codex
```

Goal-level language pinning:

```yaml
goals:
  - id: G_POLY
    title: "Python + Rust feature"
    status: active
    languages: [python, rust]
```

## Acceptance Contract

You can pin a goal to an immutable contract file:

```yaml
goals:
  - id: G_LOGIN
    title: "Implement Login"
    status: active
    spec_file: "features/login.feature"
    contract_file: ".ai/contracts/login.contract.yaml"
```

Contract example:

```yaml
version: 1
inputs:
  - "email/password"
outputs:
  - "access token"
error_cases:
  - "invalid credentials -> 401"
security_requirements:
  - "rate limit enabled"
required_assertions:
  - "status_code == 200"
must_fail_tests:
  - "tests/test_login.py"
must_pass_tests:
  - "tests/test_login.py"
required_changes:
  - "src/auth.py"
required_docs:
  - "README.md"
  - "docs/auth/*.md"
required_security_docs:
  - "SECURITY.md"
forbidden_changes:
  - "tests/*"
  - "features/*"
```

In `devf auto`:
- RED stage must generate meaningful failing tests.
- Implementation cannot modify test/spec/contract files.
- Contract `must_pass_tests`/change rules are enforced before success.
- If `required_docs` / `required_security_docs` are set, missing updates are blocked.

## Dependency + Role Controls

Goals can declare dependency and write-scope intent:

```yaml
goals:
  - id: G_IMPL
    title: "Implement feature"
    status: active
    depends_on: [G_TEST]
    owner_agent: worker
    uncertainty: high
    decision_file: ".ai/decisions/D_G_IMPL.yaml"
```

- `depends_on`: scheduler executes goals in dependency-safe batches
- `owner_agent: tester|worker|architect|gatekeeper`: role-based file scope guardrails
- `uncertainty: high` + `decision_file`: enforce "decide-first, implement-later" gate
- hard policy: disallowed file paths are blocked **before** applying parsed LLM edits

## Merge Train + Risk Controls

`config.yaml`:

```yaml
merge_train:
  pre_merge_command: "pytest -q"
  post_merge_command: "pytest tests/smoke -q"
  auto_rollback: true
```

`risk_policy.yaml`:

```yaml
block_threshold: 95
rollback_threshold: 80
```

- if merge risk score exceeds `block_threshold`, merge is auto-blocked
- if post-merge smoke fails and risk score exceeds `rollback_threshold`, latest merge commit is auto-reverted

## Policy Files

`devf init` now creates `.ai/policies/` templates:

- `retry_policy.yaml`: classification-specific retry limits and actions
- `risk_policy.yaml`: risk score model by phase/path/failure type
- `transition_policy.yaml`: lifecycle state registry
- `model_routing.yaml`: default role/model routing hints
- `feedback_policy.yaml`: feedback promotion/dedup defaults
- `docs_policy.yaml`: stale-doc warning/block policy (high-risk path aware)
- `immune_policy.yaml`: autonomous edit grant/TTL/protected-path guardrails

## Immune Guardrails

Use `immune_policy.yaml` to enforce default-deny autonomous edits.

Issue a short-lived grant before high-risk autonomous repair runs:

```bash
devf immune grant --allow "src/**/*.py" --approved-by supervisor --ttl-minutes 30
```

When enabled, out-of-scope writes, expired grants, and protected-path writes are blocked
and appended to `.ai/immune/audit.jsonl`.

## Feedback Loop

Manager-centric flow:

1. Worker records explicit pain points:
   - `devf feedback note ...`
2. System infers friction from evidence rows:
   - `devf feedback analyze --run-id <id>`
3. Manager applies promotion gate and builds backlog:
   - `devf feedback backlog --promote`
4. Manager publishes accepted items to Codeberg (optional):
   - `devf feedback publish --limit 10`
5. One-shot orchestration (2x productivity path):
   - `devf orchestrate --run-id <id> --window 14 --max-goals 5`

This keeps worker output lightweight while preserving a high-signal improvement queue.

## Decision Workflow (Validate Before Build)

Use `devf decision` to enforce decision/validation parallelization before implementation:

```bash
devf decision new G_AUTH \
  --question "Which rate-limit algorithm should we adopt?" \
  --alternatives A,B,C

# Fill scores per criterion in the decision yaml, then:
devf decision evaluate .ai/decisions/<decision_id>.yaml --accept --run-id <run_id>
```

- Ticket file: `.ai/decisions/<decision_id>.yaml`
- Validation matrix: weighted criteria + threshold (`min_score`)
- Evidence row: `.ai/decisions/evidence.jsonl` (`schema_version: decision_evidence.v1`)
- Init templates:
  - `.ai/templates/decision_ticket.yaml`
  - `.ai/schemas/decision_evidence.schema.yaml`

`feedback_policy.yaml` publish section example:

```yaml
publish:
  enabled: true
  backend: codeberg
  repository: your-user/your-repo
  token_env: CODEBERG_TOKEN
  base_url: https://codeberg.org
  labels: [bot-reported, devf-feedback]
  min_status: accepted
```

If `CODEBERG_TOKEN` is unset, publish falls back to `berg --non-interactive issue create`
using your existing `berg auth login` session.

## Documentation Control Plane

Use `devf docs generate` to refresh generated docs after meaningful project changes:

```bash
devf docs generate --window 14
```

Generated outputs:
- `docs/generated/codemap.md`
- `docs/generated/goal_traceability.md`
- `docs/generated/decision_summary.md`
- `docs/generated/quality_security_report.md`

By default, the command warns when these generated docs were stale before refresh.
With default `docs_policy.yaml`, stale docs also fail the command when high-risk paths
were touched since last generation.
It also scans markdown files for Mermaid blocks and renders SVG assets to:
- `docs/generated/mermaid/*.svg`
- `docs/generated/mermaid/index.md`

Manual Mermaid-only rendering:

```bash
devf docs mermaid --glob "docs/**/*.md" --open-index
```

If `mmdc` is unavailable, Mermaid rendering is skipped with warnings (base docgen still succeeds).

WikiLink vault sync (`.knowledge/`):

```bash
devf docs sync-vault
```

Generated note groups:
- `.knowledge/Goal/G_*.md`
- `.knowledge/Decision/D_*.md`
- `.knowledge/Run/R_*.md`
- `.knowledge/Contract/C_*.md`

## Design

See [docs/design.md](docs/design.md) for full design document.
See [docs/scopes/](docs/scopes/) for scope-level design breakdowns.
