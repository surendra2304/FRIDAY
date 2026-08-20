# FRIDAY — Phase 7 Implementation Plan: Advanced Autonomous Reasoning & Multi-Step Task Execution

**Document Version**: 1.0.0  
**Phase**: Phase 7 (Autonomous Reasoning, Goal Tracking & Multi-Step Task Execution)  
**Date**: 2026-08-20  
**Baseline Commit**: `604236843c308b0bb7c925b1e3aba29b580d5e42`  
**Status**: DRAFT / APPROVED FOR IMPLEMENTATION  

---

## 1. Executive Summary & Phase 7 Goal

Phase 6 successfully established multimodal vision, screen understanding, safe snapshot capturing, live voice integration, credential failover, and hard-blocked computer action proposals (`Proposal != Execution`). 

The goal of **Phase 7** is to elevate FRIDAY from a single-turn reactive agent into an **autonomous, self-correcting, multi-step problem solver** capable of decomposing complex goals into planned stages, executing actions with strict verification, maintaining active task state across interruptions, and recovering from failures—all while preserving zero-trust security, provider independence, and strict authorization boundaries.

---

## 2. Current Architecture & Gap Analysis

| Architecture Area | Current Implementation State | Identified Gaps for Phase 7 |
| :--- | :--- | :--- |
| **Reasoning State Machine** | **PARTIAL**: Basic `max_tool_iterations` while-loop inside `FridayAgent.process_message`. | No explicit state machine (`UNDERSTANDING`, `PLANNING`, `EXECUTING`, `VERIFYING`, `COMPLETED`, `FAILED`). No structured state transitions. |
| **Task Planning** | **PARTIAL**: Dynamic single-step tool calling driven entirely by prompt and model response. | No formal `TaskPlan`, step decomposition, dependency tracking, or pre-execution validation before execution. |
| **Multi-Step Execution** | **PARTIAL**: Sequential and parallel tool batch execution exists in `agent.py`. | No step-by-step progress tracking, pause/resume capability, or partial rollback on step failure. |
| **Verification & Self-Correction** | **MISSING**: Agent accepts tool output as truth and returns response directly without asserting post-conditions. | No structured verification stage (`assert_task_outcome`), deterministic criteria checks, or active replanning loops. |
| **Task Memory & Working Context** | **PARTIAL**: SQLite conversation memory stores full message history; semantic embeddings and FTS recall historical context. | No decoupled **Short-Term Working Task State** (`ActiveTaskContext`) to prevent context contamination across long sub-tasks. |
| **Failure Recovery** | **PARTIAL**: Credential pool handles 429/quota failover; tool execution catches generic exceptions. | No automated strategy adaptation (e.g. tool fallback, alternative query generation, retry budgeting). |
| **Interruption & Resumption** | **PARTIAL**: Gemini Live handles server VAD and voice interruption; background scheduler handles interval cron. | Active multi-step agent tasks cannot be paused mid-flight, checkpointed to SQLite, and resumed seamlessly. |
| **Long-Running Task Management**| **PARTIAL**: `TaskScheduler` in `tasks/scheduler.py` handles periodic cron tasks. | Disconnected from `FridayAgent` reasoning loop; lacks goal progress tracking, timeouts, and structured state reporting. |
| **Computer Control Safety** | **COMPLETE & SOLID**: `ComputerActionProposal` + `ComputerActionExecutor` enforce strict hard-blocks and mandatory confirmation. | Must ensure new autonomous planning layers never bypass `Proposal != Execution` or auto-authorize sensitive actions. |
| **Provider Independence** | **COMPLETE**: Clean `BaseLLMProvider` and `MockLLMProvider` abstractions. | Must ensure all Phase 7 planning and state machine tests remain 100% testable offline with `MockLLMProvider`. |

---

## 3. Recommended Phase 7 Subphases & Dependency Order

