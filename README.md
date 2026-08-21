# FRIDAY — Autonomous Personal AI Agent

> **F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou

FRIDAY is a modular, extensible, autonomous personal AI assistant built with a cloud-first, safety-first architecture, clean component separation, pluggable LLM backends, tiered tool execution policies, contextual persistent memory, and sub-second real-time Gemini Live voice streaming.

---

## 🌟 Real-Time Voice Architecture (Phase 5 Complete)

- **Full-Duplex Gemini Live Streaming (`gemini-3.1-flash-live-preview`)** `[IMPLEMENTED | REAL-TESTED]`:
  - Bidirectional WebSocket session handling live audio input and output turns simultaneously.
  - Non-blocking 16 kHz 16-bit linear PCM microphone capture streaming in 40ms frames.
  - Immediate 24 kHz 16-bit linear PCM speaker playback starting on the first response chunk without waiting for turn completion.
  - Dual-layer instant barge-in: local RMS energy detection (**1.935 ms** speaker queue flush) and server-side interruption handling.
  - Server-side VAD with automatic speech activity detection.
  - Zero local AI model overhead: 0% GPU, < 1% CPU, < 5 MB RAM (Strictly cloud-first: no Ollama, no local Whisper, no local TTS).
- **Unified Single-Brain Intelligence Layer** `[IMPLEMENTED | REAL-TESTED]`:
  - Voice directly dispatches functions through `ToolRegistry` and commits turns to `SQLiteConversationMemory`.
  - Dynamic tool schema translation to Gemini Live function declarations.
  - Tiered safety policies (`SAFE`, `SENSITIVE`, `DANGEROUS`) and authorizer gating fully enforced in voice.
  - Bidirectional memory sync: text saved -> voice recalled; voice saved -> text recalled.

---

## 📊 Capability & Verification Matrix

| Subsystem / Capability | Implementation | Mock Tested | Real Tested | Status |
| :--- | :--- | :---: | :---: | :---: |
| **10-Phase Cognitive Intelligence Loop** | `src/friday/agent/cognitive.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multi-Attribute Capability Router** | `src/friday/routing/capability_router.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Unified 15-Category Domain Error Taxonomy** | `src/friday/core/exceptions.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **FridayDoctor System Health Diagnostics** | `src/friday/core/doctor.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Background Tasks & Crash-Recovery Store** | `src/friday/tasks/manager.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Durable Checkpoints & Resumption Engine** | `src/friday/agent/checkpoint.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **HMAC-SHA256 Authorization & Safety Gating** | `src/friday/core/auth.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Zero-Secret Scrubber & Redaction Engine** | `src/friday/security/scrubber.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Google Gemini Intelligence Provider (`gemini-3.7-flash`)** | `src/friday/llm/gemini_provider.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **OpenAI / Non-Gemini Multimodal Provider** | `src/friday/vision/openai_vision.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Multimodal Perception & Screen Caching** | `src/friday/vision/perception_pipeline.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Windows DPI Virtual Screen Capture** | `src/friday/vision/windows_screen.py` | ✅ PASS | ⚠️ BLOCKED (Headless) | **IMPLEMENTED** |
| **Real Streaming Microphone Capture (16kHz)** | `src/friday/voice/audio_io.py` | ✅ PASS | ✅ REAL PASS (17 devs) | **REAL-TESTED** |
| **Immediate Streaming Speaker (24kHz)** | `src/friday/voice/audio_io.py` | ✅ PASS | ✅ REAL PASS (Dev 3) | **REAL-TESTED** |
| **Gemini Live WebSocket Voice (`gemini-3.1-flash-live-preview`)** | `src/friday/voice/gemini_live_session.py` | ✅ PASS | ✅ PASS | **REAL-TESTED** |
| **Persistent SQLite Memory (WAL + ACID + FTS5)**| `src/friday/memory/sqlite.py` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |
| **Cloud-First Gemini Embeddings (`gemini-embedding-2`)** | `src/friday/memory/embeddings/` | ✅ PASS | ✅ PASS | **IMPLEMENTED** |

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

## 📖 Architecture & Diary

FRIDAY maintains a permanent engineering diary, architectural decision records (ADR), and development history in:
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
