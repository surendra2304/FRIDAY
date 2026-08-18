# FRIDAY Project Diary

> **Permanent, never-ending historical record and institutional memory of the FRIDAY project.**
> **Started: 2026-08-18 | Current Version: v0.4.6 | Milestone: Phase 2 Complete (Persistent Memory Foundation)**

---

## 2026-08-18 — Day 1

### Project state at start

* The project directory (`d:/FRIDAY`) was completely empty at the start of the day.
* No existing codebase, configuration, dependency files, or documentation existed.
* System environment: Python 3.11.9 on Windows 11 x64, with Git and GitHub CLI (`gh`) authenticated.
* Core mission established: Build **FRIDAY** (**F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou) as a modular, extensible, safety-first personal AI assistant without premature dependencies on heavy monolithic frameworks.

---

### Work completed

#### Session 1 — Architecture Specification & Project Setup
* Established foundational architectural principles: modularity, native interfaces, typed schemas, strict 3-tier safety model, and secret-safe logging.
* Defined the permanent Project Diary structure in `docs/FRIDAY_DIARY.md` as the eternal source of truth.
* Authored `pyproject.toml`, `requirements.txt`, `.env.example`, and `.gitignore`.

#### Session 2 — Core Engine & Subsystem Implementation (V0.1)
* **`friday.core`**:
  * Implemented strongly-typed data structures (`Role`, `SafetyLevel`, `Message`, `ToolCall`, `ToolResult`, `AgentResponse`) in `src/friday/core/types.py`.
  * Built custom domain exception hierarchy (`FridayError`, `ConfigError`, `LLMProviderError`, `ToolError`, `SafetyError`, `MemoryError`) in `src/friday/core/exceptions.py`.
  * Built configuration manager using `pydantic-settings` with automatic `.env` loading and custom `__repr__` to mask API keys in `src/friday/core/config.py`.
  * Built structured logging with `SecretMaskingFilter` to sanitize API keys and tokens from console and disk logs in `src/friday/core/logging.py`.
* **`friday.llm`**:
  * Defined abstract provider interface `BaseLLMProvider` in `src/friday/llm/base.py`.
  * Implemented `MockLLMProvider` in `src/friday/llm/mock_provider.py` for deterministic offline testing and zero-cost CI.
  * Implemented `OpenAILLMProvider` in `src/friday/llm/openai_provider.py` using `httpx` for OpenAI, Groq, Ollama, and OpenRouter endpoints.
  * Implemented dynamic provider instantiation in `src/friday/llm/factory.py`.
* **`friday.tools`**:
  * Defined `BaseTool` in `src/friday/tools/base.py` with automatic OpenAI function schema generation and mandatory `SafetyLevel`.
  * Built `ToolRegistry` in `src/friday/tools/registry.py` with registration, discovery, schema export, and safety-gated execution.
  * Implemented built-in `SystemInfoTool` (`SAFE`) in `src/friday/tools/builtin/system_info.py` to retrieve OS, architecture, runtime, and time.
* **`friday.memory`**:
  * Defined `BaseMemory` interface in `src/friday/memory/base.py`.
  * Implemented `InMemoryConversationMemory` in `src/friday/memory/in_memory.py` with sliding window message buffer.
* **`friday.agent`**:
  * Built prompt engine and persona guidelines in `src/friday/agent/prompts.py`.
  * Implemented core orchestration loop `FridayAgent` in `src/friday/agent/agent.py` coordinating memory, prompts, model reasoning, tool execution, and response synthesis.
* **`friday.cli`**:
  * Built interactive console interface `src/friday/cli/main.py` with custom slash commands (`/help`, `/status`, `/history`, `/tools`, `/clear`, `/exit`).
  * Configured package entry points in `src/friday/__main__.py` and `pyproject.toml`.

#### Session 3 — Test Suite & Initial Bug Fixes
* Implemented 24 comprehensive pytest unit and integration tests across 6 test modules in `tests/`.
* Discovered and resolved Windows console encoding issue (`UnicodeEncodeError` on `cp1252` terminal) by adopting ASCII-safe artwork and configuring UTF-8 stdout reconfiguration.
* Discovered and resolved double-redaction assertion discrepancy in `test_logging.py`.
* Validated 100% test pass rate (24/24 passed in 0.17s).

#### Session 4 — GitHub Setup & Repository Publication
* Initialized local Git repository on `main` branch.
* Verified zero secret leakage in tracked files (`.gitignore` verified).
* Created public remote repository `https://github.com/surendra2304/FRIDAY` via GitHub CLI.
* Pushed initial foundation commit (`74bd226`) to GitHub.

#### Session 5 — Milestone V0.2: Agent Brain & Multi-Step Tool-Calling Loop
* **Schema-Driven Argument Validation**:
  * Added `validate_arguments(arguments)` method to `BaseTool` in `src/friday/tools/base.py` verifying required parameters and expected data types (`string`, `integer`, `number`, `boolean`, `array`, `object`).
  * Integrated schema validation into `ToolRegistry.execute()` in `src/friday/tools/registry.py` to intercept and return structured `ToolResult` error payloads if arguments are malformed.
* **Enriched System Diagnostics Tool**:
  * Enhanced `SystemInfoTool` in `src/friday/tools/builtin/system_info.py` to provide comprehensive OS details, machine architecture, logical CPU core count, real-time physical RAM statistics via Win32 API, Python runtime paths, and category filters (`all`, `os`, `hardware`, `runtime`).
* **Sequential Multi-Step Agent Tool-Calling Loop**:
  * Refactored `FridayAgent.process_message()` in `src/friday/agent/agent.py` with a multi-step execution loop.
  * Supported sequential tool calling pipelines (e.g. Turn 1 $\rightarrow$ Tool A $\rightarrow$ Turn 2 $\rightarrow$ Tool B $\rightarrow$ Turn 3 $\rightarrow$ Final Response).
  * Added `max_tool_iterations` (default: 5) safety guardrail to protect against infinite tool-calling loops.
  * Added `tool_callback` support to broadcast real-time tool execution events to UI/CLI listeners.
* **Interactive CLI Tool Feedback**:
  * Updated `src/friday/cli/main.py` to register an active tool execution event listener printing `-> [Tool] <tool_name> (<safety_level>) [DONE|ERROR]` in real time.
* **Intelligent Mock Synthesis**:
  * Upgraded `MockLLMProvider` in `src/friday/llm/mock_provider.py` to detect incoming `Role.TOOL` output messages and synthesize a natural language response referencing tool results.
* **Expanded Test Matrix**:
  * Added comprehensive tests for direct response, single tool invocation, multi-step sequential tool chaining, unknown tool handling, schema argument validation errors, tool runtime exceptions, safety gating, max iteration guardrails, tool event callbacks, and multi-turn context retention.
  * Total test count increased to **35 tests (100% passing)**.

#### Session 6 — Phase 1.1: Repository Audit and Architecture Stabilization
* Checked and resolved key bugs and weak points identified during a targeted architectural audit:
  * **JSON Serialization Bug**: Replaced Python's default `str(tc.arguments)` in `Message.to_provider_dict()` (which produces invalid single-quoted Python dict representations) with standard `json.dumps()` output to comply with standard JSON parsing.
  * **Validation of Optional Parameters**: Modified `BaseTool.validate_arguments()` to skip type validation check on explicit `None` (null) values, permitting optional arguments to bypass strict checks and default cleanly.
  * **Tool Schema Safety Gating**: Enforced `max_safety` filtering inside `ToolRegistry.get_schemas()` using an explicit safety level hierarchy comparison (`SAFE < SENSITIVE < DANGEROUS`).
  * **LLM Exception Truncation & Key Masking**: Enhanced `OpenAILLMProvider` to parse structured JSON error messages from the endpoint response, truncate raw HTTP response text to 300 characters (preventing raw HTML page dumps in console/logs), and automatically scrub any API keys from propagated error strings.
