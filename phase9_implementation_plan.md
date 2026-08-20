# FRIDAY — PHASE 9 IMPLEMENTATION PLAN
## Autonomous Goal Understanding, Reasoning & Hierarchical Planning

**Document Version**: 1.0.0  
**Phase Status**: IN PROGRESS (Phase 9.1 Complete)  
**Baseline Commit**: `c3eb8d677c48eeeea781429c729e2522278e2768` (Phase 8 Officially Closed & Verified)  
**Current Subphase**: Phase 9.1 (Autonomous Goal Understanding & Hierarchical Decomposition)  
**IBM Quantum Status**: RESERVED FOR FUTURE SPECIALIZED COMPUTE PHASE  

---

## 1. Executive Summary & Goals

Phase 9 upgrades FRIDAY's cognitive reasoning pipeline from low-level imperative plan decomposition to **autonomous, goal-driven reasoning and intent understanding**. Phase 9.1 establishes the structured `Goal` layer:
- Converting ambiguous, multimodal, or compound user requests into normalized `Goal` models.
- Differentiating between information requests, planning requests, computer-control requests, multi-step tasks, and long-running background tasks.
- Hierarchical Subgoal Decomposition with acyclic DAG dependencies.
- Zero-trust security: Request interpretation NEVER directly executes tools or computer control actions.

---

## 2. Subphase Roadmap for Phase 9

```
Phase 9.1: Autonomous Goal Understanding & Decomposition [COMPLETE]
Phase 9.2: Hierarchical Task Planning & Dependency DAG [COMPLETE]
Phase 9.3: Intelligent Multi-Step Execution Orchestrator [COMPLETE]
Phase 9.4: Formal Verification, Self-Correction & Bounded Recovery [COMPLETE]
Phase 9.5: Autonomous Hypothesis Testing & World-Model Calibration [PENDING]
Phase 9.6: Phase 9 Full Autonomous Cognitive Acceptance Gate [PENDING]
```

---

## 3. Subphase 9.1 Specifications & Verification [COMPLETE]

- **Components Implemented**:
  1. `Goal`: Structured container with `goal_id`, `original_request`, `normalized_intent`, `desired_outcome`, `request_type`, `constraints`, `required_capabilities`, `dependencies`, `risk_level`, `authorization_requirements`, `success_conditions`, `cancellation_conditions`, and `subgoals`.
  2. `GoalRequestType`: `INFORMATION_REQUEST`, `PLANNING_REQUEST`, `COMPUTER_CONTROL_REQUEST`, `MULTI_STEP_TASK`, `LONG_RUNNING_TASK`, `AMBIGUOUS_REQUEST`, `PROHIBITED_REQUEST`.
  3. `GoalRiskLevel`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
  4. `SubGoal`: Child subgoal model supporting DAG dependency associations.
  5. `GoalUnderstandingEngine`: Converts natural language prompts into normalized Goal objects, performs heuristic safety analysis, detects contradictory constraints, flags prohibited intents, and generates clarification prompts when underspecified.
- **Files Created/Modified**:
  - `src/friday/agent/goal.py`
  - `src/friday/agent/__init__.py`
  - `tests/test_goal_understanding.py` (10/10 tests passing)
- **Security & Architectural Invariants**:
  - `Proposal != Execution` preserved.
  - Zero raw screenshot persistence and secret redaction active.
  - 100% provider-independent (works with `MockLLMProvider` and cloud backends).

---

## 4. Subphase 9.2 Specifications & Verification [COMPLETE]

- **Components Implemented**:
  1. `TaskPlan` & `PlanStep` typed DAG enhancements:
     - `compute_topological_schedule`: Groups plan steps into topological waves for concurrent safe execution.
     - Cycle detection: Detects and rejects circular dependency loops (`PlanValidationError`).
     - Validation: Pre-execution validation checking step existence, self-dependencies, unavailable capabilities, unknown tools, and invalid schemas.
     - Typed step extensions: `expected_output_type`, `required_capabilities`, `rollback_step_id`, and `checkpoint_enabled`.
  2. `GoalDecomposer.create_from_goal`: Converts structured `Goal` instances into executable `TaskPlan` objects. Rejects ambiguous or prohibited goals prior to execution.
  3. Zero-execution guarantee during planning: Planning never executes tools or OS actions directly.
- **Files Created/Modified**:
  - `src/friday/agent/planner.py`
  - `tests/test_hierarchical_planning_dag.py` (10/10 tests passing)
  - `tests/test_task_planner.py`
- **Verification**:
  - Full automated suite: 503 passed, 5 deselected in 71.52s.

---

## 5. Subphase 9.3 Specifications & Verification [COMPLETE]

- **Components Implemented**:
  1. Explicit Step Lifecycle States:
     - `StepStatus`: `PENDING`, `READY`, `RUNNING`, `WAITING`, `COMPLETED` / `SUCCEEDED`, `FAILED`, `SKIPPED`, `BLOCKED`, `CANCELLED`, `ROLLED_BACK`.
  2. Multi-Step Execution Orchestration:
     - Dependency waiting & cascading: Prerequisite checks verify completion prior to executing downstream steps; failed prerequisites skip downstream tasks cleanly.
     - Idempotency protection: Deduplicates state-modifying actions via execution fingerprinting to prevent accidental double-execution during retries.
     - Bounded timeout & thread isolation: Enforces per-step timeouts (`ThreadPoolExecutor` timeout handling) preventing hangs.
     - Computer Control & Authorization Gating: Directly routes through `BaseAuthorizer` and proposal verification before any sensitive/dangerous action executes.
     - Perception Integration: Visual and screen tasks verified against `StepVerifier` success criteria.
- **Files Created/Modified**:
  - `src/friday/agent/planner.py`
  - `src/friday/agent/executor.py`
  - `tests/test_multi_step_orchestrator.py` (6/6 tests passing)
- **Verification**:
  - Full automated suite: 509 passed, 5 deselected in 80.24s.

---

## 6. Subphase 9.4 Specifications & Verification [COMPLETE]

- **Components Implemented**:
  1. Formal Assertion Engine (`StepVerifier`):
     - Added support for multiple structured assertion types: `regex:<pattern>`, `contains:<substr>`, `not_contains:<substr>`, `json_key:<key>`, `min_length:<int>`, and `exact:<str>`.
     - Validates actual real-world outcome contracts instead of assuming successful tool return codes represent real-world goal completion.
  2. Bounded Self-Correction & Diagnosis (`SelfCorrectionPolicy`, `FailureAnalyzer`, `AutonomousRecoveryManager`):
     - Automatic classification into `FailureType` (transient errors, verification failures, tool errors, parameter schema issues).
     - Adaptive strategy selection (`RETRY`, `ALTERNATIVE_TOOL`, `CREDENTIAL_FAILOVER`, `ADJUST_PARAMETERS`, `ABORT_TASK`).
     - Strict execution bounds preventing retry storms and infinite loops (enforces per-step retry limits and global task budgets).
     - Unconditional hard-block protection: Strictly forbids self-correcting around safety denials, authorization blocks, destructive actions, or policy restrictions.
- **Files Created/Modified**:
  - `src/friday/agent/verification.py`
  - `src/friday/agent/recovery.py`
  - `tests/test_verification_and_bounded_recovery.py` (4/4 tests passing)
- **Verification**:
  - Full automated suite: 513 passed, 5 deselected in 96.98s.



