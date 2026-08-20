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
Phase 9.2: Constraint Reasoning & Feasibility Analysis [PENDING]
Phase 9.3: Dynamic Plan Optimization & Strategy Selection [PENDING]
Phase 9.4: Multi-Agent Role Specialization & Subgoal Delegation [PENDING]
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