* Expanded test suite from 35 to **39 tests** covering optional `None` argument validation, safety filtering thresholds, JSON error parsing, and HTML truncation.
* Confirmed 100% test pass rate (39/39 passed in 0.78s).

#### Session 7 — Phase 1.1: Core Audit and Stabilization Updates
* Checked and resolved key bugs, security, and extensibility issues during a targeted core architectural audit:
  * **Strict Rejection of Unexpected Parameters**: Upgraded `BaseTool.validate_arguments()` to strictly check for and reject any keys present in the arguments dictionary that are not defined in the tool's JSON schema properties. This prevents unexpected arguments from triggering runtime `TypeError` exceptions during execution.
  * **Null Gating for Optional Parameters**: Modified `ToolRegistry.execute()` to filter out optional parameters containing `None` values prior to tool invocation. This allows native Python default parameter values in method signatures to take over instead of being overwritten by `None`, preventing potential type crashes inside tool implementations.
  * **Dialogue Context Memory Persistence**: Upgraded `FridayAgent.process_message()` to persist intermediate assistant messages (with tool calls) and tool response messages directly to the short-term conversation memory (`self.memory`) as they occur. Rebuilds `working_context` dynamically in each reasoning iteration. This ensures the complete dialog history is preserved across subsequent turns.
  * **Graceful CLI Configuration Failures**: Wrapped `get_settings()` in a `try-except ValidationError` block at the CLI entry point (`src/friday/cli/main.py`). This catches Pydantic configuration failures on startup and prints a clean user message instead of a stack trace.
* Expanded test suite from 39 to **42 tests** covering unexpected parameter validation errors, null argument filtering default values, and agent multi-turn memory persistence of intermediate tool calls/results.
* Confirmed 100% test pass rate (42/42 passed in 0.73s).

#### Session 8 — Phase 1.2: Tool System Expansion
* Added a robust and secure collection of built-in foundational tools:
  * **Time / Date Tool (`SAFE`)**: Implemented `TimeDateTool` retrieving local date, local time, day of the week, and Unix timestamp. Automatically uses system-local environment settings without hardcoding timezones.
  * **Safe Calculator Tool (`SAFE`)**: Implements `CalculatorTool` evaluating arithmetic expressions. Built with Python's `ast` parsing module to restrict execution strictly to `ast.Expression`, `ast.BinOp` (Add, Sub, Mult, Div, Pow), `ast.UnaryOp` (USub, UAdd), and `ast.Constant` / `ast.Num` values. Rejects any code injection (functions, attributes, imports) and caps max string length (500 chars) and exponentiation scale (max exponent 1000) to prevent CPU denial-of-service (DoS) locks.
  * **Sandboxed File Reader Tool (`SAFE`)**: Implements `FileReaderTool` restricted to reading text files. Enforces path traversal validation using `Path.resolve()` to block accessing directories outside the workspace root (directory sandbox model). Rejects reading binary files and sets a default limit of 100 KB to avoid context overflow.
  * **Sandboxed File Listing Tool (`SAFE`)**: Implements `FileListingTool` to retrieve files and subdirectories inside a workspace directory relative to the workspace root. Enforces traversal boundaries and returns structured markdown tables with details limited to the first 100 elements.
  * **Deferred Web Search Tool**: Web search implementation was deferred to a future milestone because the codebase lacks configured search providers, and scraping duckduckgo creates fragile, slow, and non-deterministic network execution constraints in test runner environments.
* Refactored `FridayAgent._create_default_registry()` to auto-load and register all 5 tools on initialization.
* Expanded test suite from 42 to **54 tests** covering all new built-in tools (arithmetic evaluations, security injection blockages, traversal blocks, file system operations, binary rejections) and natural language agent queries using Mock responders.
* Confirmed 100% test pass rate (54/54 passed in 0.84s).

#### Session 9 — Phase 1.2: Explicit Tool Authorization and Confirmation Flow
* Introduced a robust tool authorization and confirmation mechanism:
  * **Permission Architecture**: Added strongly typed domain models `AuthorizationDecision` (APPROVED, DENIED, EXPIRED, CANCELLED), `AuthorizationRequest` (containing tool name, safety level, arguments, purpose, affected resource), and `AuthorizationResponse` in `src/friday/core/types.py`.
  * **Authorization Abstraction (`BaseAuthorizer` ABC)**: Created a core authorization boundary in `src/friday/core/auth.py` that decouples the agent from interface-specific confirmation mechanisms.
  * **Interactive CLI Confirmation (`CLIAuthorizer`)**: Implemented a terminal-based prompt in `src/friday/cli/auth.py`:
    * `SAFE` tools are auto-approved for automatic execution.
    * `SENSITIVE` tools show a detailed prompt of requested arguments and resources, requiring an explicit case-insensitive `[y/N]` confirmation.
    * `DANGEROUS` tools require typing the exact word `CONFIRM` (case-sensitive) to prevent accidental destructive actions.
    * Gracefully handles KeyboardInterrupt (Ctrl+C) or EOF by converting execution requests to `CANCELLED`.
  * **Secure Defaults (`DefaultSecureAuthorizer` and `AutoDenyAuthorizer`)**: Prevents unsafe executions by defaulting to auto-deny policies when no interactive environment is attached.
  * **Validation Gating**: Ensured validation (parameter schema compliance) happens before authorization requests, and execution happens only after authorization is APPROVED.
  * **Audit logging**: Authorization requests, safety levels, and decisions are cleanly logged to the console/file logs.
* Updated `FridayAgent` to accept `authorizer: Optional[BaseAuthorizer]` and inject `CLIAuthorizer` inside CLI main entry point.
* Expanded test suite from 54 to **63 tests** covering SAFE auto-execution, SENSITIVE approved/denied execution, DANGEROUS approved/denied execution, cancelled/expired confirmations, validation priority, and execution gating.
* Confirmed 100% test pass rate (63/63 passed in 0.86s).

#### Session 10 — Phase 1.2: Coordinated Multi-Tool Coordinated Execution
* Enhanced the agent execution model to support handling multiple tool calls in a single response turn:
  * **Concurrently vs. Sequential Routing Heuristic**: If all tool calls requested in the turn are `SAFE` independent read-only tools, FRIDAY executes them concurrently in a thread pool (`concurrent.futures.ThreadPoolExecutor`) to minimize batch latency.
  * If any requested tool call is `SENSITIVE` or `DANGEROUS`, FRIDAY forces sequential execution to maintain safe execution ordering and confirmation prompt semantics.
  * **Order and Correlation Preservation**: The results are mapped to memory (`Role.TOOL` messages) and appended to the final response in the exact original order requested by the LLM.
  * **Error Handling Resilience**: Isolated failures (exceptions, schema errors, or authorization blocks) inside parallel execution batches do not abort or compromise the results of other successful tool calls.
