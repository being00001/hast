# hast

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
- **Decision Parallelization**: Decision tickets + validation matrix scoring (`hast decision`) before implementation.
- **Feedback Intelligence Loop**: Explicit worker notes + inferred friction notes + manager promotion backlog.
- **Impact-Based Test Suggestion**: Automatically identifies and suggests tests impacted by code changes.
- **Retry Context Injection**: Injects failures, diffs, and logs from previous attempts to prevent repetitive mistakes.
- **Runner Interface**: Pluggable architecture for executing sessions (Local, OpenHands, Docker).

## Status

Pre-alpha. Active development of Swarm Orchestration.

## Quick Start

```bash
hast init
hast doctor     # Preflight diagnostics (config/policies/git/worktree)
hast doctor --strict --json  # CI-friendly: non-zero on warnings/failures
hast-lab new demo --dir /tmp
hast-lab run protocol-roundtrip --project /tmp/demo
hast-lab run no-progress --project /tmp/demo
hast-lab report --project /tmp/demo
hast focus --tool codex   # Build low-cognitive-load session pack for Codex/Claude
hast map        # See the codebase map
hast explore "EconomyPort.evaluate() 파라미터 확장 시 영향은?"  # Read-only design exploration
hast context --format pack  # Get AI-optimized context
hast sim G_LOGIN --run-tests  # Predict likely blockers before auto
hast auto       # Run automated loop
hast auto --dry-run  # Show concise dry-run summary
hast auto --dry-run --dry-run-full  # Show full prompt(s)
hast auto ROOT --recursive --parallel 3
hast retry G_LOGIN      # Reactivate blocked goal + clear attempts + rerun auto
hast retry G_LOGIN --no-sim  # Skip simulation preview if you want minimal output
hast retry G_LOGIN --no-preflight  # Emergency bypass for doctor preflight
hast queue claim --worker codex --role implement --goal G_LOGIN --idempotency-key req-123
hast queue renew QCLM_abc123 --worker codex --ttl-minutes 45
hast queue release QCLM_abc123 --worker codex --goal-status done
hast queue list --active-only
hast observe baseline --window 14
hast events replay
hast inbox summary --top-k 10
hast inbox act inbox-123 --action reject --operator gatekeeper --goal-status blocked
hast protocol export --adapter langgraph --goal G_LOGIN --role implement --no-include-context
hast protocol ingest .ai/protocols/result_packet.json
hast auto G_LOGIN --tool langgraph   # ProtocolRunner roundtrip (export -> wait -> ingest)
hast metrics    # Aggregate evidence metrics (7-day default)
hast triage --run-id <id>  # Show per-attempt policy triage rows
hast feedback note --lane project --category workflow_friction --impact medium --expected "..." --actual "..."
hast feedback note --lane tool --category workflow_friction --impact medium --expected "..." --actual "..."
hast feedback analyze --run-id <id>
hast feedback backlog --window 14 --lane project --promote
hast feedback publish --limit 10 --lane tool --dry-run
hast orchestrate --run-id <id> --window 14 --max-goals 5 --enforce-baseline
hast propose note --category risk --impact high --risk high --title "..." --why-now "..."
hast propose list --window 30
hast propose promote --window 14 --max-active 5
hast decision new G_LOGIN --question "Which auth strategy?" --alternatives A,B
hast decision evaluate .ai/decisions/D_G_LOGIN_*.yaml --accept
hast decision spike .ai/decisions/D_G_LOGIN_*.yaml --parallel 3 --backend auto
hast decision spike .ai/decisions/D_G_LOGIN_*.yaml --accept --accept-if-reason diff_lines --accept-max-diff-lines 30
hast immune grant --allow "src/**/*.py" --approved-by supervisor
hast docs generate --window 14
hast docs mermaid --open-index
hast docs sync-vault
```

Machine-readable output is available on major commands with `--json`
(for example: `hast metrics --json`, `hast docs generate --json`,
`hast decision evaluate <file> --json`).

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

`hast auto` and `hast plan` can run either:

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
always_allow_changes:
  - "docs/ARCHITECTURE.md"
  - "src/protocols.py"
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
  mutation_enabled: true
  mutation_high_risk_only: true
  min_mutation_score_python: 70
  min_mutation_score_rust: 60
  pytest_parallel: true
  pytest_workers: "auto"
  pytest_reruns_on_flaky: 2
  pytest_random_order: false
  security_commands:
    - "gitleaks detect --no-git --source ."
