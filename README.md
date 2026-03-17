# hast

AI-native development session manager.

Session continuity, project state tracking, and verification pipeline for solo developer + AI coding agent workflows.

## Key Features

- **Code Map (Symbol Graph)**: AST-based project summary providing classes, methods, and signatures to reduce AI navigation cost.
- **Context Pack (XML)**: AI-optimized structured context format for higher instruction following accuracy.
- **Smart Scoping**: Intelligent context pruning using bidirectional dependency analysis and priority-based filtering.
- **Contract Enforcement**: Mandatory test files and acceptance criteria defined in `goals.yaml`.
- **Policy-Driven Retry/Triage**: Failure classes are normalized and retried/blocked by policy.
- **Risk Scoring**: Every attempt receives a `risk_score` for safer merge decisions.
- **Evidence Logging**: Attempts are logged in `.ai/runs/<run_id>/evidence.jsonl` with state/policy metadata.
- **Decision Parallelization**: Decision tickets + validation matrix scoring before implementation.
- **Runner Interface**: Pluggable architecture for executing sessions (Local, OpenHands, Docker).

## Installation

```bash
pip install hast
```

For development:

```bash
git clone https://github.com/being00001/hast.git
cd hast
pip install -e ".[dev]"
```

## Status

Pre-alpha. Active development of Swarm Orchestration.

## Security

hast executes commands defined in `.ai/config.yaml` (such as `ai_tool`, `test_command`).
**Never run `hast auto` in a repository with an untrusted `.ai/` directory.**

If you clone a repository that already contains `.ai/config.yaml`, review its contents before running hast commands.

## Quick Start

```bash
hast init                        # Initialize .ai/ directory with config and policies
hast doctor                      # Preflight diagnostics
hast map                         # View the codebase symbol map
hast context --format pack       # Get AI-optimized context
hast auto                        # Run automated goal execution loop
hast auto --dry-run              # Preview without executing
```

## CLI Reference

Beyond the basics above, hast provides commands for the full development lifecycle:

### Goal Execution

```bash
hast auto G_LOGIN --tool codex           # Run specific goal with a specific tool
hast auto ROOT --recursive --parallel 3  # Parallel execution
hast retry G_LOGIN                       # Reactivate blocked goal + rerun
hast sim G_LOGIN --run-tests             # Predict blockers before auto
```

### Context & Exploration

```bash
hast focus --tool codex                  # Build session pack for Codex/Claude
hast explore "How does auth work?"       # Read-only design exploration
```

### Observability

```bash
hast metrics                             # Aggregate evidence metrics (7-day default)
hast triage --run-id <id>                # Per-attempt policy triage rows
hast observe baseline --window 14        # Observability baseline
hast events replay                       # Replay shadow bus events
```

### Execution Queue

```bash
hast queue claim --worker codex --role implement --goal G_LOGIN --idempotency-key req-123
hast queue release QCLM_abc123 --worker codex --goal-status done
hast queue list --active-only
```

### Feedback & Proposals

```bash
hast feedback note --lane project --category workflow_friction --impact medium --expected "..." --actual "..."
hast feedback analyze --run-id <id>
hast feedback backlog --window 14 --lane project --promote
hast orchestrate --run-id <id> --window 14 --max-goals 5
hast propose note --category risk --impact high --title "..."
```

### Decisions

```bash
hast decision new G_AUTH --question "Which auth strategy?" --alternatives A,B,C
hast decision evaluate .ai/decisions/<id>.yaml --accept
hast decision spike .ai/decisions/<id>.yaml --parallel 3 --backend auto
```

### Documentation

```bash
hast docs generate --window 14           # Refresh generated docs
hast docs mermaid --open-index           # Render Mermaid diagrams
hast docs sync-vault                     # Sync WikiLink vault
```

Machine-readable output is available on major commands with `--json`.

## Configuration

### Tool Routing

`hast auto` can run local CLI tools or API models:

```yaml
# .ai/config.yaml
test_command: "pytest"
ai_tool: "claude -p {prompt_file}"
ai_tools:
  codex: "codex exec {prompt_file}"
  gemini: "gemini -p {prompt_file}"
  claude: "claude -p {prompt_file}"
```

```bash
hast plan "Add login feature" --tool codex
hast auto G_LOGIN --tool codex
```

### Goal Configuration

```yaml
# .ai/goals.yaml
goals:
  - id: G_LOGIN
    title: "Implement Login"
    status: active
    spec_file: "features/login.feature"
    depends_on: [G_AUTH]
    owner_agent: worker
    languages: [python]
```

- `depends_on`: scheduler executes goals in dependency-safe batches
- `owner_agent`: role-based file scope guardrails (`tester|worker|architect|gatekeeper`)
- `uncertainty: high` + `decision_file`: enforce "decide-first, implement-later" gate

### Acceptance Contracts

Pin a goal to an immutable contract:

```yaml
# .ai/contracts/login.contract.yaml
version: 1
inputs:
  - "email/password"
outputs:
  - "access token"
must_fail_tests:
  - "tests/test_login.py"
must_pass_tests:
  - "tests/test_login.py"
required_changes:
  - "src/auth.py"
forbidden_changes:
  - "tests/*"
  - "features/*"
```

### Merge Train + Risk Controls

```yaml
# .ai/config.yaml
merge_train:
  pre_merge_command: "pytest -q"
  post_merge_command: "pytest tests/smoke -q"
  auto_rollback: true
```

### Policy Files

`hast init` creates `.ai/policies/` templates including:

- `retry_policy.yaml`: retry limits and actions per failure classification
- `risk_policy.yaml`: risk score model by phase/path/failure type
- `security_policy.yaml`: bundled security scanner gate (`gitleaks`, `semgrep`, `trivy`/`grype`)
- `immune_policy.yaml`: autonomous edit grant/TTL/protected-path guardrails
- `feedback_policy.yaml`: feedback promotion/dedup defaults
- `docs_policy.yaml`: stale-doc warning/block policy

And more. See `hast init` output for the full list.

## Quality Gates

```bash
pre-commit install
pre-commit install --hook-type pre-push
pre-commit run --all-files
```

The default bundle runs:
- ruff lint (Python)
- mypy type checks (core modules)
- pytest suite
- conditional Rust gates (`cargo fmt --check`, `cargo clippy`) when `Cargo.toml` exists

## License

[MIT](LICENSE)

## Design

See [docs/design.md](docs/design.md) for the full design document.
