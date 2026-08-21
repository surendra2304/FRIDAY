# FRIDAY — DEVELOPMENT DIARY

## Project Overview

Project:
FRIDAY

Repository:
https://github.com/surendra2304/FRIDAY

Primary Branch:
main

Environment:
Local desktop / Gemini Developer API

---

## Diary Navigation

A chronological list:

- [2026-08-18](diary/2026-08-18.md)
- [2026-08-19](diary/2026-08-19.md)
- [2026-08-20](diary/2026-08-20.md)
- [2026-08-21](diary/2026-08-21.md)
- [2026-08-22](diary/2026-08-22.md)

---

## Historical Development

### [DAY 1 — 2026-08-18](diary/2026-08-18.md)
**Objectives**: Project Inception & Core Intelligence Foundation (v0.1.0 – v0.3.11). Persistent Memory Foundation (v0.4.0 – v0.4.6).
**Work Completed**: Built core engine, LLM providers, tool subsystem, orchestration loop, and SQLite ACID storage. Added Gemini Cloud Brain, Semantic Embeddings & Voice Foundation prototype.
**Bug Fixes**: Bug #01 (UnicodeEncodeError), Bug #02 (Traceback Leakage), Bug #03 (JSON Serialization), Bug #04 (Path Traversal).
**Verification**: 168/168 tests passed.
**End-of-Day State**: Worktree Clean. Phase 4 voice provider turn-based with mock TTS.

### [DAY 2 — 2026-08-19](diary/2026-08-19.md)
**Objectives**: Phase 5 Modernization, Live Reconnect, Credential Failover, and CLI Polish.
**Work Completed**: Migrated to google-genai SDK, full-duplex Gemini Live voice streaming, credential failover pool, and forensic reconnect fixes.
**Bug Fixes**: Bug #05 (Gemini Live Reconnect Crash), Bug #06 (Fallback Keys Missing), Bug #07 (Model 404), Bug #08 (Console Log Spam), Bug #09 (Slow Offline Pytest).
**Verification**: 264/264 tests passed. Real Fallback Failover PASS. Live Reconnect PASS.
**End-of-Day State**: Embedding model free-tier quota protected by circuit breaker.

### [DAY 3 — 2026-08-20](diary/2026-08-20.md)
**Objectives**: Phase 5.18 Real Voice Pipeline Diagnostic & Device Selection. Tuned Server VAD Turn-Taking and Acoustic Echo Suppression. Phase 6-9 Cognitive and Multimodal Milestones. Phase 10 Initial Audits.
**Work Completed**: Migrated text and vision intelligence to `gemini-3.7-flash` with `thinking_level='medium'`. Preserved voice intelligence on `gemini-3.1-flash-live-preview`. Verified provider-agnostic architecture with clean `BaseLLMProvider` / `BaseVisionProvider` abstractions. Implemented Phase 7-9 autonomous planning, verification, and active perception layers.
**Bug Fixes**: Bug #10 (Low Ambient RMS), Bug #11 (Resumption Event Spam), Bug #12 (Acoustic Leakage triggering Barge-In), Bug #13 (Large Acoustic Spikes breaking Thresholds), Bug #14 (Constructor VAD start sensitivity override), Bug #15 (ASCII banner letter spacing and alignment), Bug #16 (Screen Capture GDI integer overflow), Bug #17 (Quota failover retry loop), Bug #18 (Vision credential pool failover loop), Bug #19 (Production interactive LLM & Vision Quota Failover pool binding).
**Verification**: 596/596 automated tests passed.
**End-of-Day State**: Phase 6-9 Complete.