```mermaid
flowchart TD
    subgraph PHASE_7 ["Phase 7 Implementation Roadmap"]
        P7_1["7.1 Reasoning State Foundation & Task State Machine"]
        P7_2["7.2 Structured Task Planning & Goal Decomposition"]
        P7_3["7.3 Multi-Step Task Execution Engine & Progress Tracker"]
        P7_4["7.4 Verification, Assertions & Self-Correction Loops"]
        P7_5["7.5 Active Working Task Memory & Context Isolation"]
        P7_6["7.6 Autonomous Failure Recovery & Strategy Adaptation"]
        P7_7["7.7 Interruption, Checkpointing & Resumption"]
        P7_8["7.8 Advanced Tool Orchestration & Multi-Tool Planning"]
        P7_9["7.9 Long-Running Task Management & Background Progress"]
        P7_10["7.10 Autonomous Capability Safety & Authorization Gate"]
        P7_11["7.11 Full Phase 7 Multimodal Autonomous Acceptance Gate"]
    end

    P7_1 --> P7_2
    P7_2 --> P7_3
    P7_3 --> P7_4
    P7_3 --> P7_5
    P7_4 --> P7_6
    P7_3 --> P7_7
    P7_2 --> P7_8
    P7_7 --> P7_9
    P7_4 & P7_6 & P7_8 & P7_9 --> P7_10
    P7_10 --> P7_11
```

### Detailed Subphase Breakdown

#### Phase 7.1 — Reasoning State Foundation & Task State Machine [COMPLETE]
- Implement `TaskState` enumeration: `NOT_STARTED`, `UNDERSTANDING`, `PLANNING`, `EXECUTING`, `VERIFYING`, `COMPLETED`, `FAILED`.
- Implement `ReasoningStateMachine` with explicit valid state transitions, audit trail logging, and state change listeners.
- Integrated seamlessly into `FridayAgent` (`current_state`, `state_machine`, `get_status()`, and lifecycle logging in `process_message`).
- **Files Created/Modified**: `src/friday/agent/state.py`, `src/friday/agent/agent.py`, `src/friday/agent/__init__.py`, `tests/test_reasoning_state.py` (10/10 tests passing).

#### Phase 7.2 — Structured Task Planning & Goal Decomposition [COMPLETE]
- Implement `TaskPlan`, `PlanStep`, `StepStatus`, `PlanValidationError`, and `GoalDecomposer`.
- Define step dependencies, expected inputs/outputs, safety requirements, and pre-execution validation.
- Prevent arbitrary shell or destructive generation in plans via strict schema & safety elevation validation.
- Integrated into `FridayAgent` (`create_plan`, `current_plan`, and active plan status tracking in `get_status()`).
- **Files Created/Modified**: `src/friday/agent/planner.py`, `src/friday/agent/agent.py`, `src/friday/agent/__init__.py`, `tests/test_task_planner.py` (10/10 tests passing).

#### Phase 7.3 — Multi-Step Task Execution Engine & Progress Tracker [COMPLETE]
- Implement `TaskExecutionEngine`, `ExecutionProgress`, `StepExecutionResult`, and `TaskExecutionResult`.
- Execute `PlanStep` items strictly in dependency order with failure cascading (failed prerequisites cause dependent steps to be marked SKIPPED).
- Track step progress, elapsed time, step results, and realtime progress callbacks.
- Enforce strict per-step safety checks and authorization boundaries with bounded execution limits.
- Integrated into `FridayAgent` (`execute_plan` method with progress tracking).
- **Files Created/Modified**: `src/friday/agent/executor.py`, `src/friday/agent/agent.py`, `src/friday/agent/__init__.py`, `tests/test_multi_step_execution.py` (8/8 tests passing).

#### Phase 7.4 — Verification, Assertions & Self-Correction Loops [COMPLETE]
- Implement post-step and task-level formal verification (`StepVerifier`, `VerificationResult`, and `VerificationStatus`).
- Support explicit assertion criteria (`contains:<substr>`, `regex:<pattern>`, and semantic output heuristics).
- Enable bounded self-correction loops (`SelfCorrectionPolicy`): diagnose failure, generate adjusted steps, retry within strict budget (max 3), and re-verify without infinite loops.
- Integrated into `TaskExecutionEngine` with preservation of `BaseAuthorizer` gating and Proposal != Execution.
- **Files Created/Modified**: `src/friday/agent/verification.py`, `src/friday/agent/executor.py`, `src/friday/agent/__init__.py`, `tests/test_verification_and_correction.py` (6/6 tests passing).

#### Phase 7.5 — Active Working Task Memory & Context Isolation
- Implement `ActiveTaskContext` to hold temporary variables, intermediate tool results, and step outputs during task execution.
- Only commit high-level task summaries and final verified results to long-term SQLite conversation memory upon completion.
- Prevents context overflow and token bloat in multi-step dialogues.
- **Target Files**: `src/friday/memory/task_context.py`, `tests/test_task_memory.py`.