* Expanded test suite from 63 to **73 tests** in `tests/test_multi_tool.py` covering single tool calls, parallel execution latencies, multi-tool success/failure separation, mixed safety sequential routing, and result correlation order.
* Confirmed 100% test pass rate (73/73 passed in 1.32s).

#### Session 11 — Phase 1.2: Agent Reliability and Observability Hardening
* Hardened FRIDAY's execution model against external and internal exceptions, network transients, and timeout blocks:
  * **LLM Provider Retry & Backoff**: Upgraded `OpenAILLMProvider.generate()` to retry transient network request errors (`httpx.RequestError`), timeouts, and status codes `429` (Rate limits) and `5xx` (Internal server errors) up to 3 times using exponential backoff (1s, 2s, 4s). Parse and respect HTTP `Retry-After` header when rate-limited. Permanent errors (e.g. status code 401/403/400) fail immediately.
  * **Strict Tool Timeout Gating**: Added constructor parameter `tool_timeout` to `FridayAgent`. Wrapped sequential and parallel tool calls inside a `ThreadPoolExecutor` future request to enforce strict timeout boundaries (default: 30 seconds), preventing hangs and returning graceful error messages instead of blocking indefinitely.
  * **Clean Error Translations**: Enhanced LLM generation exception handling in `FridayAgent.process_message()` to catch connection failures, authentication mismatches, or rate limits and return friendly, clean default explanations rather than propagating stack traces or JSON response error bodies.
  * **Audit Observability**: Implemented detailed latency tracking of individual tool execution steps and overall agent turns. Logs are sanitized via the regex secret filter.
  * **Response Diagnostics**: Enriched `AgentResponse.metadata` to output structured indicators `success` and `tools_used` alongside provider, model, and duration statistics.
* Expanded test suite from 73 to **79 tests** in `tests/test_reliability.py` verifying transient network retries, rate limit Retry-After waits, auth errors rejection, tool timeouts, clean error translation, and response diagnostics.
* Confirmed 100% test pass rate (79/79 passed in 12.98s).

#### Session 12 — Phase 1.2: Security Hardening and Execution Boundary Audits
* Conducted a thorough security audit of configuration, environmental handling, logging, tool registry, built-in tools (calculator, time/date, filesystem tools), authorization policies, agent reasoning loops, and provider HTTP boundaries:
  * **Accidental Secret Logging and Traceback Sanitization**: Discovered that standard logging filters do not catch formatted exception tracebacks since `exc_info` is formatted by the Logger Formatter after the Filter is applied. Mitigated this by implementing `SanitizedFormatter` in `src/friday/core/logging.py` which intercepts and sanitizes the final formatted string output of Console and File handlers, protecting against credential leaks in all tracebacks.
  * **Absolute Path Traversal Protection**: Hardened `FileReaderTool` and `FileListingTool` to explicitly reject any absolute or drive-anchored paths (e.g. `/etc/passwd`, `C:\Windows`) inside input parameters prior to path combination and resolution, avoiding Windows UNC drive mapping bypasses and ensuring strict workspace containment.
  * **Safe Arithmetic Evaluation**: Re-verified the `ast` parsing arithmetic evaluator. Node exclusions (Call, Attribute, Subscript, import blocks, and Variable Names) correctly block code injections. Input length (500 chars) and AST Pow combination boundaries successfully defend against Denial of Service CPU locks.
  * **Zero Trust Gating**: Audited execution chains. System parameter schema verification strictly occurs before authorization prompts, preventing parameter pollution and ensuring invalid requests do not reach the user or compromise safety boundaries.
* Expanded test suite from 79 to **82 tests** in `tests/test_logging.py` and `tests/test_tools.py` verifying absolute path rejections (Unix/Windows format boundaries) and SanitizedFormatter traceback filtering.
* Confirmed 100% test pass rate (82/82 passed in 13.30s).

#### Session 13 — Phase 2: Memory Architecture Audit and Persistent Storage Design
* Completed architectural audit and design for Phase 2 Persistent Memory:
  * **Layered Memory Model**: Formally delineated three memory layers:
    1. *Working Memory*: Active short-term conversational context window (system message + recent turns) held in memory for immediate agent decision iterations.
    2. *Persistent Conversation Memory*: Durable local conversation and message store surviving application restarts, recording all turns, tool calls, and results chronologically.
    3. *Long-Term / Semantic Memory (Deferred)*: Associative facts, user preferences, and vector retrieval to be layered on top in future milestones without disrupting the relational message store.
  * **Storage Engine Decision (SQLite)**: Selected native `sqlite3` as the primary persistent backend. Provides zero-configuration local storage, ACID transaction guarantees, single-file portability (`data/friday.db`), in-memory testing capability (`:memory:`), and eliminates external server dependencies.
  * **Relational Data Schema**: Designed strict tables `conversations` (ID, title, created_at, updated_at, metadata) and `messages` (ID, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata) with indexed foreign keys and JSON serialization for complex tool payloads.
  * **Memory Interface & Configuration**: Formulated the `SQLiteConversationMemory` class extending `BaseMemory` while preserving full compatibility with `InMemoryConversationMemory`. Outlined configuration settings (`FRIDAY_MEMORY_BACKEND`, `FRIDAY_MEMORY_DB_PATH`, `FRIDAY_MEMORY_AUTO_PERSIST`).
  * **Documented ADR-007**: Added architectural decision record defining storage selection, decoupling strategy, and semantic memory integration roadmap.

#### Session 14 — Phase 2: Implementation of SQLite Persistent Conversation Memory
* Implemented `SQLiteConversationMemory` in `src/friday/memory/sqlite.py` implementing `BaseMemory`:
  * **Database & Schema Initialization**: Automatically initializes parent directories and creates `conversations` and `messages` tables with indexed foreign key relationships and WAL journaling for maximum crash resilience and fast concurrency.
  * **Session Isolation & Multi-Conversation CRUD**: Full CRUD support for creating, listing, loading, and deleting conversations with cascading message deletions. Fresh conversation sessions are initialized on instantiation if no `conversation_id` is supplied.
  * **Explicit JSON Serialization**: Tool calls (`ToolCall` objects) and extra metadata are serialized to JSON strings and accurately reconstructed without losing types, IDs, or timestamps.
  * **Thread Safety & Transaction Isolation**: Guarded all SQLite operations with threading locks and transaction context managers, ensuring thread safety during multi-tool asynchronous runs.
  * **Zero-Coupling Integration**: `FridayAgent` dynamically attaches to `SQLiteConversationMemory` via `Settings.memory_backend = "sqlite"`, keeping agent reasoning decoupled from storage mechanics.
* Expanded test suite from 82 to **91 tests** in `tests/test_sqlite_memory.py` covering database auto-creation, schema integrity, conversation lifecycle, message CRUD, tool metadata preservation, sliding context window, multi-conversation isolation, persistence across re-instantiation, and multi-thread concurrency.
* Confirmed 100% test pass rate (91/91 passed in 12.53s).