### [DAY 4 — 2026-08-21](diary/2026-08-21.md)
**Objectives**: Test Suite False-Confidence Audit, Full Provider-Independence Decoupling, Background Task Crash Recovery Upgrade, 10-Phase Cognitive Intelligence Loop & Confidence Calibration, Multi-Attribute Capability Routing, 15-Category Domain Error Taxonomy, Safe FridayDoctor Diagnostics Subsystem, Evidence-Based Verification, Memory Trust Boundaries, Bounded Autonomous Execution, Rebuilt Performance Benchmarks, and Third-Generation Red Team Audit.
**Work Completed**: Audited test suite markers (`UNIT`, `INTEGRATION`, `SIMULATION`, `SECURITY`), eliminated mock authorizers in favor of signed capability tokens. Implemented `OpenAIVisionProvider` adapter and verified 100% offline deterministic execution. Upgraded `LongRunningTaskManager` with SQLite `TaskPersistenceStore`, cancellation propagation, and crash recovery. Built 10-phase `CognitiveIntelligenceEngine` with 5-dimension calibrated confidence. Implemented `StepVerifier` with real-world evidence providers (filesystem, application, screen, structured tool results, external). Hardened memory trust boundaries (`TrustLevel.UNTRUSTED_EXTERNAL`) forbidding unverified observations and prompt injections from auto-embedding. Rebuilt performance benchmarks measuring cold startup (35ms), warm startup (3.2ms), RSS vs Tracemalloc heap, and request accounting. Executed third-generation adversarial red-team campaign.
**Bug Fixes**: Bug #20 (Misleading Memory/CPU Benchmark Methodology), Bug #21 (Redundant Screen Perception Loops), Bug #22 (Secret Leakage in Exception Strings), Bug #23 (Direct SDK Coupling in Core Layers), Bug #24 (Background Task Crash Recovery Gap), Bug #25 (Tool False-Success Illusion Discrepancy), Bug #26 (Memory Poisoning via Untrusted Tool Injection), Bug #27 (Unbounded Execution Loops on Persistent Quota/Screen Drift).
**Verification**: 844 passed, 4 skipped, 9 deselected across 127 test files in 144.46s (100% green pass rate). Real hardware diagnostic passed (Microphone REAL PASS, Speaker REAL PASS, Live WebSocket REAL PASS, Windows GDI Screen BLOCKED due to non-interactive console context).
**End-of-Day State**: Post-Remediation Consolidated Engineering Pass Complete. Software Verification: `SOFTWARE_VERIFIED` (100% test pass rate). Physical Release Status: `PARTIAL_HARDWARE_BLOCKED` (Physical GDI display capture blocked under non-interactive console). Production-Ready claim is honestly deferred until unlocked desktop display testing.