```

```bash
hast plan "Add login feature" --tool codex
hast auto G_LOGIN --tool codex
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

In `hast auto`:
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
- `auto_eligible: true|false`: planning hint for whether goal is safe for immediate auto execution
- `decision_required: true|false`: marks goals that need explicit design decision before implementation
- `blocked_by: "DECISION: ..."`: operator-facing prerequisite hint when design clarity is missing
- `always_allow_changes` (config): scope-check bypass for deterministic generated files (e.g. pre-commit updates)
- hard policy: disallowed file paths are blocked **before** applying parsed LLM edits
- `hast retry <goal_id>`: one-command recovery for blocked goals (reactivate + clear attempts + rerun)

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

`hast init` now creates `.ai/policies/` templates:

- `retry_policy.yaml`: classification-specific retry limits and actions
- `risk_policy.yaml`: risk score model by phase/path/failure type
- `transition_policy.yaml`: lifecycle state registry
- `model_routing.yaml`: default role/model routing hints
- `feedback_policy.yaml`: feedback promotion/dedup defaults
- `docs_policy.yaml`: stale-doc warning/block policy (high-risk path aware)
- `immune_policy.yaml`: autonomous edit grant/TTL/protected-path guardrails
- `security_policy.yaml`: bundled security scanner gate (`gitleaks`, `semgrep`, `trivy`/`grype`)
- `spike_policy.yaml`: decision-spike ranking criteria and deterministic tiebreak controls
- `execution_queue_policy.yaml`: lease TTL and per-worker claim concurrency controls
- `observability_policy.yaml`: baseline readiness guard thresholds
- `event_bus_policy.yaml`: shadow event emission/reducer controls
- `operator_inbox_policy.yaml`: policy-authorized inbox action/transition matrix
- `consumer_role_policy.yaml`: role lane mapping (`implement/test/verify`) for worker pull claims
- `protocol_adapter_policy.yaml`: external adapter policy (`langgraph`/`openhands`) for export/ingest bridge
- `control_plane_evidence.schema.yaml`: event/action contract for run evidence rows

Control-plane contract:
- every run evidence row is normalized with `event_type` and `contract_version`
- semantic mismatches are surfaced in `contract_warnings` (non-blocking)
- optional shadow bus: evidence/queue/orchestrator events can be replayed into `.ai/state/*` via `hast events replay`

### ProtocolRunner Pilot (Self-Dogfood)

You can run a local end-to-end protocol roundtrip with the bundled mock worker:

```bash
# Terminal A
hast auto G_PILOT --tool langgraph

# Terminal B (same project root)
python3 scripts/mock_langgraph_worker.py --project-root . --goal-id G_PILOT --once
```

The mock worker auto-scans both root and goal worktrees:
- `.ai/protocols/outbox/*.json`
- `.worktrees/*/.ai/protocols/outbox/*.json`

It applies a deterministic file edit and writes `result_*.json` into the matching
workspace inbox so `ProtocolRunner` can ingest evidence automatically.
Use `--goal-id` to avoid consuming packets from other active goals.

## Immune Guardrails

Use `immune_policy.yaml` to enforce default-deny autonomous edits.

Issue a short-lived grant before high-risk autonomous repair runs:

```bash
hast immune grant --allow "src/**/*.py" --approved-by supervisor --ttl-minutes 30
```

When enabled, out-of-scope writes, expired grants, and protected-path writes are blocked
and appended to `.ai/immune/audit.jsonl`.

## Feedback Loop

Manager-centric flow:

1. Worker records explicit pain points:
   - project lane: `hast feedback note --lane project ...`
   - hast lane: `hast feedback note --lane tool ...`
2. System infers friction from evidence rows:
   - `hast feedback analyze --run-id <id>`
3. Manager applies promotion gate and builds backlog:
   - `hast feedback backlog --lane project --promote`
4. Manager publishes accepted items to Codeberg (optional):
   - `hast feedback publish --limit 10 --lane tool`
5. One-shot orchestration (2x productivity path):
   - `hast orchestrate --run-id <id> --window 14 --max-goals 5 --enforce-baseline`

`orchestrate` syncs only `project` lane feedback into goals. `tool` lane is excluded from goal auto-sync.
When `--enforce-baseline` is set, orchestrate is blocked if observability baseline guards are not satisfied.

