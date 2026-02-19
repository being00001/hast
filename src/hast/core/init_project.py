"""Project initialization."""

from __future__ import annotations

import json as _json
from datetime import datetime as _datetime
from pathlib import Path


_GITIGNORE_SENTINEL = "# --- hast runtime artifacts (auto-managed) ---"

GITIGNORE_PATTERNS = """\
# --- hast runtime artifacts (auto-managed) ---
.ai/runs/
.ai/attempts/
.ai/sessions/
.ai/handoffs/
.ai/events/
.ai/feedback/
.ai/proposals/
.ai/decisions/spikes/
.ai/decisions/evidence.jsonl
.ai/protocols/
.ai/security/
.ai/immune/audit.jsonl
.ai/state/
.ai/queue/
.ai/auto.lock
.ai/.pre-commit-cache/
.ai/archive/
# --- end hast runtime artifacts ---
"""


def _ensure_gitignore(root: Path) -> Path | None:
    """Append hast runtime patterns to .gitignore if not already present.

    Returns the path if modified, None if already up-to-date.
    """
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if _GITIGNORE_SENTINEL in existing:
            return None
    else:
        existing = ""

    separator = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(
        existing + separator + GITIGNORE_PATTERNS,
        encoding="utf-8",
    )
    return gitignore_path


CONFIG_TEMPLATE = """test_command: "pytest"
ai_tool: "claude -p {prompt}"
# always_allow_changes:
#   - "docs/ARCHITECTURE.md"
#   - "src/protocols.py"
# language_profiles:
#   rust:
#     targeted_test_command: "cargo test"
#     gate_commands:
#       - "cargo test"
#       - "cargo fmt --check"
#       - "cargo clippy -- -D warnings"
# gate:
#   required_checks: ["pytest"]
#   mutation_enabled: true
#   mutation_high_risk_only: true
#   mutation_python_command: "mutmut run --paths-to-mutate src"
#   mutation_rust_command: "cargo mutants --timeout 300"
#   min_mutation_score_python: 70
#   min_mutation_score_rust: 60
#   pytest_parallel: true
#   pytest_workers: "auto"
#   pytest_reruns_on_flaky: 2
#   pytest_random_order: true
#   security_commands:
#     - "gitleaks detect --no-git --source ."
"""

GOALS_TEMPLATE = """goals: []
"""

RULES_TEMPLATE = """# .ai/rules.md

## Verification
- Run tests before committing
- Commit only after tests pass

## Commit Format
{type}({goal_id}): {description}
types: feat, fix, refactor, test, docs, chore
"""

RETRY_POLICY_TEMPLATE = """version: v1
default_max_retries: 3
no_repeat_same_classification: true
max_retries_by_classification:
  spec-ambiguous: 1
  test-defect: 2
  impl-defect: 3
  env-flaky: 2
  dep-build: 1
  security: 0
actions:
  exceed_limit: block
  no_repeat_same: escalate
"""

RISK_POLICY_TEMPLATE = """version: v1
max_score: 100
success_base_score: 15
sensitive_path_weight: 20
security_failed_check_bonus: 15
security_missing_tool_bonus: 5
security_expired_ignore_bonus: 10
security_force_block_on_failed_checks: true
security_force_block_on_missing_tools: false
block_threshold: 95
rollback_threshold: 80
base_score_by_classification:
  spec-ambiguous: 55
  test-defect: 45
  impl-defect: 40
  env-flaky: 35
  dep-build: 70
  security: 90
phase_weights:
  plan: 5
  implement: 10
  bdd-red: 10
  bdd-green: 15
  gate: 20
  merge: 25
  legacy: 10
sensitive_path_patterns:
  - "src/**/auth*.py"
  - "src/**/security*.py"
  - ".github/workflows/*"
  - "pyproject.toml"
  - "requirements*.txt"
"""

TRANSITION_POLICY_TEMPLATE = """version: v1
states:
  - planned
  - red_verified
  - green_verified
  - review_ready
  - merged
"""