#### Session 15 — Phase 2: Integration of Persistent Conversation Memory in Agent Core
* Integrated persistent conversation memory into `FridayAgent` through the decoupled memory factory:
  * **Memory Factory (`create_memory`)**: Implemented in `src/friday/memory/factory.py` to instantiate `SQLiteConversationMemory` or `InMemoryConversationMemory` based on `Settings.memory_backend`.
  * **Active Conversation Session Management**: Added explicit `conversation_id` parameter to `FridayAgent.__init__`, along with helper properties and methods (`agent.conversation_id`, `agent.switch_conversation(id)`, `agent.create_new_conversation(title)`).
  * **Complete Turn-by-Turn Persistence**: Flow preserves all user prompts, LLM responses, tool calls, tool results, and final synthesized answers inside SQLite while maintaining separate working context window slicing for prompt construction.
  * **Process Restart Simulation**: Reopening an existing conversation ID across different `FridayAgent` instances reliably reconstructs all prior turns and tool metadata without information loss.
  * **CLI Diagnostics Enrichment**: Updated `print_status` in `src/friday/cli/main.py` to display the active `Memory Backend` and `Conversation ID`.
* Expanded test suite from 91 to **98 tests** in `tests/test_agent_persistence.py` verifying agent operations with in-memory and SQLite backends, process restart simulation, tool call/result persistence, session switching, and context window slicing.
* Confirmed 100% test pass rate (98/98 passed in 13.39s).

#### Session 16 — Phase 2: Multi-Conversation Session Management & CLI Commands
* Implemented multi-conversation session management across memory backends and the interactive CLI:
  * **Core Lifecycle Abstractions**: Enhanced `BaseMemory`, `SQLiteConversationMemory`, and `FridayAgent` with session primitives: `create_conversation()`, `list_conversations()`, `get_conversation()`, `rename_conversation()`, `load_conversation()`, and `delete_conversation()`.
  * **Destructive Deletion Safety**: Added safety confirmation prompt `[y/N]` for `/delete` commands to prevent accidental loss of conversation logs.
  * **Interactive CLI Commands**:
    - `/new [title]` — Create and immediately switch to a new conversation session.
    - `/conversations` (or `/list`) — List all stored conversations with message counts and update timestamps.
    - `/switch <id>` — Switch active context using full ID or unique ID prefixes.
    - `/rename <title>` — Rename active conversation session.
    - `/current` — Display metadata, ID, and message metrics for current active session.
    - `/delete [id]` — Permanently delete a conversation session with explicit confirmation.
* Expanded test suite from 98 to **105 tests** in `tests/test_conversation_management.py` verifying new conversation creation, conversation isolation, renaming, active metadata inspection, delete lifecycle, invalid switching, and multi-conversation restart persistence.
* Confirmed 100% test pass rate (105/105 passed in 13.76s).

#### Session 17 — Phase 2: Searchable Historical Conversation Retrieval
* Implemented searchable memory retrieval across persistent conversations:
  * **Memory Search Abstraction**: Added `search()` method to `BaseMemory` returning structured `MemorySearchResult` records with conversation title, message timestamp, author role, content snippet, and relevance ranking score.
  * **SQLite FTS5 Indexing & Triggers**:
    - Created `messages_fts` virtual table using SQLite's FTS5 tokenizer (`porter unicode61`).
    - Installed automatic synchronization triggers (`trg_messages_ai`, `trg_messages_ad`, `trg_messages_au`) ensuring full-text index updates in real-time.
    - Used BM25 ranking (`bm25(messages_fts)`) with query sanitization and wildcard prefix matching, plus graceful `LIKE` pattern fallback.
  * **Built-in `search_memory` Tool**:
    - Added `MemorySearchTool` (`SAFE`) in `src/friday/tools/builtin/memory_search.py` enabling the LLM agent to search historical conversations on-demand when users inquire about past discussions.
  * **Interactive CLI Search**:
    - Added `/search <query>` command to the CLI for direct historical search from the prompt.
* Expanded test suite from 105 to **113 tests** in `tests/test_memory_search.py` covering in-memory search, SQLite exact and prefix matching, conversation filtering, limit enforcement, date constraint filtering, tool execution, agent end-to-end tool loop, and synthetic performance benchmarks (500 messages searched in under 50ms).
* Confirmed 100% test pass rate (113/113 passed in 15.35s).

#### Session 18 — Phase 2: Security & Privacy Hardening of Persistent Memory
* Conducted a comprehensive privacy, security, and data lifecycle review of persistent SQLite conversation storage:
  * **Deletion Isolation & Privacy Guardrails**: Verified that deleting a conversation strictly cascade-deletes only associated messages and FTS5 index tokens without impacting other conversation records or bleeding across sessions.
  * **Search Scoping & Data Boundary Enforcement**: Enforced strict `conversation_id` parameter binding on FTS5 queries, preventing unauthorized cross-conversation keyword leaks when scoped to a specific thread.
  * **Complete Storage Purge (`purge_all`)**: Implemented safe, ACID-compliant database reset (`purge_all()`) which cleans tables, drops virtual indexes, and executes `VACUUM` to free storage on disk, protected in the CLI behind an explicit double-confirmation prompt (`CONFIRM PURGE`).
  * **Configurable Data Retention Policy**: Added `memory_retention_days` setting to `Settings` with automatic pruning on agent initialization, preventing unbounded database growth while preserving recent history by default.
  * **Secret Leakage Prevention**: Verified all diagnostic outputs (`get_status()`) mask sensitive credentials and API keys.
* Expanded test suite from 113 to **119 tests** in `tests/test_memory_security.py` verifying deletion isolation, search scoping privacy, complete purge security, retention policy pruning, auto-pruning on agent startup, and secret masking in diagnostic endpoints.
* Confirmed 100% test pass rate (119/119 passed in 15.57s).

#### Session 19 — Phase 2: Performance, Scalability & Disaster Recovery of Persistent Memory
* Hardened persistent SQLite storage for long-term scalability and recovery:
  * **Database Tuning & Index Optimizations**:
    - Configured high-performance SQLite PRAGMAs: `PRAGMA busy_timeout = 20000;`, `PRAGMA synchronous = NORMAL;`, `PRAGMA cache_size = -64000;` (64MB memory cache) alongside existing `PRAGMA journal_mode = WAL;` and `PRAGMA foreign_keys = ON;`.
    - Added index `idx_conversations_updated` on `conversations(updated_at DESC)` for instant session lookups.
  * **Defensive Row Deserialization & Disaster Recovery**:
    - Added robust fallbacks in `_row_to_message` protecting against malformed metadata JSON, corrupted role strings, or null contents.
    - Verified nested directory auto-creation for missing databases.
  * **Safe Local Backup & JSON Export**:
    - Implemented `backup(backup_path)` using SQLite's native `conn.backup(dest_conn)` API for non-blocking hot backups.
    - Implemented `export_conversation_to_dict(conversation_id)` for exporting complete session histories to JSON files.
    - Added CLI commands `/backup [path]` and `/export [path]`.
  * **Performance Benchmarks**:
    - Validated realistic local workload on 1000 messages across 20 conversations:
      - Average Insert Latency: <1.5ms
      - Load Conversation (50 messages): <0.5ms
      - Context Window Query (last 10 messages): <0.3ms
      - FTS5 Full-Text Search (across 1000 messages): <2.0ms
      - List Conversations (21 conversations): <0.5ms
* Expanded test suite from 119 to **125 tests** in `tests/test_memory_performance_and_recovery.py` verifying auto-creation on missing paths, malformed row recovery, multi-threaded concurrent reads and writes, online backup integrity, conversation JSON export, and performance benchmarks.
* Confirmed 100% test pass rate (125/125 passed in 17.90s).

