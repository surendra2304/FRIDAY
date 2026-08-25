# FRIDAY — Autonomous Multi-Agent AI Operating System

> **F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou

FRIDAY is a modular, extensible, **Autonomous Multi-Agent AI Operating System** built with a cloud-first, safety-first architecture, clean component separation, a high-throughput **Unified Multi-Provider AI Gateway** (`Groq` -> `Cerebras` -> `Mistral` -> `OpenRouter`), dedicated Gemini Real-Time Voice/Vision isolation, foundational **Multi-Agent Specialist Delegation** (`BaseAgent`, `AgentRegistry`, `TaskDecomposer`, `AgentRouter`), tiered tool execution policies, contextual persistent memory, proactive background monitoring, scientific experimentation framework (`FRIDAY Lab`), futuristic split-view observability, and external AI Universe SDK integration.

---

## 🌟 Architecture & Capabilities (Phases 5–21)

- **Phase 12: Unified Multi-Provider AI Gateway (`FallbackChainLLMProvider`)** `[IMPLEMENTED | REAL-TESTED]`:
  - Intelligent cross-provider failover chain: **Groq (`openai/gpt-oss-120b`) -> Cerebras (`gpt-oss-120b`) -> Mistral (`mistral-large-latest`) -> OpenRouter (`meta-llama/llama-3.3-70b-instruct`)**.
  - Sub-second text reasoning and tool calling with zero local GPU/CPU load.
  - Strict provider isolation: Gemini dedicated strictly for Voice (`gemini-2.0-flash-exp` / `gemini-2.0-flash-realtime-exp`), Vision OCR (`gemini-1.5-flash`), and Semantic Embeddings (`text-embedding-004`).
- **Phase 13: Foundational Multi-Agent Specialist Delegation** `[IMPLEMENTED | REAL-TESTED]`:
  - `BaseAgent` identity & state package: role instructions, preferred models, scoped allowed tools, task-scoped working memory.
  - `AgentRegistry`: pool of registered specialist agents (`researcher`, `system_controller`, `coder`, `general`).
  - `TaskDecomposer`: LLM-driven structured subtask decomposition for complex, multi-step goals into executable JSON workflows.
  - `AgentRouter`: multi-attribute matching and scoring of candidate agents based on capability fit, tool coverage, and historical lab trial metrics.
- **Phase 14: Memory 2.0 Structured Knowledge Base & Compactor** `[IMPLEMENTED | REAL-TESTED]`:
  - 4-layer memory taxonomy: `working` (current turn), `episodic` (past events), `semantic` (facts/knowledge), and `task` (outcomes of workflows).
  - Metadata indexing (`importance`, `recency`, `source`, `confidence`, `privacy`) with FTS5 virtual tables and BM25 bounded retrieval.
  - `MemoryCompactor` using LLM synthesis to consolidate verbose episodic history into permanent semantic knowledge.
- **Phase 16: Productized Computer Control** `[IMPLEMENTED | REAL-TESTED]`:
  - Smart auto-focus typing with top-level window detection and Win32 foreground restoration.
  - Universal application launching (Notepad, Calculator, Word, Excel, Paint, Wordpad, Settings, Web Browsers).
  - Local Tesseract OCR preference with cloud visual screenshot fallback.
- **Phase 17: Proactive FRIDAY (Background Monitoring & Notifications)** `[IMPLEMENTED | REAL-TESTED]`:
  - `WorkflowScheduler`: interval and cron-like task triggering bounded by `DefaultSecureAuthorizer`.
  - `BackgroundMonitorService`: automated background webpage diffing and filesystem state tracking.
  - `NotificationManager`: asynchronous findings queued and announced upon user conversation initiation ("I noticed that X changed while you were away.").
- **Phase 18: FRIDAY Lab (Benchmarking & Dynamic Routing)** `[IMPLEMENTED | REAL-TESTED]`:
  - `ExperimentRunner`: concurrent A/B multi-provider performance evaluation across accuracy, latency ($ms$), success rate, token usage, and failure modes.
  - Persistent `experiments` SQLite metrics storage and comparative CLI benchmark table (`friday --run-lab`).
  - Dynamic `AgentRouter` scoring prioritization leveraging empirical historical stats.