MODEL_ROUTING_TEMPLATE = """version: v1
defaults:
  normal: worker
  high_risk: architect
rules:
  - when_phase: plan
    use: architect
  - when_phase: adversarial
    use: tester
"""

FEEDBACK_POLICY_TEMPLATE = """version: v1
enabled: true
promotion:
  min_frequency: 3
  min_confidence: 0.6
  auto_promote_impact: high
dedup:
  strategy: fingerprint_v1
publish:
  enabled: false
  backend: codeberg
  repository: ""
  token_env: CODEBERG_TOKEN
  base_url: https://codeberg.org
  labels:
    - bot-reported
    - hast-feedback
  min_status: accepted
"""

ADMISSION_POLICY_TEMPLATE = """version: v1
enabled: true
promotion:
  min_frequency: 2
  min_confidence: 0.6
  ttl_days: 30
  high_risk_fast_track: true
  max_fast_track_overflow: 1
  goal_root_id: PX_2X
  owner_agent: architect
  max_promote_per_run: 20
dedup:
  strategy: fingerprint_v1
"""

DOCS_POLICY_TEMPLATE = """version: v1
freshness:
  warn_stale: true
  block_on_high_risk: true
  high_risk_path_patterns:
    - "src/**/auth*.py"
    - "src/**/security*.py"
    - ".github/workflows/*"
    - "pyproject.toml"
    - "requirements*.txt"
"""

IMMUNE_POLICY_TEMPLATE = """version: v1
enabled: false
require_grant_for_writes: true
grant_file: ".ai/immune/grant.yaml"
audit_file: ".ai/immune/audit.jsonl"
max_changed_files: 120
protected_path_patterns:
  - ".ai/policies/**"
  - ".ai/protocols/**"
  - ".ai/immune/**"
"""

SECURITY_POLICY_TEMPLATE = """version: v1
enabled: false
fail_on_missing_tools: false
audit_file: ".ai/security/audit.jsonl"
dependency_scanner_mode: either
gitleaks_enabled: true
gitleaks_command: "gitleaks detect --no-git --source ."
semgrep_enabled: true
semgrep_command: "semgrep scan --config auto --error"
trivy_enabled: true
trivy_command: "trivy fs --severity HIGH,CRITICAL --exit-code 1 ."
grype_enabled: true
grype_command: "grype . --fail-on high"
# ignore_rules:
#   - id: "SG-001"
#     checks: ["semgrep"]
#     pattern: "known false positive pattern"
#     reason: "tracked in SECURITY-123"
#     expires_on: "2026-12-31"
"""

SPIKE_POLICY_TEMPLATE = """version: v1
prefer_lower_diff_lines: true
prefer_lower_changed_files: true
include_duration_tiebreaker: false
"""

EXECUTION_QUEUE_POLICY_TEMPLATE = """version: v1
default_lease_ttl_minutes: 30
max_lease_ttl_minutes: 240
max_active_claims_per_worker: 1
"""

OBSERVABILITY_POLICY_TEMPLATE = """version: v1
thresholds:
  min_goal_runs: 5
  first_pass_success_rate_min: 0.40
  block_rate_max: 0.35
  security_incident_rate_max: 0.20
  claim_collision_rate_max: 0.15
  mttr_minutes_max: 180
"""

EVENT_BUS_POLICY_TEMPLATE = """version: v1
enabled: false
shadow_mode: true
emit_from_evidence: true
emit_from_queue: true
emit_from_orchestrator: true
auto_reduce_on_emit: false
"""

OPERATOR_INBOX_POLICY_TEMPLATE = """version: v1
default_top_k: 10
transitions:
  security_failure:
    approve: [active]
    reject: [blocked]
    defer: []
  action_block:
    approve: [active]
    reject: [blocked]
    defer: []
  action_escalate:
    approve: [active]
    reject: [blocked]
    defer: []
  baseline_blocked:
    approve: [active]
    reject: [blocked]
    defer: []
  claim_collision:
    approve: [active]
    reject: []
    defer: []
"""