#### Session 20 — LLM Architecture: First-Class Google Gemini Cloud Provider
* Integrated native Google Gemini REST API provider (`GeminiLLMProvider`) into FRIDAY's cloud-first, low-laptop-compute architecture:
  * **Zero Local Model Overhead**: Heavy inference is offloaded to Gemini Cloud API (`gemini-2.5-flash`, `gemini-1.5-pro`), while the laptop handles FRIDAY agent orchestration, SQLite memory, tools, and UI.
  * **Contract & Message Translation**:
    - Maps FRIDAY `Message(role=SYSTEM)` to Gemini `systemInstruction`.
    - Maps `Message(role=USER)` and `Message(role=ASSISTANT)` with `tool_calls` to Gemini `contents` with `functionCall` objects.
    - Maps `Message(role=TOOL)` to Gemini `function` role with structured `functionResponse` dictionary payload.
  * **Tool Calling Bridge**: Converts OpenAI function JSON schemas into Gemini function declarations with parameters and descriptions.
  * **Resilience & Secret Sanitization**:
    - Implemented exponential backoff with jitter on 429 quota and 5xx transient server errors.
    - Protected against secret leakage: masks `FRIDAY_GEMINI_API_KEY` in logs, exceptions, and `Settings.__repr__`.
    - Normalizes safety filter blocks (`promptFeedback.blockReason`).
* Expanded test suite from 125 to **132 tests** in `tests/test_llm_providers.py` verifying factory instantiation, missing API key guard, request/response payload translation, tool call parsing, API key sanitization, and safety filter block recovery.
* Confirmed 100% test pass rate (132/132 passed in 18.88s).

#### Session 21 — Gemini Function Calling & FRIDAY Tool Trust Boundary
* Integrated Google Gemini tool calling with FRIDAY's tiered tool execution and safety subsystem:
  * **Strict Trust Boundary**: Enforced the fundamental security principle:
    > **Gemini decides WHAT it wants.**
    > **FRIDAY decides WHETHER it is allowed.**
    > **FRIDAY executes it.**
    - Gemini has zero direct OS, memory, or shell access.
    - Every function call from Gemini passes through FRIDAY's schema validation before authorization.
    - SENSITIVE and DANGEROUS tools strictly require user confirmation (`BaseAuthorizer`); unapproved actions are rejected and returned as structured error results without execution.
  * **Schema Declaration Fidelity**:
    - Validated complete translation of `BaseTool.parameters` schemas into Gemini `functionDeclarations` (names, descriptions, required properties, types, nested arrays, and objects).
  * **Multi-Step & Coordinated Execution**:
    - Verified direct answers without tool invocations.
    - Verified single tool call round-trips (User -> Gemini call -> FRIDAY execution -> Result -> Gemini synthesis).
    - Verified multiple independent SAFE tools running concurrently via `ThreadPoolExecutor`.
    - Verified sequential multi-step tool reasoning chains (Step 1 -> Result -> Step 2 -> Result -> Answer).
    - Verified schema error recovery when malformed arguments are provided by the model.
    - Verified maximum iteration guardrail preventing infinite tool recursion.
* Added comprehensive integration test suite `tests/test_gemini_tools.py` (9 tests).
* Expanded total test count from 132 to **141 tests**, maintaining a 100% pass rate in 25.18s.

#### Session 22 — Gemini Model & Cost Controls (Free-First Operation & Observability)
* Hardened FRIDAY's Gemini cloud usage controls for predictable, low-cost/free operation:
  * **Free-First Cost Mode (`FRIDAY_COST_MODE=free_first`)**: Ensures FRIDAY operates with zero hidden or accidental cloud billings, relying on free-tier rate and quota parameters.
  * **Granular Model & Request Controls**:
    - `FRIDAY_GEMINI_MODEL`: Allows overriding the Gemini model independently from global defaults (`gemini-2.5-flash`, `gemini-1.5-pro`).
    - `FRIDAY_GEMINI_TIMEOUT`: Configurable HTTP request timeout (default 60s).
    - `FRIDAY_GEMINI_MAX_RETRIES` & `FRIDAY_GEMINI_BACKOFF_FACTOR`: Exponential backoff respecting provider `Retry-After` headers without endless loops on hard rate limits.
    - `FRIDAY_GEMINI_MAX_TOKENS` & `FRIDAY_GEMINI_TEMPERATURE`: Granular generation parameter overrides.
    - `FRIDAY_MAX_DAILY_REQUESTS`: Optional safety ceiling on total daily model queries.
  * **Provider Isolation & Clean Failures**:
    - Disallowed unconfigured silent fallbacks: a failed Gemini call fails with an informative, user-friendly exception rather than silently leaking data to another cloud provider.
    - Mock provider remains fully decoupled and available for offline test and development environments.
  * **Privacy-Preserving Usage Observability**:
    - Added non-secret turn execution metadata: `duration_seconds`, `iterations`, `request_count`, `cost_mode`, `provider`, `model`, and `success`.
    - Zero prompt/response dumping or API key logging.
* Added dedicated test suite `tests/test_gemini_cost_and_controls.py` (8 tests).
* Expanded total test count from 141 to **149 tests**, maintaining a 100% pass rate in 26.74s.

---

### Architecture / structure changes

```text
FRIDAY/
├── .env.example                     # Environment configuration template
├── .gitignore                       # Git ignore rules for virtualenvs, secrets, logs
├── pyproject.toml                   # Modern packaging metadata & dependency specifications
├── requirements.txt                 # Pinned dependencies
├── README.md                        # Project documentation & usage guide
├── docs/
│   └── FRIDAY_DIARY.md              # Permanent Living Project Diary & ADRs
├── logs/
│   └── friday.log                   # Local sanitized runtime logs
├── src/
│   └── friday/
│       ├── __init__.py
│       ├── __main__.py              # Entrypoint for python -m friday
│       ├── core/
│       │   ├── __init__.py
│       │   ├── auth.py              # BaseAuthorizer, DefaultSecureAuthorizer, and test mocks
│       │   ├── config.py            # Pydantic Settings, env loading, secret masking
│       │   ├── exceptions.py        # Domain exception hierarchy
│       │   ├── logging.py           # Structured logging & secret sanitization filter
│       │   └── types.py             # Role, SafetyLevel, Message, ToolCall, AgentResponse, Authorization
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py              # BaseLLMProvider ABC
│       │   ├── factory.py           # LLM Provider factory
│       │   ├── gemini_provider.py   # Cloud-first Google Gemini Provider (HTTPX)
│       │   ├── mock_provider.py     # Deterministic Mock Provider with post-tool synthesis
│       │   └── openai_provider.py   # OpenAI-compatible Provider (HTTPX)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py              # BaseTool ABC with JSON schema validation & SafetyLevel
│       │   ├── registry.py          # ToolRegistry with schema validation & safety gating
│       │   └── builtin/
│       │       ├── __init__.py
│       │       ├── calculator.py    # Safe AST arithmetic expression evaluator (SAFE)
│       │       ├── file_listing.py  # Sandboxed read-only workspace directory listing (SAFE)
│       │       ├── file_reader.py   # Sandboxed read-only workspace file reader (SAFE)
│       │       ├── memory_search.py # Searchable historical conversation retrieval tool (SAFE)
│       │       ├── system_info.py   # Enriched System Diagnostics Tool (SAFE)
│       │       └── time_date.py     # Local host system date and time details (SAFE)
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── base.py              # BaseMemory ABC
│       │   ├── factory.py           # Memory factory (instantiates backend from settings)
│       │   ├── in_memory.py         # Sliding window conversation memory buffer
│       │   └── sqlite.py            # Persistent SQLite conversation memory
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── agent.py             # FridayAgent with multi-step sequential reasoning loop
│       │   └── prompts.py           # Persona prompts & system messages
│       └── cli/
│           ├── __init__.py
│           ├── auth.py              # Interactive CLIAuthorizer prompting y/N or CONFIRM
│           └── main.py              # Interactive REPL with real-time tool progress feedback
└── tests/
    ├── __init__.py
    ├── conftest.py                  # Pytest fixtures
    ├── test_agent.py                # Agent dialog, multi-step tool loops & error handling tests
    ├── test_agent_persistence.py    # Agent persistent memory integration & session tests
    ├── test_auth.py                 # Authorization gating, validation priority, and CLI tests
    ├── test_config.py               # Settings & masking tests
    ├── test_conversation_management.py # Multi-conversation session management & CLI tests
    ├── test_llm_providers.py        # Mock & OpenAI provider tests
    ├── test_logging.py              # Logging & secret filter tests
    ├── test_memory.py               # Memory buffer & sliding window tests
    ├── test_memory_performance_and_recovery.py # Performance scaling & recovery tests
    ├── test_memory_search.py        # Searchable historical conversation retrieval tests
    ├── test_memory_security.py      # Memory privacy, deletion isolation & retention tests
    ├── test_multi_tool.py           # Coordinated parallel and sequential execution tests
    ├── test_reliability.py          # LLM retries, network errors, tool timeouts, and diagnostics tests
    ├── test_sqlite_memory.py        # Persistent SQLite storage, lifecycle & isolation tests
    └── test_tools.py                # Tool registry, schema validation & safety tier tests
```