- **Phase 19: Observability & Futuristic Interface** `[IMPLEMENTED | REAL-TESTED]`:
  - Split-view Rich terminal UI: top panel displays transcript/thoughts; bottom panel displays live `Status Panel` (Cognitive Phase, Active Agent, Provider, Active Tool, Latency).
  - `ExecutionTimeline` with circular event buffering and chronological replay (`history`).
  - Strict log routing sending `INFO` and `WARNING` streams to file, keeping terminal quiet and clean.
- **Phase 24: Git & GitHub Automation** `[IMPLEMENTED | REAL-TESTED]`:
  - Safe Git repository tools: `git_status`, `git_commit`, `git_push` with timeout safety and cwd handling.
  - Remote PyGithub integration: `list_github_issues`, `create_github_issue` with API token authentication.
- **Phase 25: System Resource Manager** `[IMPLEMENTED | REAL-TESTED]`:
  - `GetSystemResourcesTool` (`get_system_resources`): real-time CPU %, RAM %, and top memory-consuming processes.
  - `KillProcessTool` (`kill_process`): process termination marked `DANGEROUS` with sensitive authorization gating.
  - Proactive high-CPU sustained alert engine (>90% CPU for >2m prompts the user for automated remediation).
- **Phase 26: Autonomous Self-Coding (The Dev Agent)** `[IMPLEMENTED | REAL-TESTED]`:
  - `DeveloperAgent` specialist agent for autonomous code generation, bug fixing, and branch management.
  - Developer tool suite: `write_code_file` (safe path/directory creation), `run_tests` (automated pytest execution and stderr diagnostics), and `create_git_branch` (sensitive branch creation).
  - `AutonomousDevWorkflow`: End-to-end issue resolution (*"Fix issue #4"*): retrieves GitHub issue, routes to Dev Agent, writes code, runs test suite, and commits/pushes to remote on success.
- **Phase 27: IoT & Smart Home Control** `[IMPLEMENTED | REAL-TESTED]`:
  - `ControlLightTool` (`control_light`): toggle smart lights and adjust brightness (0-100%) via local REST API using `httpx`.
  - `ControlPlugTool` (`control_plug`): toggle smart power plugs and switches by device ID.
  - Built-in offline error resilience and zero-latency voice fast-paths (*"Turn off the lights"*, *"Dim the lights to 50%"*).
- **Phase 28: Proactive Screen Reading (The Watcher)** `[IMPLEMENTED | REAL-TESTED]`:
  - `ScreenWatcherService`: Passive background screen observation combining active window tracking and local Tesseract OCR.
  - Fast Groq/Llama-3.1-8B intent classifier detecting code tracebacks (`offer_debug`) or email composition (`offer_proofread`).
  - Proactive conversational notifications delivered via `NotificationManager` and Gemini Live spoken prompts upon speech pauses.
- **Phase 29: Calendar Schedule & Morning Briefing Workflow** `[IMPLEMENTED | REAL-TESTED]`:
  - `GetTodaysEventsTool` (`get_todays_events`): Parses `.ics` calendar feeds using `icalendar` and `recurring-ical-events` to extract today's meetings.
  - `MorningBriefingWorkflow`: Combines today's calendar schedule with live weather forecasts via web search to generate natural spoken morning briefings (*"Good morning Surendra. You have 3 meetings today. The weather is sunny."*).
  - Proactive 8:00 AM background scheduler hook for automated morning intelligence delivery.
- **Phase 30: Autonomous Web Research, OS Settings, & Email Automation** `[IMPLEMENTED | REAL-TESTED]`:
  - `ResearchAgent`: Specialist agent orchestrating `web_search`, `fetch_webpage_content` (HTML clean-up via BeautifulSoup4), and `synthesize_information` (3-bullet-point LLM summaries) with prompt-injection defense.
  - Windows OS Settings Tools: `toggle_dark_mode` (registry-based theme switching), `toggle_bluetooth` (SENSITIVE radio control), and `toggle_wifi` (SENSITIVE network adapter toggle).
  - `SendEmailTool` (`send_email`, SENSITIVE): SMTP email delivery with STARTTLS and App Password authentication.
  - `EmailDraftingWorkflow`: Intercepts natural speech intents (*"Draft an email to John about the project update"*), drafts executive subject and body text, and prompts the user for sending confirmation.
