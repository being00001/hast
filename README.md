# devf

AI-native development session manager.

Session continuity, project state tracking, and verification pipeline for solo developer + AI coding agent workflows.

## Key Features (AI-Native)

- **Code Map (Symbol Graph)**: AST-based project summary providing classes, methods, and signatures to reduce AI navigation cost.
- **Context Pack (XML)**: AI-optimized structured context format for higher instruction following accuracy.
- **Smart Scoping (Tier 1 & 2)**: Intelligent context pruning using bidirectional dependency analysis and priority-based filtering (src > tests > docs).
- **Contract Enforcement**: Mandatory test files and acceptance criteria defined in `goals.yaml`.
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
```

## Design

See [docs/design.md](docs/design.md) for full design document.
See [docs/scopes/](docs/scopes/) for scope-level design breakdowns.
