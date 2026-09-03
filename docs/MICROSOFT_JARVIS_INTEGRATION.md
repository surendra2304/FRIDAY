# FRIDAY — Microsoft JARVIS / HuggingGPT Architecture & Integration Guide

## 1. Architectural Overview

FRIDAY integrates the foundational autonomous coordination paradigms introduced by **Microsoft JARVIS (HuggingGPT)** directly into its native architecture. In this design, FRIDAY functions as the central autonomous controller coordinating language models, multimodal vision systems, local Windows automation drivers, and specialized agents.

```
                          ┌──────────────────────────┐
                          │       USER REQUEST       │
                          │   (Voice, Desktop, API)  │
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │   FRIDAY UNDERSTANDING   │
                          │   (Goal & Modalities)    │
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  DYNAMIC TASK PLANNER    │
                          │ (Decompose into Subtasks)│
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │       TASK GRAPH         │
                          │ (Typed DAG Dependencies) │
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │   MODEL & TOOL ROUTER    │
                          │  (Executor & Model Map)  │
                          └─────────────┬────────────┘
                                        │
                 ┌──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
        ┌────────────────┐     ┌────────────────┐     ┌────────────────┐
        │  TOOL EXECUTOR │     │ VISION / MULTI │     │ AGENT / LLM    │
        │  (OS/Apps/Web) │     │ (OCR/Gemini)   │     │ (Coding/Reason)│
        └────────┬───────┘     └────────┬───────┘     └────────┬───────┘
                 │                      │                      │
                 └──────────────────────┼──────────────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │   DYNAMIC RE-PLANNER     │
                          │  (Failure Recovery/DAG)  │
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │    RESULT SYNTHESIZER    │
                          │(Coherent Multimodal Merge)│
                          └─────────────┬────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │     FRIDAY RESPONSE      │
                          │  (Speak / Transcribe/UI) │
                          └──────────────────────────┘
```

---

## 2. Core Subsystems