- **Phase 31: Recursive Self-Improvement (Self-Dev Agent & Architecture Evolution)** `[IMPLEMENTED | REAL-TESTED]`:
  - `ReadOwnCodebaseTool` (`read_own_codebase`): Scans `src/friday/` directory and extracts AST docstrings into a structured architecture map for LLM reasoning.
  - `SelfDevAgent`: Specialist developer agent with deep knowledge of FRIDAY's internal package layers, responsible for authoring, testing, and integrating new capabilities.
  - `SelfImprovementWorkflow`: Autonomous end-to-end self-modification loop (*"FRIDAY, add a tool to click the mouse"*): indexes codebase $\rightarrow$ synthesizes Python code with Groq 70B $\rightarrow$ writes tool file $\rightarrow$ runs automated pytest suite $\rightarrow$ commits and pushes changes to GitHub with strict SENSITIVE authorization gating.
  - Voice Integration: System prompt & Gemini Live session instruction to intercept self-modification voice requests, plan changes, and confirm with the user.

---

## 📊 Capability & Verification Matrix

| Subsystem / Capability | Implementation | Mock Tested | Real Tested | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Recursive Self-Improvement & SelfDevAgent (Phase 31)** | `src/friday/agents/specialists/self_dev_agent.py`, `src/friday/workflows/self_improve_workflow.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Autonomous Web Research Specialist (`ResearchAgent`)** | `src/friday/agents/specialists/research_agent.py`, `src/friday/tools/builtin/web_research.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Windows OS Settings Voice Control (Dark Mode, Bluetooth, Wi-Fi)** | `src/friday/tools/builtin/os_settings.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Calendar Schedule & Morning Briefing Workflow** | `src/friday/tools/builtin/calendar.py`, `src/friday/workflows/briefing_workflow.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Voice Email Drafting & SMTP Delivery (`send_email`)** | `src/friday/tools/builtin/email_tools.py`, `src/friday/workflows/email_workflow.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Autonomous Self-Coding Dev Agent & Workflow (Phase 26)** | `src/friday/agents/specialists/developer_agent.py`, `src/friday/workflows/dev_workflow.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **IoT & Smart Home Control Hub (Phase 27)** | `src/friday/tools/builtin/smart_home.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Proactive Screen Reading - The Watcher (Phase 28)** | `src/friday/vision/screen_watcher.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Git & GitHub Issue Automation (Phase 24)** | `src/friday/tools/builtin/git_tools.py`, `src/friday/tools/builtin/github_tools.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **System Resource Manager & CPU Alerting (Phase 25)** | `src/friday/tools/builtin/system_monitor.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Unified Multi-Provider AI Gateway (Groq->Cerebras->Mistral->OpenRouter)** | `src/friday/llm/factory.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multi-Agent Specialist Delegation (BaseAgent, Registry, Decomposer, Router)** | `src/friday/agents/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Memory 2.0 Knowledge Base & Compactor (4-Layer, BM25, FTS5)** | `src/friday/memory/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Stable Gemini Live Voice Streaming (Server-Side VAD)** | `src/friday/voice/gemini_live_session.py` | ✅ PASS | ✅ PASS | **REAL-TESTED** |
| **Phase 16 Computer Control & Auto-Focus Typing** | `src/friday/tools/builtin/type_text.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Proactive FRIDAY (Scheduler, Monitor, Notifications)** | `src/friday/workflows/`, `src/friday/observability/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **FRIDAY Lab (A/B Benchmarking & Dynamic Routing)** | `src/friday/lab/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Futuristic Split-View UI & Timeline Replay** | `src/friday/cli/main.py`, `src/friday/observability/timeline.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **AI Universe SDK Contract & Orchestrator (Phases 20-21)** | `src/friday/integrations/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **10-Phase Cognitive Intelligence Loop** | `src/friday/agent/cognitive.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multi-Attribute Capability Router** | `src/friday/routing/capability_router.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Unified 15-Category Domain Error Taxonomy** | `src/friday/core/exceptions.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **FridayDoctor System Health Diagnostics** | `src/friday/core/doctor.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Background Tasks & Crash-Recovery Store** | `src/friday/tasks/manager.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Durable Checkpoints & Resumption Engine** | `src/friday/agent/checkpoint.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **HMAC-SHA256 Authorization & Safety Gating** | `src/friday/core/auth.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Zero-Secret Scrubber & Redaction Engine** | `src/friday/security/scrubber.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multimodal Perception & Local Screen OCR** | `src/friday/vision/perception_pipeline.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Persistent SQLite Memory (WAL + ACID + FTS5)**| `src/friday/memory/sqlite.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Cloud-First Gemini Embeddings (`text-embedding-004`)** | `src/friday/memory/embeddings/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.10 or higher (Python 3.11+ recommended)
- `pip` or virtual environment manager

### 2. Setup

```bash
# Clone or navigate to the repository
cd d:/FRIDAY

