# devf Architecture: The Autonomous Software Factory

This document visualizes the "Hierarchical Swarm" architecture of `devf`, implemented to enable autonomous feature development with safety and cost optimization.

## System Pipeline (Mermaid)

```mermaid
graph TD
    %% Actors
    User([User / L1])
    Architect[🤖 Architect AI / L2]
    Worker[👷 Worker AI / L3]
    Git((Git Repo))

    %% User Input
    User -->|devf plan "Add Feature"| Architect

    %% Planning Phase
    subgraph Planning [Phase 1: Planning]
        Architect -->|Reads| GoalsYaml[.ai/goals.yaml]
        Architect -->|Reads| Docs[docs/*.md]
        Architect -->|Thinks & Creates| Spec[features/login.feature]
        Architect -->|Updates| GoalsYaml
    end

    %% Execution Loop (Swarm)
    subgraph Execution [Phase 2: Execution Loop]
        direction TB
        
        GoalsYaml -->|Triggers| AutoLoop{devf auto}
        
        %% Step 1: Test Generation (Red)
        AutoLoop -->|Step 1: Gen Tests| Worker
        Spec -->|Input| Worker
        Worker -->|Writes| TestCode[tests/test_login.py]
        TestCode -->|Run Pytest| TestResult1{Test Failed?}
        TestResult1 -->|No (Green?)| Warn[Warning: Should be Red]
        TestResult1 -->|Yes (Red)| ImplStep

        %% Step 2: Implementation (Green)
        ImplStep[Step 2: Implement] -->|Input: Spec + Fail Log| Worker
        Worker -->|Modifies| SrcCode[src/*.py]
        SrcCode -->|Run Pytest| TestResult2{Test Passed?}
        
        %% Loop or Done
        TestResult2 -->|No (Fail)| Retry[Retry Loop]
        Retry -->|Max Retries?| Blocked[Status: Blocked]
        Retry -->|Not Max| ImplStep
        TestResult2 -->|Yes (Green)| Commit
    end

    %% Finalize
    Commit[Git Commit & Merge] -->|Update| Git
    Commit -->|Update| GoalsYaml
    GoalsYaml -->|Status: Done| User

    %% Safety Layer
    subgraph Safety [Safety Layer]
        Jail[🛡️ Filesystem Jail] -.-> Worker
        Limits[🛑 Loop Limits] -.-> AutoLoop
        Cache[💰 Prompt Caching] -.-> Worker
    end
```

## Key Components

### 1. The Architect (L2)
- **Role:** Project Manager & System Designer.
- **Action:** Translates vague user instructions into concrete BDD specifications (`.feature`) and actionable goals.
- **Engine:** `devf plan` (High-Intelligence Model e.g., Claude 3.5 Sonnet).

### 2. The Worker (L3)
- **Role:** Developer & QA Engineer.
- **Action:** Implements the BDD specs using a strict TDD/BDD cycle (Red -> Green).
- **Engine:** `devf auto` (Cost-Effective Model e.g., DeepSeek-V3 or Kimi).

### 3. The Safety Layer
- **Filesystem Jail:** Prevents AI from writing outside the project root (Anti-Path Traversal).
- **Circuit Breakers:** Stops infinite loops and excessive costs.
- **Prompt Caching:** Optimizes token usage by caching static project context (up to 90% savings).
