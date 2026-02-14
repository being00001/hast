"""Project initialization."""

from __future__ import annotations

from pathlib import Path


CONFIG_TEMPLATE = """test_command: "pytest"
ai_tool: "claude -p {prompt}"
# language_profiles:
#   rust:
#     targeted_test_command: "cargo test"
#     gate_commands:
#       - "cargo test"
#       - "cargo fmt --check"
#       - "cargo clippy -- -D warnings"
# gate:
#   required_checks: ["pytest"]
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
    - devf-feedback
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

PRECOMMIT_TEMPLATE = """repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        additional_dependencies: []
  - repo: local
    hooks:
      - id: cargo-fmt
        name: cargo fmt --check
        entry: cargo fmt --check
        language: system
        pass_filenames: false
      - id: cargo-clippy
        name: cargo clippy -- -D warnings
        entry: cargo clippy -- -D warnings
        language: system
        pass_filenames: false
"""


def init_project(root: Path) -> list[Path]:
    ai_dir = root / ".ai"
    created: list[Path] = []

    ai_dir.mkdir(parents=True, exist_ok=True)
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

    decision_template_path = templates_dir / "decision_ticket.yaml"
    if not decision_template_path.exists():
        decision_template_path.write_text(DECISION_TICKET_TEMPLATE, encoding="utf-8")
        created.append(decision_template_path)

    decision_schema_path = schemas_dir / "decision_evidence.schema.yaml"
    if not decision_schema_path.exists():
        decision_schema_path.write_text(DECISION_EVIDENCE_SCHEMA_TEMPLATE, encoding="utf-8")
        created.append(decision_schema_path)

    precommit_template_path = templates_dir / "pre-commit-config.yaml"
    if not precommit_template_path.exists():
        precommit_template_path.write_text(PRECOMMIT_TEMPLATE, encoding="utf-8")
        created.append(precommit_template_path)

    return created