# Create and activate virtual environment (optional but recommended)
python -m venv .venv
.venv\Scripts\activate  # Windows PowerShell/CMD

# Install dependencies
pip install -e .
```

### 3. Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` to configure your preferred settings:
```ini
# Cloud-first Google Gemini (Free-First & Predictable):
FRIDAY_LLM_PROVIDER=gemini
FRIDAY_LLM_MODEL=gemini-2.5-flash
FRIDAY_GEMINI_API_KEY=your-gemini-api-key-here
FRIDAY_COST_MODE=free_first
FRIDAY_GEMINI_TIMEOUT=60.0
FRIDAY_GEMINI_MAX_RETRIES=3
FRIDAY_GEMINI_BACKOFF_FACTOR=2.0

# Or use mock provider for offline development & testing:
# FRIDAY_LLM_PROVIDER=mock

# Memory backend (sqlite or in_memory):
FRIDAY_MEMORY_BACKEND=sqlite
FRIDAY_MEMORY_DB_PATH=data/friday.db
FRIDAY_MEMORY_MAX_MESSAGES=50
# Optional retention policy in days (None/0 for indefinite):
# FRIDAY_MEMORY_RETENTION_DAYS=30

# Semantic Long-Term Memory (Cloud-First Remote Embeddings):
FRIDAY_EMBEDDING_PROVIDER=gemini
FRIDAY_EMBEDDING_MODEL=text-embedding-004
FRIDAY_EMBEDDING_DIMENSION=768
FRIDAY_EMBEDDING_SIMILARITY_THRESHOLD=0.6

# Or configure OpenAI/Groq/OpenRouter:
# FRIDAY_LLM_PROVIDER=openai
# FRIDAY_LLM_MODEL=gpt-4o-mini
# FRIDAY_LLM_API_KEY=your-api-key-here
# FRIDAY_LLM_BASE_URL=https://api.openai.com/v1
```

> **Memory Layers**: FRIDAY operates a 4-layer memory system:
> 1. **Layer 1: Working Memory** (Sliding in-memory context buffer).
> 2. **Layer 2: Persistent Conversation Memory** (ACID SQLite session isolation).
> 3. **Layer 3: Historical Search** (High-speed SQLite FTS5 full-text indexing with BM25 ranking).
> 4. **Layer 4: Semantic Long-Term Memory** (Cloud-first vector embeddings with cosine similarity and automatic FTS5 fallback). Zero heavy local embedding models or vector databases are run on your laptop.

> **Note on Free-First Operation**: `FRIDAY_COST_MODE=free_first` ensures FRIDAY runs within predictable limits without silently activating paid billing or third-party paid services. Note that cloud provider rate limits and daily quota limits still apply according to your API tier.

### 4. Running FRIDAY

Launch the interactive CLI:
```bash
python -m friday
```

Or run via installed script:
```bash
friday
```

---

## 💻 CLI Commands

While running FRIDAY, you can use the following commands:

- `/new [title]` — Start a new conversation session and switch to it.
- `/conversations` (or `/list`) — List all stored conversation sessions with message counts.
- `/switch <id>` — Switch active session by full ID or prefix.
- `/rename <title>` — Rename the current active conversation.
- `/current` — Display metadata, ID, and message metrics for active conversation.
- `/search <query>` — Search historical messages for keywords across sessions.
- `/backup [path]` — Create a hot local backup copy of the SQLite database.
- `/export [path]` — Export active conversation to a local JSON file.
- `/status` — View current agent status, active provider, model, memory size, and loaded tools.
- `/history` — View the stored conversation history in the active session.
- `/tools` — View registered tools and their safety classifications.
- `/clear` — Clear the messages in the active conversation session.
- `/delete [id]` — Permanently delete a conversation session (requires confirmation).
- `/purge` — Completely wipe all stored conversations and database memory (`CONFIRM PURGE`).
- `/help` — Display available commands.
- `/exit` or `/quit` — Gracefully exit the assistant.