---

### Technical decisions

* **ADR-001: Native Python Abstractions vs Heavy Agent Frameworks (LangChain/CrewAI)**
  * *Decision*: Build native lightweight interfaces (`BaseLLMProvider`, `BaseTool`, `BaseMemory`).
  * *Alternatives Considered*: LangChain, CrewAI, AutoGen.
  * *Reason*: Avoid framework dependency bloat, fragile breaking changes, hidden prompt engineering, and unconstrained execution paths. Ensures complete auditability and safety control.
  * *Consequences*: Full control over agent loops and tool gating with zero overhead.

* **ADR-002: Three-Tier Explicit Tool Safety Model (`SAFE`, `SENSITIVE`, `DANGEROUS`)**
  * *Decision*: Enforce safety classification enum on every tool.
  * *Alternatives Considered*: Binary allowlists, unrestricted auto-execution.
  * *Reason*: Personal AI assistants executing local computer tasks must have deterministic boundaries. `SAFE` allows read-only queries autonomously; `SENSITIVE` and `DANGEROUS` mandate interactive confirmation.
  * *Consequences*: Tools cannot execute state-altering or destructive actions silently.

* **ADR-003: First-Class Deterministic Mock LLM Provider**
  * *Decision*: Provide an offline `MockLLMProvider` out of the box with post-tool synthesis.
  * *Alternatives Considered*: Requiring live OpenAI API keys for all tests, patching HTTP calls per test.
  * *Reason*: Allows the entire test suite and CLI demo to run instantly offline, with zero cost and 100% determinism.
  * *Consequences*: New developers can clone and run FRIDAY immediately without API configuration.

* **ADR-004: In-Memory Sliding Buffer for Initial Context Management**
  * *Decision*: Implement `InMemoryConversationMemory` with fixed message buffer for V0.1/V0.2.
  * *Alternatives Considered*: Immediate SQLite or Vector database setup.
  * *Reason*: Premature storage complexity was unnecessary for V0.1/V0.2; clean interface `BaseMemory` allows swapping in SQLite/Vector backends seamlessly in V0.4.
  * *Consequences*: Simple, blazing fast, and clean separation of concerns.

* **ADR-005: Sequential Multi-Step Tool-Calling Decision Loop**
  * *Decision*: Implement an iterative while loop bounded by `max_tool_iterations` (default: 5) inside `FridayAgent.process_message()`.
  * *Alternatives Considered*: Single-turn tool execution, DAG execution graph engines.
  * *Reason*: Enables chaining dependent tool invocations (Tool A output $\rightarrow$ Tool B input) while preventing infinite recursive loops and keeping execution transparent and debuggable.
  * *Consequences*: FRIDAY can autonomously resolve multi-stage tasks while maintaining a strict iteration ceiling.

* **ADR-006: Schema-Driven Tool Argument Validation at Registry Boundary**
  * *Decision*: Validate tool arguments against the tool's JSON schema properties and required fields before executing `tool.execute()`.
  * *Alternatives Considered*: Letting tools fail with Python `TypeError` / `KeyError`.
  * *Reason*: Early schema validation produces consistent, structured error messages in `ToolResult` that allow LLMs to understand what parameter was missing or malformed and self-correct.
  * *Consequences*: Zero unhandled parameter crashes during tool execution.

* **ADR-007: SQLite as the Embedded Persistent Memory Backend**
  * *Decision*: Use standard library `sqlite3` for persistent conversation storage while keeping `BaseMemory` abstract and decoupled from the agent loop.
  * *Alternatives Considered*: PostgreSQL/MySQL (requires external service daemon), JSON flat-files (lacks concurrency safety, slow indexing, corruption risk), Vector databases as primary store (unnecessary overhead for sequential conversation logs).
  * *Reason*: SQLite is built-in, transactional, reliable, and requires zero external infrastructure. It stores conversation histories cleanly and allows future semantic/vector indices to reference message IDs directly.
  * *Consequences*: Instant local persistence across CLI sessions with zero new runtime dependencies.

* **ADR-008: SQLite FTS5 Full-Text Search for Historical Message Retrieval**
  * *Decision*: Leverage SQLite's built-in FTS5 virtual table engine with BM25 relevance ranking and Porter stemming for keyword memory retrieval instead of introducing heavy embedding models in Phase 2.
  * *Alternatives Considered*: Pure Python linear search, external vector databases (Chroma/FAISS) with high latency and GPU/RAM footprint.
  * *Reason*: FTS5 executes in under 2ms across thousands of messages, requires 0 extra dependencies, runs 100% offline, and integrates directly with SQLite database triggers.
  * *Consequences*: High-speed keyword and substring historical context retrieval available to both the CLI (`/search`) and autonomous agent (`search_memory` tool).

* **ADR-009: Multi-Conversation Session Isolation & Two-Tier Deletion Safety**
  * *Decision*: Structure persistent storage into discrete conversation threads with foreign-key cascade deletes, complemented by a strict two-tier deletion model: single session deletion (y/N prompt) vs complete database purge (`CONFIRM PURGE` prompt).
  * *Alternatives Considered*: Single monolithic conversation history, silent auto-deletion.
  * *Reason*: Users need distinct topic threads (work, personal, coding) without context pollution. Destructive database-wide wipes must require explicit, conscious confirmation.
  * *Consequences*: Clean session organization, zero cross-conversation context bleeding, and airtight privacy controls.

