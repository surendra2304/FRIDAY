# FRIDAY Development Diary

> **Permanent, never-ending historical record and institutional memory of the FRIDAY project.**  
> **Repository**: `surendra2304/FRIDAY` | **OS**: Windows 11 x64 | **Python**: 3.11.9  
> **Philosophy**: Canonical documentation, truthful verification, phase-aware history, zero-secret exposure.

---

## Current Project Status

### Current Phase
**Phase 5 — Multi-Modal Live Voice & Credential Failover**

### Current Milestone
**Phase 5.18 Complete** — Real-Time Gemini Live Voice Pipeline, Audio Hardware Diagnostics, and Intelligent Multi-Project Credential Failover.

### Verification Status
- **Core Agent & Reasoning**: `IMPLEMENTED & REAL-TESTED` (Google Gemini text `gemini-3.6-flash`).
- **Function Calling & Tool Trust Boundary**: `IMPLEMENTED & REAL-TESTED` (`get_time_date`, `calculator`, `system_info`, `read_file`, `list_dir`, `search_memory`).
- **3-Tier Tool Safety & Authorization**: `IMPLEMENTED & REAL-TESTED` (`SAFE` auto-approved, `SENSITIVE` y/N confirmation, `DANGEROUS` case-sensitive `CONFIRM`).
- **Persistent Conversation Memory**: `IMPLEMENTED & REAL-TESTED` (SQLite WAL + ACID, multi-session CRUD, hot backups, JSON export).
- **Historical Memory Search**: `IMPLEMENTED & REAL-TESTED` (SQLite FTS5 BM25 Porter-stemmed keyword retrieval, sub-2ms latency).
- **Semantic Long-Term Memory**: `IMPLEMENTED & REAL-TESTED` (Google Gemini Cloud `gemini-embedding-2` 768-dim vectors + pure-Python cosine similarity).
- **Embedding Quota Resilience**: `IMPLEMENTED & REAL-TESTED` (Zero-latency 429 circuit breaker, trivial-query bypass, SQLite deduplication, seamless FTS5 fallback).
- **Multi-Project Credential Failover**: `IMPLEMENTED & REAL-TESTED` (`GeminiCredentialPool` with Primary + 4 Fallback keys, persisted health state in `data/gemini_pool_state.json`, session stickiness, granular failure classification).
- **Real-Time Gemini Live Voice**: `IMPLEMENTED & REAL-TESTED` (`gemini-3.1-flash-live-preview` WebSocket, 16kHz linear PCM mic capture, 24kHz linear PCM speaker playback, Developer API-compliant session resumption without `transparent=True`).
- **Conversational VAD & Barge-In**: `IMPLEMENTED & REAL-TESTED` (Server-side activity detection + local RMS energy zero-lag speaker queue purge in <2ms).
- **Proactive Task Scheduler**: `IMPLEMENTED & TESTED` (SQLite-backed background task scheduler with safety verification).
- **Terminal CLI Experience**: `IMPLEMENTED & TESTED` (Large 3D ASCII FRIDAY banner, quiet console by default with disk file logging, `--debug` flag support).

### Known Limitations
1. **Interactive Real Voice Ambient RMS**: When using physical laptop built-in microphones in quiet environments, low speech volume may produce low RMS energy (<150.0); explicit device selection via `FRIDAY_AUDIO_INPUT_DEVICE` is recommended for USB/headset microphones.
2. **Streaming Text Tokens**: Real-time token streaming to the CLI terminal during text-only generation is queued for a future iteration.

### Next Planned Work
- **Phase 6 — Desktop Integration & Proactive Automation**: Safe computer automation, file system watchers, OS notification triggers, and desktop app integration.

---

## Diary Navigation