CONSUMER_ROLE_POLICY_TEMPLATE = """version: v1
default_role: implement
phase_to_role:
  plan: implement
  implement: implement
  adversarial: test
  gate: verify
  review: verify
"""

PROTOCOL_ADAPTER_POLICY_TEMPLATE = """version: v1
enabled_adapters:
  - langgraph
  - openhands
default_export_context_format: pack
include_context_by_default: true
include_prompt_by_default: true
max_context_chars: 200000
require_goal_exists: true
result_inbox_dir: ".ai/protocols/inbox"
processed_results_dir: ".ai/protocols/processed"
poll_interval_seconds: 2
max_wait_seconds: 900
require_packet_id_match: true
archive_consumed_packets: true
"""

DECISION_TICKET_TEMPLATE = """decision:
  version: 1
  decision_id: "D_EXAMPLE"
  goal_id: "G_EXAMPLE"
  question: "Which approach should we choose?"
  status: "proposed"
  owner: "architect"
  alternatives:
    - id: "A"
      hypothesis: ""
      approach: ""
      tradeoffs: []
    - id: "B"
      hypothesis: ""
      approach: ""
      tradeoffs: []
  validation_matrix:
    - criterion: "contract_fit"
      weight: 30
      min_score: 3
      description: "Meets acceptance contract as written."
    - criterion: "regression_risk"
      weight: 20
      min_score: 3
      description: "Reduces regression risk."
    - criterion: "operability"
      weight: 20
      min_score: 3
      description: "Easy to observe/rollback."
    - criterion: "delivery_speed"
      weight: 15
      min_score: 2
      description: "Fast to ship with low rework."
    - criterion: "security_posture"
      weight: 15
      min_score: 3
      description: "Secure-by-default behavior."
  scores:
    A: {}
    B: {}
  selected_alternative: null
  decision_reason: ""
  next_actions: []
  evidence_refs: []
"""

DECISION_EVIDENCE_SCHEMA_TEMPLATE = """version: decision_evidence.v1
type: jsonl_row
required:
  - timestamp
  - event_type
  - decision_id
  - goal_id
  - winner_id
  - winner_eligible
  - winner_score
  - ranking
  - classification
  - action_taken
properties:
  timestamp: "ISO-8601 datetime string"
  event_type: "decision_evaluation"
  decision_id: "Decision ticket id"
  goal_id: "Related goal id"
  decision_file: "Path to decision file"
  question: "Decision question text"
  winner_id: "Selected alternative id"
  winner_eligible: "Boolean threshold pass/fail"
  winner_score: "Weighted score (0-100)"
  ranking: "List of alternatives with score/eligibility"
  status: "Decision status at logging time"
  classification: "decision-accepted | decision-blocked"
  action_taken: "advance | escalate"
  actor: "Who evaluated the decision"
  run_id: "Optional .ai/runs/<run_id> link"
  evidence_refs: "Optional refs to spike/test evidence"
  schema_version: "decision_evidence.v1"
"""

CONTROL_PLANE_EVIDENCE_SCHEMA_TEMPLATE = """version: control_plane_evidence.v1
type: jsonl_row
required:
  - timestamp
  - run_id
  - goal_id
  - phase
  - attempt
  - success
  - should_retry
  - classification
  - action_taken
  - event_type
  - contract_version
properties:
  event_type: "auto_attempt | goal_invalidation | decision_spike"
  action_taken: "advance | retry | escalate | block | rollback"
  failure_classification: "null or triage taxonomy class"
  contract_warnings: "Optional list[str] when contract checks detect semantic mismatch"
  contract_version: "Control-plane contract version. Example: cp.v1"
"""

