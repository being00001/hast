# devf Operation Scenario: Health Check API

This document describes a real-world usage scenario for `devf`'s Autonomous Architect and Swarm capabilities.

## Goal
Implement a standard `/health` endpoint for the application to verify system status.

## Workflow

### 1. Planning (Architect Phase)
**Command:** `devf plan "Add a standard /health endpoint that returns 200 OK"`

**Expected Outcome:**
*   **Architect AI** analyzes the request.
*   Creates **BDD Specification**: `features/health.feature`
*   Updates **Goals**: `.ai/goals.yaml` with a new goal `G_HEALTH`.

### 2. Execution (Worker Phase)
**Command:** `devf auto G_HEALTH` (triggered automatically by `plan --autonomous`)

**Step 2.1: Test Generation (RED)**
*   **Worker AI** reads `features/health.feature`.
*   Generates `tests/step_defs/test_health.py` using `pytest-bdd`.
*   **System** runs tests -> **FAIL** (Expected).

**Step 2.2: Implementation (GREEN)**
*   **Worker AI** reads the failing tests.
*   Creates/Edits `src/main.py` (or relevant file) to add the route.
*   **System** runs tests -> **PASS**.

### 3. Completion
*   Goal `G_HEALTH` is marked as `done`.
*   Changes are committed to git.