---

## 🧪 Running Tests

Run the complete test suite using `pytest`:

```bash
pytest -v
```

---

## 📖 Documentation & Architecture

For external AI agents and developers seeking to understand the complete project state, architecture, and current status, refer to the **Primary Handoff Document**:
👉 [**docs/FRIDAY_PROJECT_CONTEXT.md**](docs/FRIDAY_PROJECT_CONTEXT.md)

FRIDAY also maintains a permanent engineering diary, architectural decision records (ADR), and development history in:
👉 [**docs/FRIDAY_DIARY.md**](docs/FRIDAY_DIARY.md)

---

## 🗺️ Roadmap Execution Matrix

- [x] **Phase 1-4 — Core Architecture, Basic Reasoning, Safety Authorizer, & SQLite Memory**
- [x] **Phase 5 & 11 — Gemini Live Voice Streaming (Half-Duplex Echo Suppression & Server-Side VAD)**
- [x] **Phase 6-10 — Perception Pipeline, Checkpoints, Task Manager, & Error Taxonomy**
- [x] **Phase 12 — Unified Multi-Provider AI Gateway (`Groq` -> `Cerebras` -> `Mistral` -> `OpenRouter`)**
- [x] **Phase 13 — Multi-Agent Specialist Delegation (`BaseAgent`, `Registry`, `Decomposer`, `Router`)**
- [x] **Phase 14 — Memory 2.0 Structured Knowledge Base & LLM Compactor**
- [x] **Phase 15 — Autonomous Operating System Kernel Integration & Fast-Paths**
- [x] **Phase 16 — Computer Control, Auto-Focus Typing, & Universal App Launching**
- [x] **Phase 17 — Proactive FRIDAY (Background Monitoring, File Watchers, & Notifications)**
- [x] **Phase 18 — FRIDAY Lab (Multi-Provider A/B Benchmarking & Dynamic Routing)**
- [x] **Phase 19 — Observability & Futuristic Interface (Split-View Dashboard & Timeline Replay)**
- [x] **Phases 20 & 21 — AI Universe Integration Preparation (API SDK Contract & Mock Client)**
- [x] **Phase 22 — Hybrid Memory (ChromaDB + SQLite BM25 FTS5 with 60s TTL Caching)**
- [x] **Phase 23 — Active Context Screen Perception & Provider-Agnostic Prompt Sanitization**
- [x] **Phase 24 — Git & GitHub Automation (`git_status`, `git_commit`, `git_push`, `PyGithub` Issues)**
- [x] **Phase 25 — System Resource Manager (`psutil` CPU/RAM Monitoring & Proactive Sustained High CPU Alerting)**
- [x] **Phase 26 — Autonomous Self-Coding Dev Agent (`DeveloperAgent`, `write_code_file`, `run_tests`, `create_git_branch`, `AutonomousDevWorkflow`)**
- [x] **Phase 27 — IoT & Smart Home Control (`ControlLightTool`, `ControlPlugTool`, Local REST Hub Integration)**
- [x] **Phase 28 — Proactive Screen Reading (The Watcher, Local OCR + Fast Groq Intent Classification & Spoken Assistance)**
- [x] **Phase 29 — Calendar Schedule & Morning Briefing Workflow (`GetTodaysEventsTool`, `MorningBriefingWorkflow`, Proactive 8:00 AM Engine)**
- [x] **Phase 30 — Autonomous Productivity Suite (`ResearchAgent`, OS Settings Control, Voice Email Drafting & SMTP Delivery)**
- [x] **Phase 31 — Recursive Self-Improvement (`ReadOwnCodebaseTool`, `SelfDevAgent`, `SelfImprovementWorkflow`, Voice Intent Routing)**
- [x] **Master Roadmap Freeze (All 31 Phases Completed & Verified)**