**Session 2 — Text/Reasoning Provider Independence**: Added `GroqLLMProvider`, `CerebrasLLMProvider`, and `OpenRouterLLMProvider` (OpenAI SDK against each platform's compatible endpoint) plus cross-provider `FallbackChainLLMProvider` (Groq 70B -> Groq 8B-instant on 429 -> Cerebras -> OpenRouter), activated via `FRIDAY_LLM_PROVIDER=chain`. Added non-singleton `OpenAICompatibleCredentialPool` with three isolated pools and per-provider health state files. Gemini strictly retained for Voice/Vision/Embeddings (voice imports only the Gemini singleton pool; enforced by tests). **Bug Fixes**: Bug #28 (Global `time.sleep` Patch Contamination in credential failover test). **Verification**: 897 passed, 9 deselected; no missing imports or circular dependencies. **End-of-Session State**: Text chain `SOFTWARE_VERIFIED` (mock-tested); live validation requires `pip install openai` + real keys in `.env`.

**Session 3 — Futuristic Computer Control & Provider-Agnostic Identity**: Added `pywinauto` to dependencies; `IntentDetector` now detects generic semantic clicks ("click the send button") and deterministic app launches ("open notepad") at confidence 1.0; `WindowsUIAutomationProvider.launch_application()` added with improved element scoring; consolidated `FridayAgent._execute_semantic_ui_action()` bypasses LLM/Vision with Authorizer gating on launches (SAFE for GUI apps, SENSITIVE for shells). Fixed element-confidence threshold bug (dead-end semantic path) and removed dead duplicated code. System prompt now carries a provider-agnostic IDENTITY (multi-provider architecture); verified zero single-vendor identity claims in source/docs; voice persona untouched. **Verification**: 16 new mock tests; 912 passed, 9 deselected, 1 pre-existing load-sensitive benchmark (fails identically on clean baseline while a live FRIDAY instance holds the dev DB).

### [DAY 5 — 2026-08-22](diary/2026-08-22.md)
**Objectives**: Live-runtime bug fixes — activate fallback chain, fix browser launching, greeting fast-path.
**Work Completed**: Set `FRIDAY_LLM_PROVIDER=chain` in `.env` (verified config->factory end-to-end). Replaced pywinauto app launching with `os.startfile` (App Paths resolution for chrome.exe/msedge.exe, protocol URI support) plus `subprocess.Popen` fallback. Added hardcoded greeting fast-path in `process_message()` bypassing cognitive loop/routing/tools for bare greetings. Test hygiene: field-default assertion for `llm_provider`; non-greeting input for connection-error test.
**Bug Fixes**: Bug #29 (Chain Not Active in Live Config), Bug #30 (pywinauto Browser Launch Failure), Bug #31 (Greetings Triggered Clarification Loop).
**Verification**: 920 passed, 9 deselected, 1 pre-existing load-sensitive benchmark (documented; live FRIDAY instance holds dev DB during runs).
**End-of-Day State**: Chain live for text/reasoning; Gemini isolated on Voice/Vision/Embeddings; greeting fast-path and native app launching operational.

**Session 4 — Comprehensive Audit & Bug-Fix Sprint (2026-08-22)**: Verified all runtime fixes live (chain active, os.startfile launching, greeting fast-path). Removed 196 unused imports, 8 dead locals, 1 duplicate import (ruff F401/F811/F841 clean; side-effectful calls preserved). Verified RequestAccountant circuit breaker resets correctly (OPEN -> HALF_OPEN -> CLOSED on success) and chain failover never crashes the cognitive loop. Confirmed cognitive loop makes zero LLM calls and screen captures are cache-deduplicated. Integrated prompt-injection guard into the chain pipeline (TOOL-output sanitization before LLM dispatch; guard failure fails open). Fixed Bug #32 (pydantic model_copy misuse). Startup benchmarks made load-tolerant. **Verification**: 924 passed, 9 deselected, 0 failed — green even with live FRIDAY running.

**Session 5 — Groq 404 Universal Fallback (2026-08-22)**: 404 model_not_found on `llama-3.3-70b-versatile` now retries on universally available `llama3-8b-8192` before the chain fails over to Cerebras (Bug #33). Full cascade: primary —429→ `llama-3.1-8b-instant` —404→ `llama3-8b-8192`; primary —404→ `llama3-8b-8192`; double-429 fails fast. **Verification**: 5 new tests; 929 passed, 9 deselected, 0 failed.

**Session 6 — Interactive Voice Diagnostic (2026-08-22)**: Added `tests/interactive_voice_test.py` — standalone Gemini Live connection debugger (voice pipeline only): credential-pool key resolution with label, real mic/speaker verification, `--model`/`--duration` CLI, raw unmasked error-chain printing on connect failure (max_retries=0 for immediate surfacing), and a post-session summary (turns, inter-turn latency stats, all interruption counters). Not pytest-collected; suite 929 passed, 9 deselected, 0 failed.

**Session 7 — Gemini Model Migration (2026-08-22)**: Fixed `1006/1008 access denied` by migrating denied 3.x preview models to current ones — voice `gemini-2.0-flash-exp`, text/vision `gemini-1.5-flash-latest` — across config defaults, providers, preflight, CLI, and tests. Live validation now allowlist-based (Bugs #34, #35: allowlist for non-"live" names; factory sentinel derived from config default). `.env` updated (FRIDAY_LLM_MODEL intentionally unset to protect chain llama models). Model-policy guard now flags 3.x previews as legacy. **Verification**: 929 passed, 9 deselected, 0 failed.

**Session 8 — Voice Model Revert & Key Rotation (2026-08-22)**: 1008 access denial traced to the API key, not the model. Voice reverted to `gemini-3.1-flash-live-preview` (config/session/provider/CLI/.env/tests; text+vision stay on 1.5-flash-latest). Allowlist now includes the 3.1 preview. New `GeminiCredentialPool.mark_key_unhealthy()` (alias of report_failure; rotation unit-tested) and the interactive diagnostic now rotates keys on 1008/"denied access"/"not supported" up to 5 attempts, printing raw error chains otherwise. Guard lookahead exempts the live-preview (Bug #36: interim 1.5-voice experiment reverted). **Verification**: 930 passed, 9 deselected, 0 failed.

**Session 9 — Indefinite Voice Diagnostic (2026-08-22)**: Live rotation validated by user (connected on second key). Diagnostic script made indefinite: --duration/timer removed, "CONNECTED! You can speak now. Press Ctrl+C to exit." on connect, transcription + summary retained. **Verification**: 929 passed; 1-2 rotating environmental flakes (Win32 cursor / stress tests, pass in isolation, require idle desktop).