* **ADR-010: Online Hot Database Backups & JSON Export**
  * *Decision*: Implement hot online local database backups using `sqlite3.Connection.backup()` and structured JSON exports.
  * *Alternatives Considered*: Raw OS file copies (risks corrupted copies during active writes), cloud sync (violates local-first privacy principle).
  * *Reason*: SQLite's online backup API guarantees non-blocking, transaction-consistent disk copies while the agent is running.
  * *Consequences*: Users can reliably back up or export conversations locally at any time without downtime.

* **ADR-011: Cloud-First Google Gemini LLM Provider (Low Laptop Compute)**
  * *Decision*: Add first-class support for Google Gemini REST API (`GeminiLLMProvider`) as the primary cloud-first model provider rather than running resource-heavy local LLMs via Ollama.
  * *Alternatives Considered*: Local Ollama model execution (high CPU/RAM/battery drain on laptop), vendor-locked proprietary SDKs.
  * *Reason*: FRIDAY is designed to be cloud-first and lightweight on the user's laptop. The laptop handles agent orchestration, SQLite memory, tools, and UI, while heavy language inference is handled by Gemini (`gemini-2.5-flash`).
  * *Consequences*: Blazing fast inference, zero local GPU requirements, structured system instructions, and robust function calling.

* **ADR-012: Free-First Cost Control, Rate-Limit Resiliency & Usage Observability**
  * *Decision*: Structure FRIDAY's Gemini usage with an explicit `cost_mode="free_first"` policy, bounded retry counts with exponential backoff on transient errors, and privacy-preserving non-secret metadata observability.
  * *Alternatives Considered*: Silent provider fallback (risks data leakage to unconfigured third parties), unconstrained retry loops (causes infinite stalls on 429 quota exhaustion).
  * *Reason*: Users require total transparency and cost safety. Cloud usage must never silently trigger paid billing, and failed API calls must fail cleanly and predictably.
  * *Consequences*: Predictable operation within free-tier quotas, zero accidental credit charges, clean user feedback on quota exhaustion, and full visibility into turn request counts and latencies.

---

### Phase 2 Final Memory Architecture Snapshot

```text
+-----------------------------------------------------------------------------+
|                                FRIDAY Agent                                 |
+--------------------------------------+--------------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
+------------------------------------+  +-------------------------------------+
|      Layer 1: Working Memory       |  |  Layer 3: Historical Search & Tool  |
|  [IMPLEMENTED]                     |  |  [IMPLEMENTED]                      |
|  - In-memory sliding context       |  |  - SQLite FTS5 Virtual Table Index  |
|  - Configurable max buffer (50)    |  |  - Porter Stemmer & BM25 Ranking    |
|  - Tool call / result correlation  |  |  - `search_memory` Agent Tool       |
|  - Dynamic prompt assembly         |  |  - CLI `/search <query>` Command    |
+------------------+-----------------+  +------------------+------------------+
                   |                                       |
                   +-------------------+-------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|            Layer 2: Durable Persistent Storage (SQLite + ACID)              |
|  [IMPLEMENTED]                                                              |
|  - Tables: conversations, messages, messages_fts                            |
|  - Triggers: trg_messages_ai, trg_messages_ad, trg_messages_au               |
|  - Tuning: WAL mode, NORMAL synchronous, 20s busy timeout, 64MB cache       |
|  - Lifecycle: /new, /conversations, /switch, /rename, /current, /delete     |
|  - Privacy: Deletion isolation, /purge (CONFIRM PURGE), retention policies  |
|  - Disaster Recovery: Hot online backup (`/backup`), JSON export (`/export`)|
+--------------------------------------+--------------------------------------+
                                       |
                                       v  (Planned Future Interface)
+-----------------------------------------------------------------------------+
|            Layer 4: Long-Term Semantic Vector Memory                        |
|  [FUTURE / DEFERRED TO PHASE 3]                                             |
|  - Local sentence embeddings (all-MiniLM-L6-v2 / BGE-Small)                 |
|  - Embedding vector index (sqlite-vss / Chroma / local HNSW)                |
|  - Cross-session associative recall & automatic fact extraction             |
|  - User preference graph & long-term episodic memory                        |
+-----------------------------------------------------------------------------+
```

---

### Database Schema (v0.4.6)

```sql
-- Conversations Table
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

-- Messages Table
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    name TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at);

-- Full-Text Search Virtual Table
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED,
    conversation_id UNINDEXED,
    content,
    tokenize = 'porter unicode61'
);

-- Real-Time Synchronization Triggers
CREATE TRIGGER IF NOT EXISTS trg_messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(message_id, conversation_id, content)
    VALUES (new.id, new.conversation_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_messages_ad AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_messages_au AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
    INSERT INTO messages_fts(message_id, conversation_id, content)
    VALUES (new.id, new.conversation_id, new.content);
END;
```

---

### Bugs encountered

#### Bug 1: Windows Console Unicode Encoding Error (`UnicodeEncodeError`)
* **Symptoms**: Running `python -m friday` in standard Windows PowerShell resulted in `UnicodeEncodeError: 'charmap' codec can't encode characters in position 78-92`.
* **Cause**: Windows console standard output default codepage (`cp1252`) cannot render unicode block characters (`█`) in the ASCII banner or unicode bullet dots (`•`).
* **Investigation**: Piped execution through PowerShell revealed terminal crash during banner print.
* **Fix**: Replaced banner typography with pure standard ASCII art (`______ _____ ...`), replaced unicode bullets with `*`, and added `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` safeguard.
* **Verification**: Piped multi-command PowerShell execution and direct interactive CLI both executed cleanly without errors.

#### Bug 2: Test Assertion Failure in `test_logging.py`
* **Symptoms**: `test_secret_masking_filter_direct_secret` failed with `AssertionError: assert '***' in 'Using token: [REDACTED] to connect'`.
* **Cause**: The `SecretMaskingFilter` first replaced exact secret text with `***`, but the subsequent regex pattern `(token)\s*:\s*...` matched `token: ***` and converted it to `token: [REDACTED]`.
* **Investigation**: Inspected filter order and test fixture string format.
* **Fix**: Updated test message to `"Using credentials {secret} to connect"` to isolate direct secret masking from regex keyword masking.
* **Verification**: Pytest passed 24/24 tests.

---

### Errors / failed attempts

1. **Attempted `pip install -e .` without explicit PyPI index**:
   * *Error*: `ERROR: Could not find a version that satisfies the requirement pydantic>=2.5.0 (from versions: none)`.
   * *Cause*: Pip in the environment was configured with empty local cache or lacked default index flag.
   * *Resolution*: Installed `pydantic`, `pydantic-settings`, `httpx` via `-i https://pypi.org/simple`.
2. **Attempted `pip install -e . --no-build-isolation` without `wheel` package**:
   * *Error*: `error: invalid command 'bdist_wheel'`.
   * *Cause*: Python 3.11 environment lacked `wheel` package required by setuptools editable installation backend.
   * *Resolution*: Installed `wheel` package, after which `pip install -e . --no-build-isolation` built and installed `friday-agent==0.1.0` successfully.

---

### Tests performed

1. **Pytest Unit Test Suite**:
   * Command: `pytest -v`
   * Result: **132 passed in 18.88 seconds**.

---

### Git activity