### 2.1 Typed Task Graph Engine (`friday.planning.types`)
A Directed Acyclic Graph (DAG) system representing complex user requests:
- **`TaskDataType`**: Strict typing across modalities (`TEXT`, `IMAGE`, `VIDEO`, `AUDIO`, `FILE`, `URL`, `JSON`, `STRUCTURED_DATA`, `SCREENSHOT`, `UI_STATE`, `TOOL_RESULT`, `MODEL_RESULT`, `ANY`).
- **`TaskStatus`**: Full lifecycle states (`PENDING`, `PLANNING`, `READY`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED`, `RETRYING`, `CANCELLED`, `SKIPPED`).
- **Topological Wave Execution**: Calculates parallel execution batches via `TaskGraph.compute_waves()`, running independent tasks concurrently.
- **Dynamic Variable Interpolation**: Injects results from upstream prerequisite tasks using `<TASK_ID>` or `{{task_id.key}}` template tokens.
- **Cycle Detection**: Guarantees acyclicity via Kahn's algorithm before dispatching workers.

### 2.2 Model & Executor Catalog (`friday.planning.executors`)
Abstracts tools, models, vision engines, and agents behind a unified, typed `BaseExecutor` interface:
- **`ToolExecutor`**: Automatically wraps and exposes all 50+ tools from FRIDAY's `ToolRegistry`.
- **`VisionExecutor`**: Fast local Tesseract/window OCR with multimodal cloud fallback for complex visual comprehension.
- **`LLMExecutor`**: Text reasoning, planning analysis, code generation, and structured translation.
- **`SpecialistAgentExecutor`**: Bridges FRIDAY's specialist agents (`DeveloperAgent`, `ResearchAgent`, `SelfDevAgent`).
- **`EasyTool Principles`**: Generates compact, token-efficient semantic summaries for LLM prompt injection without wasteful context bloat.

### 2.3 Model & Tool Router (`friday.planning.router`)
Evaluates candidate executors using an explainable, multi-factor scoring matrix:
1. **Capability Alignment (0–40 pts)**: Exact name match (+40), capability tag match (+35), or semantic keyword match.
2. **Modality & Type Compatibility (0–25 pts)**: Verifies input and output data type match.
3. **Locality Preference (0–15 pts)**: Prioritizes local, deterministic Windows execution.
4. **Cost Efficiency (0–10 pts)**: Prefers free/local models before commercial cloud providers.
5. **Latency Profile (0–10 pts)**: Prefers fast executors for interactive responsiveness.
6. **Safety Escalation**: Automatically promotes task `safety_level` and flags `requires_confirmation = True` if an executor is `SENSITIVE` or `DANGEROUS`.

### 2.4 Async Parallel Scheduler (`friday.planning.scheduler`)
Executes `TaskGraph` waves concurrently:
- Respects `max_concurrency` (default: 5 concurrent workers) to avoid resource exhaustion.
- Enforces `BaseAuthorizer` security gating before dispatching sensitive actions.
- Bounded retries with exponential backoff on transient errors (HTTP 429, 503, connection timeouts).
- Publishes real-time telemetry events (`PLAN_CREATED`, `TASK_STARTED`, `TASK_COMPLETED`, `TASK_FAILED`, etc.) via `TaskEventBus`.

### 2.5 Dynamic Re-planner & Fault Recovery (`friday.planning.replanner`)
Ensures resilient autonomy when steps fail:
- **Tier 1 (Retry)**: Instant retry with backoff for transient glitches.
- **Tier 2 (Fallback Executor)**: Automatically executes designated secondary executors (e.g. cloud vision fails -> fallback to local OCR).
- **Tier 3 (Subgraph Replacement)**: Uses the LLM replanner to replace failed steps with alternative sub-graphs and reroute downstream dependencies.
- **Tier 4 (Graceful Skipping)**: Skips non-critical auxiliary tasks while allowing unaffected branches to succeed.
- **Security Invariant**: Dynamic replanning NEVER bypasses `BaseAuthorizer` confirmation gates.

### 2.6 Result Synthesizer (`friday.planning.synthesizer`)
Consolidates all completed task outputs:
- Reconciles differences between complementary models and modalities.
- Strips internal scratchpad thoughts, tool traces, and JSON envelopes.
- Synthesizes a natural, concise, human-friendly response tailored for both voice speech and visual desktop chat.

---

## 3. Desktop HUD & UI Integration

The desktop companion overlay (`src/friday/desktop/`) subscribes to the `global_task_event_bus`:
- **Live Task Progress Checklist**: Displays interactive checklist items with status indicators:
  - `✓` (Bright Green): Completed task
  - `●` (Electric Amber): Running task
  - `○` (Muted Gray): Pending task
  - `✕` (Crimson): Failed task
- **Status Readout**: Updates the 9-state holographic orb between `PLANNING`, `EXECUTING: [Task ID]`, and `IDLE`.

---

## 4. Configuration Reference

Add these variables to your `.env` file to customize planning behavior:

| Variable | Type | Default | Description |
|---|---|---|---|
| `FRIDAY_PLANNER_ENABLED` | bool | `true` | Enable Microsoft JARVIS task graph planning |
| `FRIDAY_PLANNER_MAX_CONCURRENT_TASKS` | int | `5` | Maximum parallel subtasks in execution waves |
| `FRIDAY_PLANNER_TASK_TIMEOUT_SECONDS` | float | `60.0` | Timeout per subtask in seconds |
| `FRIDAY_PLANNER_MAX_RETRIES` | int | `3` | Maximum retry attempts per subtask on transient failures |
| `FRIDAY_PLANNER_MODEL` | str | `null` | Dedicated model override for task decomposition |

---

## 5. Programmatic API Example

```python
from friday.agent.agent import FridayAgent

# Initialize FRIDAY agent
agent = FridayAgent()

# Execute a complex multi-step request with Microsoft JARVIS task graph orchestration
response = agent.execute_complex_task("Compare Tokyo weather and Paris weather")

print("FRIDAY Response:", response.content)
print("Execution Telemetry:", response.metadata)
```

---

## 6. TaskBench Evaluation Benchmark Suite

Inspired by Microsoft's TaskBench research, FRIDAY includes an automated benchmark suite in `tests/benchmark/test_taskbench.py` evaluating:
1. Single-tool tasks
2. Multi-tool sequential workflows
3. Parallel dependency workflows
4. Multimodal vision workflows
5. Computer-control workflows
6. Dynamic failure recovery workflows
7. Aggregate metric evaluation

### Running the Benchmark Suite:
```powershell
pytest tests/benchmark/test_taskbench.py -v
```
All categories maintain $\ge 90\%$ accuracy thresholds and sub-second execution latencies in local environments.