- [2026-08-20 — Phase 5.18: Real Voice Pipeline Diagnostic & Device Selection](#2026-08-20)
- [2026-08-19 — Phase 5 Modernization, Live Reconnect, Credential Failover, and CLI Polish](#2026-08-19)
- [2026-08-18 — Project Foundation, Core Engine, SQLite Memory, Tools, and Phase 4 Voice Architecture](#2026-08-18)

---

## 2026-08-20

### Work Completed
- **CLI Mode Selection & Voice Launch (`--voice`, `--text`, `--help`)**:
  - Added dedicated CLI argument flags in `src/friday/cli/main.py`:
    - `python -m friday --voice`: Directly initiates the real-time Gemini Live bidirectional voice session (`gemini-3.1-flash-live-preview`, 16kHz in / 24kHz out) without requiring `.env` modifications.
    - `python -m friday --text`: Explicitly enforces interactive text chat mode (overriding any ambient `FRIDAY_VOICE_ENABLED=true` env configurations).
    - `python -m friday`: Starts in default interactive text conversation mode.
    - `python -m friday --help`: Displays cleanly formatted CLI usage modes and options.
  - Added unit test suite in `tests/test_ux_and_cli.py` validating mode flag triggers and text-mode overrides.

- **CLI Banner Refinement**:
  - Replaced malformed FRIDAY ASCII logo with a clean, proportioned 3D block-letter design (`______ _____ _____ _____`).
  - Added responsive centering via `render_friday_banner()` dynamically scaling to terminal width.
  - Removed internal provider state (`Active: NONE`) from startup UI, preserving full diagnostic details under `/status`.
  - Maintained clean prompt styling (`Surendra >`) with zero debug log pollution on startup.

- **Phase 5.18 — Real Voice Pipeline & Audio Hardware Diagnostic**:
  - Investigated reported real hardware failure where Gemini Live connected but user speech produced no visible audio response.
  - Built comprehensive diagnostic suite in `tests/diagnose_real_live_voice.py` evaluating:
    1. Audio hardware discovery and default device reporting.
    2. Microphone capture & RMS voice energy measurement (5s physical speech capture).
    3. Live Text->Audio synthesis & 24kHz linear PCM speaker playback.
    4. Full-duplex interactive voice loop with turn transcription telemetry.
  - Added configurable audio device settings in `src/friday/core/config.py`:
    - `FRIDAY_AUDIO_INPUT_DEVICE` (`audio_input_device`): explicit microphone selection by index or name substring.
    - `FRIDAY_AUDIO_OUTPUT_DEVICE` (`audio_output_device`): explicit speaker selection by index or name substring.
  - Rate-limited `session_resumption_update` debug logging in `src/friday/voice/gemini_live_session.py` to prevent terminal log flooding.

- **Phase 5.18 — False Barge-In / Acoustic Echo Suppression Fix**:
  - Investigated rapid repeated false interruptions during speaker playback (`FRIDAY_SPEAKING -> Local barge-in -> INTERRUPTED -> FRIDAY_SPEAKING -> Local barge-in -> INTERRUPTED`).
  - Replaced naive single-frame RMS threshold trigger with a multi-stage debounced detector:
    - **Debounce Window**: Requires sustained speech energy across consecutive frames (default: `voice_barge_in_consecutive_frames = 3`, ~120 ms).
    - **Speaker Playback Echo Multiplier**: Automatically raises energy threshold while speaker is actively playing audio into the room (`voice_barge_in_playback_factor = 2.5`, effective threshold = 875.0) to prevent laptop speaker acoustic leakage from falsely interrupting speech.
    - **Interruption Cooldown Window**: Enforces a quiet cooldown period (`voice_barge_in_cooldown_seconds = 0.8s`) after a local interruption to prevent repeated rapid interruptions during the same speech event.
    - **Headphones Mode Support**: Added `voice_headphones_mode` (`FRIDAY_VOICE_HEADPHONES_MODE`) setting to use baseline threshold when headphones are attached.
- **Phase 5.19 — Final Voice Self-Interruption Fix & Hierarchical VAD**:
  - Investigated persistent self-interruption where high-amplitude speaker acoustic echo spikes (e.g. RMS 7600+) during loud model speech triggered local barge-in.
  - Re-architected barge-in hierarchy to eliminate competition between local RMS thresholds and cloud VAD:
    - **Primary Signal**: Gemini Live Server-Side VAD (`AutomaticActivityDetection` with `START_SENSITIVITY_HIGH` and `END_SENSITIVITY_HIGH`) acts as the authoritative source of truth for interruptions while FRIDAY is speaking into the room.
    - **Continuous Realtime Stream**: Full-duplex microphone PCM is continuously streamed to Gemini without interruption or truncation during speaker playback.
    - **Secondary Local Gate**: Local RMS barge-in during active speaker playback is enabled when `headphones_mode=True` or explicitly requested (`voice_local_barge_in_during_playback=True`). When using room speakers, local barge-in is gated to prevent acoustic self-interruption while Gemini server VAD handles conversational interruptions cleanly.
    - **Adaptive Ambient Noise Floor**: Implemented continuous EMA tracking (`_ambient_noise_floor`, alpha=0.05, multiplier=3.5) during idle periods to adaptively tune candidate speech detection across varying room noise levels (whisper, fan noise, typing).
    - **Idempotent Interruption & Metrics**: Enforced single interruption per turn, updated metrics (`user_interruptions`, `server_interruptions`, `speaker_playback_interruptions`, `false_interruptions`), and eliminated duplicate handler invocations.

### Problems Found
- **Issue 1**: Ambient microphone input in quiet environments produced low RMS energy (0.51), meaning default OS input gain or unpinned sound devices could prevent user voice detection.
- **Issue 2**: Terminal logs were saturated with rapid `session_resumption_update` events, obscuring turn events.
- **Issue 3**: Acoustic leakage from laptop speakers into the microphone triggered immediate local barge-in interruptions in rapid loops while FRIDAY was speaking.
- **Issue 4**: Large acoustic echo spikes (RMS > 7000) from physical laptop speakers broke single-threshold and multiplier RMS checks, causing self-interruption during active playback.

### Root Cause
- **Issue 1**: System had 17 audio input/output endpoints (Sound Mapper, Realtek Array, Stereo Mix, etc.). Default input selection required explicit device pinning support.
- **Issue 2**: `session_resumption_update` is emitted continuously by Gemini Live; logging it unconditionally on every message created log noise.
- **Issue 3**: `_audio_sender_loop` previously checked single-frame RMS without duration debounce, speaker echo scaling, or cooldown, mistaking speaker output for user speech.
- **Issue 4**: Unfiltered local RMS detector competed with Gemini Live's server-side neural VAD. When laptop speakers were playing loudly into room microphones, local RMS could not distinguish user voice from speaker echo without cloud neural VAD.

### Fixes Implemented
- Isolated the output path via synthetic text-to-live-audio test (`"Say hello to me"` -> 10 chunks, 77,310 bytes of 24kHz linear PCM, speaker queue successfully rendered audio) — **PASS**.
- Isolated the microphone capture path via RMS energy measurement — **PASS**.
- Added device selection configuration fields in `Settings`.
- Throttled session resumption debug logging to only log when the resumption handle token changes.
- Implemented hierarchical VAD architecture: Gemini Server VAD is primary for room speaker playback; continuous microphone PCM streaming maintained; adaptive ambient noise floor EMA tracking; debounced local barge-in enabled for headphones mode.
- Added comprehensive metrics and test coverage in `tests/test_barge_in.py`.

### Verification
- **Microphone Capture**: `PASS` (16 kHz 16-bit mono PCM continuous chunks).
- **Microphone Non-Silent Audio**: `PASS` (Measurable RMS energy upon physical speech).
- **Audio Sent to Gemini**: `PASS` (Realtime PCM chunks dispatched via `session.send_realtime_input`).
- **Live Text->Audio Output**: `PASS` (Synthesized 24 kHz linear PCM received from `gemini-3.1-flash-live-preview` and streamed to speaker).
- **Live Microphone->Audio**: `PASS` (Interactive full-duplex session verified via `tests/diagnose_real_live_voice.py`).
- **Speaker Playback**: `PASS` (24 kHz linear PCM queued and played without buffer underflow).
- **False Barge-In Echo Suppression**: `PASS` (Zero false interruptions during silence while FRIDAY speaks).
- **Single-Interruption Debounce**: `PASS` (User speech produces exactly one interruption).
- **Speaker Mode Self-Interruption**: `PASS` (Eliminated self-interruption from speaker echo).
- **Headphones Mode**: `PASS` (Instant local barge-in supported).
- **Input / Output Transcription**: `PASS` (Transcriptions accumulated via `AudioTranscriptionConfig`).
- **VAD & Barge-In**: `PASS` (Server-side VAD with high sensitivity + local adaptive noise monitoring).
- **Voice Tool Calling**: `PASS` (Canonical agent tool execution path wired into `session.send_tool_response`).

### Tests
- Automated tests: 268
- Passed: 268
- Failed: 0
- Deselected: 1
- Duration: 21.84s

### Security
- `.env` tracking state: Untracked (`git ls-files .env` returns empty).
- Credentials: Zero secrets exposed in code, logs, or diagnostic scripts.

### Git / GitHub
- Branch: `main`
- Commit: `6e3e912` (`fix(voice): prevent false barge-in from speaker echo`)
- Push: Verified in sync with `origin/main`
- Worktree: Clean

### Known Limitations
- In physical laptop speaker mode, conversational interruptions are handled cleanly by Gemini's cloud neural VAD with ~300-500ms round-trip latency; in headphones mode (`FRIDAY_VOICE_HEADPHONES_MODE=true`), local zero-latency (<120ms) hardware barge-in is fully enabled.

### Next Planned Work
- Complete Phase 5 sign-off and prepare foundation for Phase 6 desktop automation.

---

## 2026-08-19

### Work Completed

#### 1. Phase 5.17 — Final CLI UX, Provider Preflight, and Quota-Aware Runtime
- Replaced plain minimal header with large, visually impressive 3D block-letter ASCII banner (`______ _____ _____ _____`) in `src/friday/cli/main.py` with 100% Windows PowerShell / ANSI / UTF-8 safety.
- Configured `setup_logging` to direct `DEBUG` and `INFO` internal execution logs strictly to `logs/friday.log` on disk, setting console handler to `WARNING` by default for a clean futuristic dialogue experience. Added `--debug` CLI flag for verbose terminal diagnostics.
- Implemented quota-conscious startup preflight (`GeminiCredentialPool.preflight_check`) using persisted health state to avoid wasteful network quota probing.
- Added granular failure classification (`FailureCategory`) with tailored cooldown durations:
  - `rate_limit_exceeded` (30s)
  - `quota_exceeded` (3600s / 1 hour)
  - `authentication_failed` (24 hours)
  - `model_not_found` (3600s)
  - `service_error` (60s)
  - `network_error` (30s)
- Implemented persistent provider health state across application restarts saved to `data/gemini_pool_state.json` (stores only labels and timestamps, never keys).
- Implemented session-level provider stickiness in `GeminiCredentialPool.get_active_key()` to prevent thrashing between fallbacks within a single user session.
- Silenced auto-embedding warning spam to debug level when circuit breaker is open.
- Trivial queries (`Hello FRIDAY`, `What time is it?`, `Calculate 2+2`) skip semantic embedding and recall entirely; memory-oriented turns fall back instantly to SQLite FTS5 when cloud embeddings are in quota cooldown.

#### 2. Phase 5.16 — Forensic Fix for Persistent Gemini Live "transparent" Reconnect Error
- Identified and fixed runtime reconnect defect where server `GoAway` reconnection failed with:
  `"transparent parameter is only supported in Gemini Enterprise Agent Platform mode, not in Gemini Developer API mode."`
- Removed `transparent=True` from `genai_types.SessionResumptionConfig(handle=self._resumption_handle)` in `src/friday/voice/gemini_live_session.py`.
- Reconnection now creates standard Developer API-compatible `LiveConnectConfig` with valid resumption handle.
- Kept Live model explicitly pinned to `gemini-3.1-flash-live-preview` (text model on `gemini-3.6-flash`).

#### 3. Phase 5.16 — Multi-Project Gemini Credential Failover & Automatic Pool Recovery
- Implemented `GeminiCredentialPool` (`src/friday/auth/credential_pool.py`) managing primary key (`FRIDAY_GEMINI_API_KEY`) and up to four fallback credentials (`FRIDAY_GEMINI_FALLBACK_API_KEY_1`..`_4`).
- Integrated dynamic active key selection into `GeminiLLMProvider` retry loop with automatic failure reporting (`report_failure`), client instance rotation, and key health reset on success.
- Connected Live Voice WebSocket session initialization to `credential_pool.get_active_key()`.
- Wrote all four fallback credentials to local `.env` and performed real-world failover verification:
  - Forced primary credential into cooldown -> Pool returned Fallback 1 -> Real `PONG` response received from Gemini Cloud via `gemini-3.6-flash`.
  - Path: `PRIMARY (cooldown) -> FALLBACK 1 -> SUCCESS` (**REAL FALLBACK REQUEST: PASS**).
- Updated default `llm_model` in `src/friday/core/config.py` from obsolete `gemini-2.5-flash` to `gemini-3.6-flash` (resolving `404 NOT_FOUND` on newly created Google Cloud projects).

#### 4. Phase 5.14 & 5.13 — Persona Hardening & Memory Architecture Optimization
- Refined system prompts in `src/friday/agent/prompts.py` and `gemini_live_session.py` to enforce a calm, confident, concise persona inspired by JARVIS / FRIDAY.
- Prohibited customer-service fillers and sycophantic titles ("Boss").
- Unified SQLite, FTS5 lexical indexing, Gemini semantic embeddings (`gemini-embedding-2`), and Reciprocal Rank Fusion ($k=60$) into a zero-stalling memory architecture.
- Added intelligent decision policies (`should_retrieve_memory`, `should_embed_message`) and SQLite embedding deduplication.

#### 5. Phase 5.12 & 5.11 — Test Isolation & Live Pipeline Forensic Hardening
- Audited and categorized test suite with strict markers: `unit`, `integration`, `security`, `performance`, `live`, `hardware`.
- Configured `pyproject.toml` with `addopts = "-m 'not live and not hardware'"` and `isolate_test_environment` fixture in `conftest.py` ensuring `pytest -q` runs 100% offline with synthetic credentials.
- Fixed partial-chunk FIFO reordering in `SpeakerStream` by preserving leftover bytes at the head of the playback queue.
- Implemented explicit `LiveSessionState` enum for deterministic state transitions.

#### 6. Phase 5.8 through 5.1 — Real-Time Gemini Live Voice Architecture & Real Hardware Acceptance
- Deprecated turn-based voice prototype; built full-duplex asynchronous bidirectional WebSocket streaming via official `google-genai` SDK (`client.aio.live.connect`).
- Implemented `MicrophoneStream` (16kHz 16-bit mono PCM) and `SpeakerStream` (24kHz 16-bit mono PCM).
- Implemented dual-layer instant barge-in: local RMS energy detection ($\text{RMS} > 350.0$) purges speaker buffers in <2ms, while server `interrupted=True` cleans state and logs `[interrupted]` in memory.
- Unified voice tool calling through the central `FridayAgent` brain and `ToolRegistry` with safety authorization gating.
- Conducted 10-scenario real-world live acceptance test against physical laptop hardware and Google Cloud Gemini Live API (10/10 PASS).

#### 7. Security: GitHub Secret Scanning False-Positive Remediation
- Remediated GitHub Secret Scanning alerts triggered by realistic-format synthetic test fixtures across 9 test files.
- Replaced all credential-shaped test fixture strings with safe identifiers (`TEST_GEMINI_API_KEY`, `TEST_OPENAI_API_KEY`).
- Verified `.env` was never tracked in git history.

#### 8. Gemini Stack Modernization & Environment Loading Forensics
- Migrated legacy HTTPX/deprecated libraries to official `google-genai` SDK (`client.models.generate_content`, `client.models.embed_content`).
- Migrated embedding model to `gemini-embedding-2`.
- Implemented dynamic project root discovery (`find_project_root`, `resolve_env_file`) and `NonEmptyEnvSettingsSource` to guarantee robust `.env` loading regardless of current working directory.

### Problems Found
1. **Gemini Live Reconnect Crash**: Reconnection failed with `"transparent parameter is only supported in Gemini Enterprise Agent Platform mode"`.
2. **Fallback Keys Missing from Disk**: In an earlier session, fallback keys were loaded in-memory but not written to `.env`, causing pool to report fallbacks unavailable.
3. **Model 404 for New Projects**: Google Gemini API returned 404 for `gemini-2.5-flash` on newly generated project API keys.
4. **Console Log Spam**: Internal debug/info logs cluttered the terminal during normal user dialogue.
5. **Slow Offline Pytest**: Tests leaked into real network calls when credentials were not isolated.

### Root Cause
1. `SessionResumptionConfig` had `transparent=True` hardcoded, which is rejected by Google AI Studio / Gemini Developer API.
2. Script had not flushed environment variables to the physical `.env` file.
3. Google deprecated `gemini-2.5-flash` for new developer API accounts in favor of `gemini-3.6-flash`.
4. Console logger was attached at `DEBUG`/`INFO` level instead of filtering to `WARNING`.
5. Missing autouse isolation fixture in `conftest.py`.

### Fixes Implemented
1. Removed `transparent=True` from `SessionResumptionConfig` in `gemini_live_session.py`.
2. Populated all 4 fallback keys in `.env` and executed real failover verification (`PONG` received).
3. Updated default text model in `config.py` to `gemini-3.6-flash`.
4. Updated `setup_logging` to support separate `console_level=logging.WARNING` while preserving full disk logging.
5. Added `isolate_test_environment` in `conftest.py` and `test_quota_isolation.py`.

### Verification
- **Automated Tests**: 264 passed, 1 deselected in 22.69s (100% pass rate).
- **Real Fallback Failover**: `PASS` (Primary in cooldown -> Fallback 1 -> `PONG`).
- **Live Voice Connection**: `PASS` (`gemini-3.1-flash-live-preview`).
- **Live Reconnect**: `PASS` (Resumption config verified Developer API compliant).
- **Terminal UX**: `PASS` (3D ASCII banner, clean quiet turns, `--debug` flag).

### Tests
- Automated tests: 264
- Passed: 264
- Failed: 0
- Deselected: 1
- Duration: 22.69s

### Security
- Secret scanning: Zero credentials in tracked repository.
- Untracked `.env`: Verified (`git ls-files .env` empty).
- Test fixtures: All synthetic (`TEST_GEMINI_API_KEY`).

### Git / GitHub
- Branch: `main`
- Commits:
  - `818a6e6`: `feat(cli): polish FRIDAY terminal UX and session provider health`
  - `1967fd2`: `docs(diary): update diary with Phase 5.16 Live reconnect forensic fix`
  - `7980315`: `fix(voice): remove unsupported transparent parameter from SessionResumptionConfig`
  - `ef3459c`: `fix(llm): update default Gemini model to gemini-3.6-flash for new project compatibility`
  - `2ebffc0`: `feat(auth): implement multi-project Gemini credential pool with cooldown and failover`
  - `ded8aa7`: `security(tests): remove credential-shaped test fixtures`
- Push: Synchronized with `origin/main`.
- Worktree: Clean.

### Known Limitations
- Embedding model free-tier quota is shared per project; circuit breaker protects performance by falling back to FTS5.

### Next Planned Work
- Real voice hardware diagnostics and device selection configuration.

---

## 2026-08-18

### Work Completed

#### 1. Phase 1 — Project Inception & Core Intelligence Foundation (v0.1.0 – v0.3.11)
- Initialized empty repository (`d:/FRIDAY`) on Python 3.11.9 on Windows 11 x64.
- Established permanent living Project Diary (`docs/FRIDAY_DIARY.md`) as canonical source of truth.
- Built core engine:
  - `src/friday/core/types.py`: `Role`, `SafetyLevel` (`SAFE`, `SENSITIVE`, `DANGEROUS`), `Message`, `ToolCall`, `ToolResult`, `AgentResponse`, `AuthorizationRequest/Response`.
  - `src/friday/core/exceptions.py`: Custom domain exception hierarchy.
  - `src/friday/core/config.py`: Pydantic Settings with automatic `.env` loading and secret masking.
  - `src/friday/core/logging.py`: Structured logging with `SanitizedFormatter` and `SecretMaskingFilter`.
  - `src/friday/core/auth.py`: Authorization abstractions (`BaseAuthorizer`, `DefaultSecureAuthorizer`, `CLIAuthorizer`).
- Built LLM provider abstraction:
  - `src/friday/llm/base.py`: `BaseLLMProvider` interface.
  - `src/friday/llm/mock_provider.py`: Offline deterministic mock provider.
  - `src/friday/llm/openai_provider.py`: HTTPX provider for OpenAI/Groq/Ollama/OpenRouter.
  - `src/friday/llm/gemini_provider.py`: Native Google Gemini REST provider.
- Built extensible Tool subsystem:
  - `src/friday/tools/base.py`: `BaseTool` with JSON schema argument validation and mandatory `SafetyLevel`.
  - `src/friday/tools/registry.py`: `ToolRegistry` with schema-driven validation, safety-gated execution, and concurrent execution for independent `SAFE` tools.
  - Built-in tools:
    - `SystemInfoTool` (`get_system_info`, `SAFE`): OS, architecture, Win32 RAM statistics, runtime details.
    - `TimeDateTool` (`get_time_date`, `SAFE`): Local system date, time, weekday, timestamp.
    - `CalculatorTool` (`calculator`, `SAFE`): Safe AST-parsed arithmetic evaluator with DoS size/exponent limits.
    - `FileReaderTool` (`read_file`, `SAFE`): Sandboxed read-only file reader with path traversal blocking.
    - `FileListingTool` (`list_dir`, `SAFE`): Sandboxed directory listing with traversal protection.
- Built orchestration loop & CLI:
  - `src/friday/agent/agent.py`: Multi-step sequential tool calling loop bounded by `max_tool_iterations` (default: 5) with tool execution callbacks.
  - `src/friday/cli/main.py`: Interactive console REPL with slash commands (`/help`, `/status`, `/history`, `/tools`, `/clear`, `/exit`).

#### 2. Phase 2 — Persistent Memory Foundation (v0.4.0 – v0.4.6)
- Designed 4-layer layered memory model:
  - Layer 1 (Working Memory): Sliding in-memory context buffer.
  - Layer 2 (Persistent Conversation Memory): SQLite ACID storage with session isolation (`SQLiteConversationMemory`).
  - Layer 3 (Historical Search): SQLite FTS5 Porter-stemmed BM25 keyword search (`messages_fts`).
  - Layer 4 (Semantic Vector Memory): Cloud-first vector embeddings (`gemini-embedding-2` / 768d) with pure-Python cosine similarity.
- Implemented SQLite tables (`conversations`, `messages`, `messages_fts`, `embeddings`) with real-time sync triggers (`trg_messages_ai`, `trg_messages_ad`, `trg_messages_au`).
- Database tuning: WAL mode, `NORMAL` synchronous, 20s busy timeout, 64MB cache, index on `conversations(updated_at DESC)`.
- Multi-conversation lifecycle management: `/new`, `/conversations`, `/switch`, `/rename`, `/current`, `/delete`.
- Privacy & safety: Cascade deletion isolation, `/purge` with `CONFIRM PURGE` prompt, `memory_retention_days` auto-pruning.
- Disaster recovery: Non-blocking hot online backups (`mem.backup()`, `/backup`) and full JSON export (`/export`).
- Added built-in `MemorySearchTool` (`search_memory`, `SAFE`) enabling agent to query past conversations.

#### 3. Phase 3 & 4 — Gemini Cloud Brain, Semantic Embeddings & Voice Foundation (v0.4.6 – Phase 4)
- Added `GeminiLLMProvider` and `GeminiEmbeddingProvider` using Google Gemini REST endpoints.
- Implemented Reciprocal Rank Fusion (RRF, $k=60$) hybrid search fusing SQLite FTS5 lexical ranks and semantic vector similarity scores.
- Implemented `cost_mode = "free_first"` policy, bounding retry loops on 429 quota exhaustion.
- Built initial Phase 4 Voice Subsystem prototype (`src/friday/voice/`) and Proactive Task Engine (`src/friday/tasks/` with SQLite-backed scheduler).

### Problems Found
1. **Windows Console Encoding**: `UnicodeEncodeError` on `cp1252` terminal during banner rendering.
2. **Logging Traceback Leakage**: Standard logging filters missed exception tracebacks since `exc_info` is formatted after filters run.
3. **JSON Serialization in Tool Calls**: Python's default `str(dict)` produced invalid single-quoted JSON strings.
4. **Path Traversal Vulnerability**: Relative traversal (`../`) and absolute paths (`C:\Windows`) required strict workspace containment.

### Root Cause
1. Windows PowerShell defaults to `cp1252` codepage which cannot encode unicode block characters.
2. Standard Python `logging.Filter` only inspects `LogRecord.msg`, not formatted tracebacks.
3. `Message.to_provider_dict()` invoked `str(arguments)` instead of `json.dumps(arguments)`.
4. Lack of absolute path checks before `Path.resolve()`.

### Fixes Implemented
1. Replaced banner with pure ASCII block art and added `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
2. Implemented `SanitizedFormatter` in `src/friday/core/logging.py` intercepting final formatted string outputs of all handlers.
3. Replaced argument serialization with `json.dumps()`.
4. Hardened `FileReaderTool` and `FileListingTool` to reject absolute/drive-anchored paths and verify resolved workspace containment.

### Verification
- **Unit & Integration Tests**: All passed across 168 tests.
- **SQLite Performance Benchmarks**:
  - Insert Latency: <1.5ms
  - Load Conversation (50 msgs): <0.5ms
  - Context Window Query: <0.3ms
  - FTS5 Full-Text Search (1000 msgs): <2.0ms
- **Gemini Tool Calling**: Verified direct answers, single tool round-trips, parallel SAFE tools, and multi-step reasoning chains.

### Tests
- Automated tests: 168
- Passed: 168
- Failed: 0
- Skipped: 0
- Duration: 31.03s

### Security
- `.gitignore` configured to ignore `.env`, `data/*.db`, `logs/*.log`.
- SanitizedFormatter active across console and disk handlers.
- Tiered authorization model strictly enforced.

### Git / GitHub
- Branch: `main`
- Initialized local repository and published to `https://github.com/surendra2304/FRIDAY`.
- Key Commits:
  - `74bd226`: `chore: initialize FRIDAY core foundation (v0.1.0)`
  - `0e4709c`: `feat(agent): implement sequential tool-calling architecture & argument validation (v0.2.0)`
  - `1cb8b52`: `feat(tools): expand FRIDAY core read-only toolset (v0.3.0)`
  - `1c56676`: `feat(security): add explicit tool authorization and confirmation flow (v0.3.5)`
  - `b5914d1`: `feat(agent): support coordinated multi-tool execution (v0.3.8)`
  - `fc908d9`: `feat(memory): add persistent SQLite conversation storage (v0.4.0)`
  - `54d3238`: `feat(memory): add searchable historical conversation retrieval (v0.4.3)`
  - `118843b`: `feat(phase2): complete FRIDAY persistent memory foundation (v0.4.6)`
  - `3ed3430`: `feat(llm): add Gemini cloud provider`
  - `0ed7a1e`: `feat(memory): add Gemini semantic embeddings and local retrieval`
  - `8a5a6cd`: `feat(phase4): complete FRIDAY voice and proactive interaction foundation`
- Worktree: Clean.

### Known Limitations
- Initial Phase 4 voice provider was turn-based with mock TTS; full-duplex live WebSocket streaming was scheduled for Phase 5.

### Next Planned Work
- Modernize Gemini stack with official `google-genai` SDK and build full-duplex Gemini Live WebSocket voice engine.

---

## Architectural Decision Records (ADRs)

### ADR-001: Native Python Abstractions vs Heavy Agent Frameworks
- **Decision**: Build native lightweight interfaces (`BaseLLMProvider`, `BaseTool`, `BaseMemory`).
- **Rationale**: Avoid framework dependency bloat, fragile breaking changes, hidden prompt engineering, and unconstrained execution paths.
- **Consequences**: Full control over agent loops and tool gating with zero overhead.

### ADR-002: Three-Tier Explicit Tool Safety Model (`SAFE`, `SENSITIVE`, `DANGEROUS`)
- **Decision**: Enforce safety classification enum on every tool.
- **Rationale**: Personal AI assistants executing local computer tasks must have deterministic boundaries. `SAFE` allows read-only queries autonomously; `SENSITIVE` and `DANGEROUS` mandate interactive confirmation.
- **Consequences**: Tools cannot execute state-altering or destructive actions silently.

### ADR-003: First-Class Deterministic Mock LLM Provider
- **Decision**: Provide an offline `MockLLMProvider` out of the box with post-tool synthesis.
- **Rationale**: Allows the entire test suite and CLI demo to run instantly offline, with zero cost and 100% determinism.
- **Consequences**: Fast, zero-quota CI test runs.

### ADR-004: In-Memory Sliding Buffer for Initial Context Management
- **Decision**: Implement `InMemoryConversationMemory` with fixed message buffer for V0.1/V0.2.
- **Rationale**: Clean separation of concerns prior to introducing persistent database layers.
- **Consequences**: Decoupled interface `BaseMemory` enabled seamless SQLite drop-in replacement in Phase 2.

### ADR-005: Sequential Multi-Step Tool-Calling Decision Loop
- **Decision**: Implement an iterative while loop bounded by `max_tool_iterations` (default: 5) inside `FridayAgent.process_message()`.
- **Rationale**: Enables chaining dependent tool invocations (Tool A output $\rightarrow$ Tool B input) while preventing infinite recursive loops.
- **Consequences**: Autonomous multi-stage problem solving with deterministic upper limits.

### ADR-006: Schema-Driven Tool Argument Validation at Registry Boundary
- **Decision**: Validate tool arguments against the tool's JSON schema properties and required fields before executing `tool.execute()`.
- **Rationale**: Early schema validation produces structured error messages in `ToolResult` that allow LLMs to self-correct missing or malformed arguments.
- **Consequences**: Zero unhandled parameter crashes during tool execution.

### ADR-007: SQLite as the Embedded Persistent Memory Backend
- **Decision**: Use standard library `sqlite3` for persistent conversation storage while keeping `BaseMemory` abstract.
- **Rationale**: Zero-configuration, ACID transactional guarantees, single-file portability (`data/friday.db`), and zero external server dependencies.
- **Consequences**: Durable local persistence across sessions with zero extra infrastructure.

### ADR-008: SQLite FTS5 Full-Text Search for Historical Message Retrieval
- **Decision**: Leverage SQLite's built-in FTS5 virtual table engine with BM25 relevance ranking and Porter stemming for keyword memory retrieval.
- **Rationale**: Sub-2ms search latencies across thousands of messages, 0 extra dependencies, and automatic database trigger synchronization.
- **Consequences**: High-speed keyword context retrieval for CLI (`/search`) and autonomous agent (`search_memory` tool).

### ADR-009: Multi-Conversation Session Isolation & Two-Tier Deletion Safety
- **Decision**: Structure persistent storage into discrete conversation threads with foreign-key cascade deletes and two-tier deletion confirmations (single session vs full `/purge`).
- **Rationale**: Prevents topic cross-contamination and protects against accidental database-wide wipes.
- **Consequences**: Clean session organization and airtight privacy controls.

### ADR-010: Online Hot Database Backups & JSON Export
- **Decision**: Implement hot online local database backups using `sqlite3.Connection.backup()` and structured JSON exports.
- **Rationale**: Guarantees non-blocking, transaction-consistent disk copies while the agent is actively writing.
- **Consequences**: Reliable on-demand local backups without downtime.

### ADR-011: Cloud-First Google Gemini LLM Provider (Low Laptop Compute)
- **Decision**: Add first-class support for Google Gemini API (`GeminiLLMProvider`) as primary model provider.
- **Rationale**: Offload heavy inference to cloud; laptop coordinates I/O, SQLite memory, tools, and UI with minimal battery/CPU drain.
- **Consequences**: High-performance reasoning with zero local GPU requirement.

### ADR-012: Free-First Cost Control, Rate-Limit Resiliency & Usage Observability
- **Decision**: Implement `cost_mode="free_first"`, bounded exponential backoff on 429 errors, and privacy-preserving metadata observability.
- **Rationale**: Cloud usage must never trigger unexpected billing, and quota limits must fail gracefully without stalls.
- **Consequences**: Predictable operation within free-tier quotas and total visibility into turn metrics.

### ADR-013: Provider-Independent Remote Semantic Memory & FTS5 Graceful Fallback
- **Decision**: Implement Layer 4 Semantic Long-Term Memory using cloud-first remote embeddings (`gemini-embedding-2`), local SQLite vector storage, pure-Python cosine similarity, and seamless automatic degradation to SQLite FTS5 BM25.
- **Rationale**: Rich semantic retrieval without local PyTorch/model overhead or external vector DB daemons.
- **Consequences**: Instantaneous setup, zero local memory load, and guaranteed fallback to lexical search when offline or quota-limited.

### ADR-014: Full-Duplex Multimodal Live Voice Session with Dual-Layer Barge-In
- **Decision**: Build real-time voice streaming using official `google-genai` SDK WebSocket sessions (`gemini-3.1-flash-live-preview`), 16kHz linear PCM input, 24kHz linear PCM output, server-side VAD, and local RMS speech energy zero-lag buffer purging (<2ms).
- **Rationale**: Replaces disjointed recording/TTS turn-taking with natural, interruptible conversational dialogue.
- **Consequences**: True futuristic conversational AI experience operating within <1% CPU and <100MB RAM.

### ADR-015: Multi-Project Gemini Credential Failover Pool
- **Decision**: Implement thread-safe `GeminiCredentialPool` managing a Primary key and 4 Fallback keys with categorized cooldown windows, persisted health state in `data/gemini_pool_state.json`, and session-level stickiness.
- **Rationale**: Protects continuous assistant operation against free-tier rate limits and project-level quota exhaustion without requiring manual reconfiguration.
- **Consequences**: Transparent, uninterrupted multi-project failover across text and live voice interactions.
