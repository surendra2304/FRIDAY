# FRIDAY Project Context

**PRIMARY HANDOFF DOCUMENT**

## A. WHAT FRIDAY IS
FRIDAY (Fully Responsive Intelligent Digital Assistant for You) is an advanced, multi-modal, local-first AI assistant for Windows. The intended end state is a highly capable autonomous agent with secure computer-control, reasoning, long-term memory, voice (Gemini Live), and vision (Gemini Vision) capabilities, operating independently while maintaining robust security and provider agnosticism.

## B. CURRENT ARCHITECTURE
FRIDAY operates on a core orchestration loop (`FridayAgent`) governed by a `ReasoningStateMachine`. User input (text/voice) flows through cognitive understanding (clarification loops), capability routing, and intent detection (deterministic spatial vs semantic UI). Action proposals are generated and explicitly authorized before execution. Memory is persisted in a local SQLite database with embeddings. API providers (like Google Gemini) are abstracted behind strict interfaces with credential failover and circuit breakers.

## C. DIRECTORY MAP
- `src/friday/`: Core source code.
  - `agent/`: Orchestration loop, state machine, task planning, and verification.
  - `vision/`: Screen capture, Vision provider interface, `DeterministicActionDetector`, `IntentDetector`, and native Windows input driver.
  - `ui_automation/`: Windows UI Automation provider (pywinauto).
  - `llm/` & `voice/`: Provider abstractions for Text and Gemini Live voice.
  - `memory/`: SQLite persistence, episodic memory, task context.
  - `core/`: Logging, configuration (`pyproject.toml`, `Settings`), security (`Authorizer`).
- `tests/`: Extensive test suite (unit, integration, simulation, security).
- `docs/`: Architecture reports, validation matrices, phase reports, and this handoff document.
- `diary/` / `FRIDAY_DIARY.md`: Chronological log of major architectural changes and fixes.
- `scripts/`: Diagnostic and utility scripts.

## D. CURRENT MODELS
- **Text Model:** Gemini 3.7 Flash (default via `gemini_provider`)
- **Vision Model:** Gemini Vision (used as fallback for non-deterministic screen understanding)
- **Voice Model:** Gemini Live (Voice Activity Detection and interrupt handling built-in)
- **Thinking Level:** Variable, configurable via `Settings`
- **Embedding Model:** Local/SQLite FTS used for semantic task retrieval
- **Credential Architecture:** Hardened failover pool supporting primary and multiple fallback API keys, gated by a `RequestAccountant` circuit breaker.

## E. EXECUTION FLOW
1. Input received (Voice/Text).
2. Cognitive Phase evaluates understanding/ambiguity (may loop for clarification).
3. Capability Router / Intent Detectors check for Fast-Paths (Geometric or Semantic UI).
4. If no Fast-Path, LLM formulates a `TaskPlan`.
5. Action Proposal generated (e.g. `ComputerActionProposal`).
6. Security Authorizer validates proposal against risk levels.
7. Execution Engine interacts with Windows (UI Automation or Native Driver).
8. Verification Phase captures screen/state to confirm success.
9. Agent responds.

## F. COMPUTER-CONTROL FLOW
- **Deterministic Geometric Action:** Detected by `DeterministicActionDetector` (regex). Bypasses LLM/Vision. Uses `WindowsNativeInputDriver` to directly execute center/corner/coordinate clicks and scrolling.
- **Semantic UI Action:** Detected by `IntentDetector`. Routes to `WindowsUIAutomationProvider` to find and click element by name/type. Bypasses Vision/LLM if confidence >= 0.90.
- **Vision Fallback:** If elements aren't found or intent is complex, `ScreenSnapshotTool` captures the screen and Gemini Vision infers coordinates.
- **Execution & Verification:** All physical executions pass through the sandbox/authorization layer. Verification follows execution.

## G. MEMORY ARCHITECTURE
- **SQLite Memory:** Persistent message storage.
- **Episodic / Task Memory:** Active context isolation (`ActiveTaskContext`).
- **Checkpoints:** State machine checkpoints for pause/resume of long-running tasks.

## H. SECURITY ARCHITECTURE
- **Authorization Capability System:** Strict `Authorizer` requiring human approval for high-risk actions.
- **Trust Levels:** Differentiates trusted user commands from untrusted web content.
- **Hard-Blocked Actions:** Destructive OS commands are explicitly denied.
- **Sanitization:** Secrets are scrubbed from logs and memory.

## I. PROVIDER-INDEPENDENCE
FRIDAY defines agnostic interfaces (`BaseLLMProvider`, `BaseWindowsInputDriver`, `UIAutomationProvider`). Gemini implementations exist, but the core logic (routing, state machine, memory) is entirely provider-independent.

## J. TEST ARCHITECTURE
- **Unit/Integration/Simulation:** Run locally via `pytest` without API keys or physical hardware.
- **Hardware/Live Tests:** Opt-in explicitly (`pytest -m live`, `pytest -m hardware`) for real API calls and physical devices.
- **Security Tests:** Validates secret scrubbing and authorization blocks.

## K. CURRENT VERIFIED STATE
- **Deterministic computer control:** REAL_PASS
- **Semantic UI routing:** REAL_PASS
- **Circuit breaker / failover:** REAL_PASS
- **Vision fallback:** SOFTWARE_VERIFIED
- **Voice/Live integration:** SOFTWARE_VERIFIED

## L. KNOWN LIMITATIONS
- UI Automation requires Windows (`pywinauto`).
- Vision API is subject to rate limits (mitigated by circuit breaker).
- Multi-monitor absolute coordinates may require scaling adjustments on non-standard DPIs.

## M. KNOWN BUGS
- See `FRIDAY_KNOWN_ISSUES.md`.

## N. RECENT FIX HISTORY
- **Deterministic Action Fast-Path (August 21, 2026):** Routed geometric actions away from Gemini Vision to prevent infinite API retry loops.
- **Circuit Breaker Refactor:** Prevented credential exhaustion loops when Vision APIs fail.
- **Semantic UI-Action Routing:** Added `WindowsUIAutomationProvider` and `IntentDetector` to bypass Vision for obvious UI clicks.

## O. HOW TO RUN
- **Start FRIDAY:** `friday` or `python -m friday.cli.main`
- **Unit Tests:** `pytest -m "not live and not hardware" -q`
- **Live API Tests:** `pytest -m live`
- **Hardware Tests:** `pytest -m hardware`
- **Security Tests:** `pytest -m security`

## P. ENVIRONMENT REQUIREMENTS
- **OS:** Windows 10/11 (required for Native Input and UI Automation)
- **Python:** >= 3.10
- **Dependencies:** `google-genai`, `pywinauto`, `sounddevice`, `pydantic`, `httpx`
- **Credentials:** Gemini API key required for full LLM/Vision functionality (set in `.env`).

## Q. IMPORTANT DEVELOPMENT RULES
- **NEVER commit secrets** (including `.env`).
- **Preserve Proposal != Execution:** Action proposals must be explicitly authorized before execution.
- **Don't claim mock PASS as real PASS:** Be truthful about validation status.
- **Maintain provider independence:** Keep vendor-specific code isolated.
- **No IBM Quantum:** Do not implement IBM Quantum unless explicitly planned.