PRECOMMIT_TEMPLATE = """minimum_pre_commit_version: "3.7.0"
default_stages: [pre-commit, pre-push]

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-merge-conflict
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-yaml

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        additional_dependencies:
          - types-PyYAML

  - repo: local
    hooks:
      - id: cargo-fmt
        name: cargo fmt --check (if Rust workspace present)
        entry: bash -lc 'if [ -f Cargo.toml ]; then cargo fmt --check; else echo "skip cargo fmt (no Cargo.toml)"; fi'
        language: system
        pass_filenames: false
        stages: [pre-push]

      - id: cargo-clippy
        name: cargo clippy -- -D warnings (if Rust workspace present)
        entry: bash -lc 'if [ -f Cargo.toml ]; then cargo clippy -- -D warnings; else echo "skip cargo clippy (no Cargo.toml)"; fi'
        language: system
        pass_filenames: false
        stages: [pre-push]
"""


def init_project(root: Path) -> list[Path]:
    ai_dir = root / ".ai"
    created: list[Path] = []

    ai_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = ai_dir / ".hast-metadata"
    if not metadata_path.exists():
        from hast import __version__

        payload = {
            "tool": "hast",
            "version": __version__,
            "created_at": _datetime.now().astimezone().isoformat(),
        }
        metadata_path.write_text(
            _json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(metadata_path)

    sessions_dir = ai_dir / "sessions"
    if not sessions_dir.exists():
        sessions_dir.mkdir(parents=True, exist_ok=True)
        created.append(sessions_dir)

    handoffs_dir = ai_dir / "handoffs"
    if not handoffs_dir.exists():
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        created.append(handoffs_dir)

    decisions_dir = ai_dir / "decisions"
    if not decisions_dir.exists():
        decisions_dir.mkdir(parents=True, exist_ok=True)
        created.append(decisions_dir)

    proposals_dir = ai_dir / "proposals"
    if not proposals_dir.exists():
        proposals_dir.mkdir(parents=True, exist_ok=True)
        created.append(proposals_dir)

    templates_dir = ai_dir / "templates"
    if not templates_dir.exists():
        templates_dir.mkdir(parents=True, exist_ok=True)
        created.append(templates_dir)

    protocols_dir = ai_dir / "protocols"
    if not protocols_dir.exists():
        protocols_dir.mkdir(parents=True, exist_ok=True)
        created.append(protocols_dir)

    schemas_dir = ai_dir / "schemas"
    if not schemas_dir.exists():
        schemas_dir.mkdir(parents=True, exist_ok=True)
        created.append(schemas_dir)

    config_path = ai_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        created.append(config_path)

    goals_path = ai_dir / "goals.yaml"
    if not goals_path.exists():
        goals_path.write_text(GOALS_TEMPLATE, encoding="utf-8")
        created.append(goals_path)

    rules_path = ai_dir / "rules.md"
    if not rules_path.exists():
        rules_path.write_text(RULES_TEMPLATE, encoding="utf-8")
        created.append(rules_path)

    policies_dir = ai_dir / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)

    retry_policy_path = policies_dir / "retry_policy.yaml"
    if not retry_policy_path.exists():
        retry_policy_path.write_text(RETRY_POLICY_TEMPLATE, encoding="utf-8")
        created.append(retry_policy_path)

    risk_policy_path = policies_dir / "risk_policy.yaml"
    if not risk_policy_path.exists():
        risk_policy_path.write_text(RISK_POLICY_TEMPLATE, encoding="utf-8")
        created.append(risk_policy_path)

    transition_policy_path = policies_dir / "transition_policy.yaml"
    if not transition_policy_path.exists():
        transition_policy_path.write_text(TRANSITION_POLICY_TEMPLATE, encoding="utf-8")
        created.append(transition_policy_path)

    model_routing_path = policies_dir / "model_routing.yaml"
    if not model_routing_path.exists():
        model_routing_path.write_text(MODEL_ROUTING_TEMPLATE, encoding="utf-8")
        created.append(model_routing_path)

    feedback_policy_path = policies_dir / "feedback_policy.yaml"
    if not feedback_policy_path.exists():
        feedback_policy_path.write_text(FEEDBACK_POLICY_TEMPLATE, encoding="utf-8")
        created.append(feedback_policy_path)

    admission_policy_path = policies_dir / "admission_policy.yaml"
    if not admission_policy_path.exists():
        admission_policy_path.write_text(ADMISSION_POLICY_TEMPLATE, encoding="utf-8")
        created.append(admission_policy_path)

    docs_policy_path = policies_dir / "docs_policy.yaml"
    if not docs_policy_path.exists():
        docs_policy_path.write_text(DOCS_POLICY_TEMPLATE, encoding="utf-8")
        created.append(docs_policy_path)

    immune_policy_path = policies_dir / "immune_policy.yaml"
    if not immune_policy_path.exists():
        immune_policy_path.write_text(IMMUNE_POLICY_TEMPLATE, encoding="utf-8")
        created.append(immune_policy_path)

    security_policy_path = policies_dir / "security_policy.yaml"
    if not security_policy_path.exists():
        security_policy_path.write_text(SECURITY_POLICY_TEMPLATE, encoding="utf-8")
        created.append(security_policy_path)

    spike_policy_path = policies_dir / "spike_policy.yaml"
    if not spike_policy_path.exists():
        spike_policy_path.write_text(SPIKE_POLICY_TEMPLATE, encoding="utf-8")
        created.append(spike_policy_path)

    execution_queue_policy_path = policies_dir / "execution_queue_policy.yaml"
    if not execution_queue_policy_path.exists():
        execution_queue_policy_path.write_text(
            EXECUTION_QUEUE_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(execution_queue_policy_path)

    observability_policy_path = policies_dir / "observability_policy.yaml"
    if not observability_policy_path.exists():
        observability_policy_path.write_text(
            OBSERVABILITY_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(observability_policy_path)

    event_bus_policy_path = policies_dir / "event_bus_policy.yaml"
    if not event_bus_policy_path.exists():
        event_bus_policy_path.write_text(
            EVENT_BUS_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(event_bus_policy_path)

    operator_inbox_policy_path = policies_dir / "operator_inbox_policy.yaml"
    if not operator_inbox_policy_path.exists():
        operator_inbox_policy_path.write_text(
            OPERATOR_INBOX_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(operator_inbox_policy_path)

    consumer_role_policy_path = policies_dir / "consumer_role_policy.yaml"
    if not consumer_role_policy_path.exists():
        consumer_role_policy_path.write_text(
            CONSUMER_ROLE_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(consumer_role_policy_path)

    protocol_adapter_policy_path = policies_dir / "protocol_adapter_policy.yaml"
    if not protocol_adapter_policy_path.exists():
        protocol_adapter_policy_path.write_text(
            PROTOCOL_ADAPTER_POLICY_TEMPLATE,
            encoding="utf-8",
        )
        created.append(protocol_adapter_policy_path)

    decision_template_path = templates_dir / "decision_ticket.yaml"
    if not decision_template_path.exists():
        decision_template_path.write_text(DECISION_TICKET_TEMPLATE, encoding="utf-8")
        created.append(decision_template_path)

    decision_schema_path = schemas_dir / "decision_evidence.schema.yaml"
    if not decision_schema_path.exists():
        decision_schema_path.write_text(DECISION_EVIDENCE_SCHEMA_TEMPLATE, encoding="utf-8")
        created.append(decision_schema_path)

    control_plane_schema_path = schemas_dir / "control_plane_evidence.schema.yaml"
    if not control_plane_schema_path.exists():
        control_plane_schema_path.write_text(
            CONTROL_PLANE_EVIDENCE_SCHEMA_TEMPLATE,
            encoding="utf-8",
        )
        created.append(control_plane_schema_path)

    precommit_template_path = templates_dir / "pre-commit-config.yaml"
    if not precommit_template_path.exists():
        precommit_template_path.write_text(PRECOMMIT_TEMPLATE, encoding="utf-8")
        created.append(precommit_template_path)

    gitignore_result = _ensure_gitignore(root)
    if gitignore_result is not None:
        created.append(gitignore_result)

    return created