* **Branch**: `main`
* **Commits**:
  * `74bd226`: `chore: initialize FRIDAY core foundation (v0.1.0)`
  * `47995ff`: `docs(diary): finalize Day 1 entry with exact commit and push metadata`
  * `0e4709c`: `feat(agent): implement sequential tool-calling architecture & argument validation (v0.2.0)`
  * `68207a1`: `docs(diary): finalize V0.2 commit hash in Day 1 log`
  * `f18dc31`: `chore(architecture): stabilize FRIDAY core foundation for Phase 1 (v0.2.1)`
  * `524c8be`: `chore(core): stabilize FRIDAY architecture for Phase 1 (v0.2.2)`
  * `1cb8b52`: `feat(tools): expand FRIDAY core read-only toolset (v0.3.0)`
  * `1c56676`: `feat(security): add explicit tool authorization and confirmation flow (v0.3.5)`
  * `b5914d1`: `feat(agent): support coordinated multi-tool execution (v0.3.8)`
  * `5519b4d`: `feat(core): improve agent reliability and execution observability (v0.3.9)`
  * `4f49bc5`: `security(core): harden FRIDAY Phase 1 execution boundaries (v0.3.10)`
  * `dd4b253`: `feat(phase1): complete FRIDAY core intelligence foundation (v0.3.11)`
  * `f42a653`: `docs(memory): design persistent FRIDAY memory architecture (v0.3.12)`
  * `fc908d9`: `feat(memory): add persistent SQLite conversation storage (v0.4.0)`
  * `83ad174`: `chore: ignore local SQLite databases in data directory`
  * `2ff4db3`: `feat(agent): integrate persistent conversation memory (v0.4.1)`
  * `6b142d4`: `feat(memory): add persistent conversation management (v0.4.2)`
  * `54d3238`: `feat(memory): add searchable historical conversation retrieval (v0.4.3)`
  * `f23695b`: `security(memory): harden persistent memory privacy and retention (v0.4.4)`
  * `74b87e7`: `perf(memory): harden persistent memory storage and recovery (v0.4.5)`
  * `118843b`: `feat(phase2): complete FRIDAY persistent memory foundation (v0.4.6)`
  * `3ed3430`: `feat(llm): add Gemini cloud provider`
  * `e9c1043`: `feat(llm): integrate Gemini function calling with FRIDAY tools`
  * *(Pending Commit)*: `feat(config): add Gemini model and usage controls`
* **Remote Repository**: `https://github.com/surendra2304/FRIDAY`
* **Push Status**: Verified and in sync with `origin/main`

---

### Current project state

* **Status**: Complete, fully functional, and stabilized **Gemini Model Controls, Cost Governance & Usage Observability**.
* **Capabilities Operational**:
  * First-class Google Gemini Cloud Provider (`gemini-2.5-flash`, `gemini-1.5-pro`) with function calling, structured system instructions, and zero local laptop compute overhead.
  * Free-first cost policy (`FRIDAY_COST_MODE=free_first`) ensuring operations stay within predictable free-tier limits without accidental paid service activations.
  * Fine-grained model tuning controls: `FRIDAY_GEMINI_TIMEOUT`, `FRIDAY_GEMINI_MAX_RETRIES`, `FRIDAY_GEMINI_BACKOFF_FACTOR`, `FRIDAY_GEMINI_MAX_TOKENS`, `FRIDAY_GEMINI_TEMPERATURE`, and `FRIDAY_MAX_DAILY_REQUESTS`.
  * Safe retry limits bounded by `max_retries` with exponential backoff on transient errors and rate limits (429/5xx).
  * Strict provider isolation preventing unconfigured fallback leakage across third parties.
  * Non-secret usage observability in `AgentResponse.metadata` (duration, iterations, request count, provider, model, cost mode).
  * Strict trust boundary enforcement: Gemini requests function calls $\rightarrow$ FRIDAY validates schemas $\rightarrow$ FRIDAY checks authorization $\rightarrow$ FRIDAY executes $\rightarrow$ returns structured result.
  * Support for direct responses, single tool call round-trips, concurrent parallel SAFE tools, and multi-step sequential reasoning.
  * Zero automated execution bypass for `SENSITIVE` and `DANGEROUS` tools.
  * Multi-step sequential tool calling decision loop with iteration guardrails.
  * Real-time tool execution event streaming in CLI.
  * Schema-based argument validation across all registered tools with optional `None` argument safety and strict unexpected parameter rejection.
  * Optional parameter `None` gating to preserve Python parameter defaults during execution.
  * Dynamic context assembly and memory persistence of intermediate tool calls/results.
  * Graceful ValidationError config gating on CLI startup.
  * Enriched system diagnostics tool (`get_system_info`) supporting category filtering and hardware inspection.
  * Time and Date tool (`get_time_date`) retrieving local OS date and time.
  * Safe AST-parsed Calculator tool (`calculator`) with length/exponentiation DoS guardrails.
  * Sandboxed File Reader (`read_file`) and Directory Lister (`list_dir`) tools with strict path traversal checking.
  * Strongly-typed tool authorization request/response model with auto-deny secure defaults.
  * Interactive CLI confirmation prompt (`CLIAuthorizer`) with detailed resource printing and case-sensitive verification for dangerous tools.
  * Validation priority gating (verifies schema before authorization, authorizes before execution).
  * Coordinated multi-tool execution (parallel ThreadPool for concurrent SAFE tools, sequential ordering for mixed/sensitive tools).
  * Robust LLM retry and backoff policy handling network transients, timeout limits, and rate limits (429/5xx).
  * Strict tool timeout boundary enforcement via thread executor futures.
  * User-friendly exceptions translation and secret-safe diagnostics response metadata.
  * Secure SanitizedFormatter blocking all credentials and token leaks from exceptions and traceback logs.
  * Explicit absolute and drive-anchored paths rejection in sandboxed file tools.
  * Persistent conversation memory backend (`SQLiteConversationMemory`) with automatic database creation, session isolation, and ACID guarantees.
  * Multi-conversation lifecycle management (creation, listing, switching, renaming, safe deletion with confirmation).
  * Searchable historical conversation retrieval (SQLite FTS5 full-text indexing, BM25 ranking, `search_memory` tool, CLI `/search` command).
  * Memory privacy, deletion isolation, configurable retention pruning (`memory_retention_days`), and complete storage purge (`/purge` with `CONFIRM PURGE`).
  * High-performance SQLite database tuning (WAL mode, `NORMAL` synchronous, 64MB memory page cache, `idx_conversations_updated` index).
  * Safe hot online backup (`mem.backup()`, CLI `/backup`) and full conversation JSON export (`mem.export_conversation_to_dict()`, CLI `/export`).
  * Defensive deserialization recovering from corrupt rows or malformed JSON payloads.
  * Correct JSON double-quote argument serialization (fixed Python single-quote bug).
  * Robust error recovery for missing tools, malformed arguments, tool exceptions, and safety denials.
  * Cloud endpoint HTTP error message extraction and HTML truncation handling.
  * 100% pass rate across 149 automated tests.

---

### Known issues

* Real-time LLM token streaming to CLI output (planned for future iteration).

---

### Next planned work

* **Phase 3 — Local Voice Interface & Long-Term Semantic Vector Memory**:
  - Local embedding models & vector similarity search (`sqlite-vss` / Chroma / FAISS).
  - Cross-session associative recall & automatic episodic fact extraction.
  - Local Voice Input/Output (Whisper STT & Kokoro/EdgeTTS audio synthesis).
  - Safe desktop automation & proactive background workflows.

---

### Important notes

* The project diary is permanent. All future development sessions must continue appending chronological entries under their respective dates without deleting historical entries.
