# devf

AI-native development session manager.

Session continuity, project state tracking, and verification pipeline for solo developer + AI coding agent workflows.

## Status

Pre-alpha. Design phase.

## Install (future)

```bash
pip install devf
```

## Quick Start (future)

```bash
devf init
devf goal add M1 "User Authentication"
devf session start --goal M1
# ... work with AI ...
devf handoff create
devf validate
devf session end
devf context   # generate context for next AI session
```

## Design

See [docs/design.md](docs/design.md) for full design document.
See [docs/scopes/](docs/scopes/) for scope-level design breakdowns.
