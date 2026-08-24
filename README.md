# FRIDAY — Autonomous Multi-Agent AI Operating System

> **F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou

FRIDAY is a modular, extensible, **Autonomous Multi-Agent AI Operating System** built with a cloud-first, safety-first architecture, clean component separation, a high-throughput **Unified Multi-Provider AI Gateway** (`Groq` -> `Cerebras` -> `Mistral` -> `OpenRouter`), dedicated Gemini Real-Time Voice/Vision isolation, foundational **Multi-Agent Specialist Delegation** (`BaseAgent`, `AgentRegistry`, `TaskDecomposer`, `AgentRouter`), tiered tool execution policies, contextual persistent memory, proactive system health telemetry, and sub-second real-time Gemini Live voice streaming.

---

## 🌟 Architecture & Capabilities (Phases 5, 11, 12, 13, 16)

- **Phase 12: Unified Multi-Provider AI Gateway (`FallbackChainLLMProvider`)** `[IMPLEMENTED | REAL-TESTED]`:
  - Intelligent cross-provider failover chain: **Groq (`openai/gpt-oss-120b`) -> Cerebras (`gpt-oss-120b`) -> Mistral (`mistral-large-latest`) -> OpenRouter (`meta-llama/llama-3.3-70b-instruct`)**.
  - Sub-second text reasoning and tool calling with zero local GPU/CPU load.
  - Strict provider isolation: Gemini dedicated strictly for Voice (`gemini-2.0-flash-exp` / `gemini-2.0-flash-realtime-exp`), Vision OCR (`gemini-1.5-flash`), and Semantic Embeddings (`text-embedding-004`).
- **Phase 13: Foundational Multi-Agent Specialist Delegation** `[IMPLEMENTED | REAL-TESTED]`:
  - `BaseAgent` identity & state package: role instructions, preferred models, scoped allowed tools, task-scoped working memory.
  - `AgentRegistry`: pool of registered specialist agents (`researcher`, `system_controller`, `coder`, `general`).
  - `TaskDecomposer`: LLM-driven structured subtask decomposition for complex, multi-step goals into executable JSON workflows.
  - `AgentRouter`: multi-attribute matching and scoring of candidate agents based on capability fit and tool coverage.
- **Phase 5 & 11: Stable Low-Latency Voice Streaming Pipeline** `[IMPLEMENTED | REAL-TESTED]`:
  - Half-duplex echo suppression with dynamic mic unmuting and configurable speaker timeout buffer (up to 60s).
  - 100% Server-Side Google VAD for natural interruption handling without client-side chopping.
  - Voice biometrics security gating (`SpeakerVerificationEngine`) with lazy imports for zero startup CPU strain.
- **Phase 16: Productized Computer Control** `[IMPLEMENTED | REAL-TESTED]`:
  - Smart auto-focus typing with top-level window detection and Win32 foreground restoration.
  - Universal application launching (Notepad, Calculator, Word, Excel, Paint, Wordpad, Settings, Web Browsers).
  - Local Tesseract OCR preference with cloud visual screenshot fallback.
  - Strict prompt sequencing ensuring applications are fully initialized before text entry.

---

## 📊 Capability & Verification Matrix

| Subsystem / Capability | Implementation | Mock Tested | Real Tested | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Unified AI Provider Gateway (Groq->Cerebras->Mistral->OpenRouter)** | `src/friday/llm/factory.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multi-Agent Specialist Delegation (BaseAgent, Registry, Decomposer, Router)** | `src/friday/agents/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Stable Gemini Live Voice Streaming (Server-Side VAD)** | `src/friday/voice/gemini_live_session.py` | ✅ PASS | ✅ PASS | **REAL-TESTED** |
| **Phase 16 Computer Control & Auto-Focus Typing** | `src/friday/tools/builtin/type_text.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Universal App Launcher & Windows Automation** | `src/friday/tools/builtin/open_application.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
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

## 🗺️ Roadmap

- [x] **V0.1 — Core Architecture & Foundation**
- [x] **V0.2 — Basic Agent Reasoning**
- [x] **V0.3 — Tool System Expansion & Interactive Confirmation Gating**
- [x] **V0.4 — Persistent SQLite Memory & Multi-Conversation Management** *(Current)*
- [ ] **V0.4.5 — Long-Term Semantic Vector Memory**
- [ ] **V0.5 — Local Voice Interface (Whisper & Kokoro/EdgeTTS)**
- [ ] **V0.6 — Safe Computer Control & Desktop Automation**
- [ ] **V0.7 — Autonomous Workflows & Proactive Actions**
- [ ] **V1.0 — FRIDAY Personal AI**