#### Phase 7.6 — Autonomous Failure Recovery & Strategy Adaptation
- Implement structured failure analysis (`FailureAnalyzer`): classifies failures into network, quota, tool syntax, missing dependency, or unexpected environment state.
- Provide automatic alternative path exploration (e.g. fallback tools or alternative query formulations) without infinite retry loops.
- **Target Files**: `src/friday/agent/recovery.py`, `tests/test_failure_recovery.py`.

#### Phase 7.7 — Interruption, Checkpointing & Resumption
- Add ACID SQLite task checkpointing (`TaskCheckpointStore`).
- Allow user or voice barge-in to pause an active execution plan, switch context, and subsequently resume the paused task from the last successful step checkpoint.
- **Target Files**: `src/friday/agent/checkpoint.py`, `src/friday/tasks/sqlite_store.py`, `tests/test_task_resumption.py`.

#### Phase 7.8 — Advanced Tool Orchestration & Multi-Tool Planning
- Enhance tool selection with dependency chaining and parameter inference.
- Support multi-tool workflows combining perception (`get_screen_snapshot`), data extraction, calculation, and safe proposal formulation in unified plans.
- **Target Files**: `src/friday/tools/planner.py`, `tests/test_advanced_tool_planning.py`.

#### Phase 7.9 — Long-Running Task Management & Background Progress
- Integrate background execution with the CLI and Voice session notifications.
- Enable non-blocking long-running goals with proactive milestone notifications and progress telemetry.
- **Target Files**: `src/friday/tasks/manager.py`, `tests/test_long_running_tasks.py`.

#### Phase 7.10 — Autonomous Capability Safety & Authorization Gate
- Conduct comprehensive 10-vector security audit for autonomous multi-step execution.
- Verify that complex plans cannot conceal malicious shell commands, password extraction, or unconfirmed OS modifications.
- Enforce that `Proposal != Execution` holds across all multi-step plan stages.
- **Target Files**: `tests/test_security_audit_phase7.py`.

#### Phase 7.11 — Full Phase 7 Multimodal Autonomous Acceptance Gate
- Create comprehensive end-to-end acceptance gate (`tests/test_phase7_acceptance_gate.py`).
- Validate complete flow: Complex Goal → Decomposition → Step Execution → Perception → Verification → Recovery → Checkpoint Resumption → Final Verified Report.
- Synchronize diary, update documentation, and perform final release gate.

---

## 4. Security & Safety Strategy

1. **Proposal != Execution**: Even when FRIDAY autonomously generates multi-step plans involving computer actions, individual action steps remain proposals until explicitly confirmed by the user.
2. **Hard-Blocked Intentions**: Password entry, API key handling, financial transactions, partition formatting, and raw shell execution remain strictly prohibited in both single-turn and multi-step plans.
3. **Budgeted Iterations & Retries**: Every plan enforces strict timeouts (default 120s), max step iterations (default 10), and max self-correction retries (default 3) to prevent runaway execution or credit consumption.
4. **Untrusted Data Boundary**: Visual observations and external web/file contents remain tagged as `UNTRUSTED DATA` throughout all planning and reasoning stages.

---

## 5. Performance, Quota & Provider Independence Strategy

1. **Local-First Reasoning**: Step validation, state transitions, syntax checks, and hash deduplication run purely locally in Python without consuming cloud API tokens.
2. **Context Compression**: Intermediate step logs remain in `ActiveTaskContext` and are summarized before injection into LLM prompts.
3. **Provider Abstraction**: All Phase 7 components interact exclusively with `BaseLLMProvider` and `BaseVisionProvider`. 100% of unit and integration tests run offline with `MockLLMProvider`.
4. **IBM Quantum Status**: Reserved for a future specialized compute phase (Phase 8+). Zero quantum dependencies or placeholder code will be introduced in Phase 7.

---

## 6. Stop Conditions & Execution Protocol

- **Phase 7 Implementation has NOT started**.
- Each subphase (7.1 through 7.11) will be executed sequentially: `inspect → implement → test → verify → document → continue`.
- Every subphase will be accompanied by deterministic unit tests and updated daily diary entries.