## Decision Workflow (Validate Before Build)

Use `hast decision` to enforce decision/validation parallelization before implementation:

```bash
hast decision new G_AUTH \
  --question "Which rate-limit algorithm should we adopt?" \
  --alternatives A,B,C

# Fill scores per criterion in the decision yaml, then:
hast decision evaluate .ai/decisions/<decision_id>.yaml --accept --run-id <run_id>
```

- Ticket file: `.ai/decisions/<decision_id>.yaml`
- Validation matrix: weighted criteria + threshold (`min_score`)
- Evidence row: `.ai/decisions/evidence.jsonl` (`schema_version: decision_evidence.v1`)
- Init templates:
  - `.ai/templates/decision_ticket.yaml`
  - `.ai/schemas/decision_evidence.schema.yaml`

`hast decision spike` supports policy-friendly execution and guarded auto-accept:

```bash
# Run spikes only
hast decision spike .ai/decisions/<decision_id>.yaml --parallel 3 --backend auto

# Guarded auto-accept (conservative):
hast decision spike .ai/decisions/<decision_id>.yaml \
  --accept \
  --accept-if-reason diff_lines \
  --accept-max-diff-lines 30 \
  --accept-max-changed-files 5 \
  --accept-require-eligible

# Show detailed winner explanation (default output remains compact)
hast decision spike .ai/decisions/<decision_id>.yaml --explain
```

Machine-readable spike output now includes:
- `winner_reason` (compact code form, e.g. `why:diff_lines`)
- `winner_reason_code`
- `winner_reason_detail` (long explanation)
- `winner_vs_runner_up` (structured comparison payload)
- guarded accept fields: `accept_if_guard_enabled`, `accept_if_guard_passed`, `accept_if_guard_failures`, `accepted`

`feedback_policy.yaml` publish section example:

```yaml
publish:
  enabled: true
  backend: codeberg
  repository: your-user/your-repo
  token_env: CODEBERG_TOKEN
  base_url: https://codeberg.org
  labels: [bot-reported, hast-feedback]
  min_status: accepted
```

If `CODEBERG_TOKEN` is unset, publish falls back to `berg --non-interactive issue create`
using your existing `berg auth login` session.

## Documentation Control Plane

Use `hast docs generate` to refresh generated docs after meaningful project changes:

```bash
hast docs generate --window 14
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
hast docs mermaid --glob "docs/**/*.md" --open-index
```

## Security Gate Policy

Use `.ai/policies/security_policy.yaml` to enable bundled security scanners in gate:

```yaml
version: v1
enabled: true
fail_on_missing_tools: false
audit_file: ".ai/security/audit.jsonl"
dependency_scanner_mode: either  # either | all
gitleaks_enabled: true
semgrep_enabled: true
trivy_enabled: true
grype_enabled: true
# optional: temporary false-positive suppression
ignore_rules:
  - id: "SG-001"
    checks: ["semgrep"]
    pattern: "known false positive pattern"
    reason: "tracked in SEC-123"
    expires_on: "2026-12-31"
```

Behavior:
- `enabled: true` adds bundled checks (`gitleaks`, `semgrep`, dependency scan via `trivy`/`grype`).
- `dependency_scanner_mode: either` runs one available dependency scanner as `dependency_scan`.
- `fail_on_missing_tools: false` marks missing tools as skipped; `true` fails gate immediately.
- `ignore_rules` can temporarily suppress matching findings; applied/expired events are logged to `audit_file`.

Risk policy can add security-driven score and action controls via `.ai/policies/risk_policy.yaml`:
- `security_failed_check_bonus`, `security_missing_tool_bonus`, `security_expired_ignore_bonus`
- `security_force_block_on_failed_checks`, `security_force_block_on_missing_tools`

If `mmdc` is unavailable, Mermaid rendering is skipped with warnings (base docgen still succeeds).

WikiLink vault sync (`.knowledge/`):

```bash
hast docs sync-vault
```

Generated note groups:
- `.knowledge/Goal/G_*.md`
- `.knowledge/Decision/D_*.md`
- `.knowledge/Run/R_*.md`
- `.knowledge/Contract/C_*.md`

## Design

See [docs/design.md](docs/design.md) for full design document.
See [docs/scopes/](docs/scopes/) for scope-level design breakdowns.
