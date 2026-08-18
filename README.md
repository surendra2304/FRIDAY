# FRIDAY — Autonomous Personal AI Agent

> **F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou

FRIDAY is a modular, extensible, autonomous personal AI assistant built with a safety-first architecture, clean component separation, pluggable LLM backends, tiered tool execution policies, and contextual memory.

---

## 🌟 Features (v0.1.0)

- **Modular Architecture**: Clean interfaces for LLM providers, tools, and memory.
- **Safety-First Design**: Tools are strictly categorized as `SAFE`, `SENSITIVE`, or `DANGEROUS`.
- **Pluggable LLM Backends**:
  - `Mock Provider`: Instant offline development & testing with zero API cost.
  - `OpenAI-Compatible Provider`: Works with OpenAI, Groq, Ollama, OpenRouter, and local LLMs.
- **Contextual Memory**: Sliding window conversation buffer with token/message bounds.
- **Safe Logging**: Structured logging with automated secret and API key masking.
- **Interactive Terminal REPL**: Full CLI with commands (`/status`, `/history`, `/tools`, `/clear`, `/exit`).
- **Comprehensive Project Diary**: Permanent source of truth at [`docs/FRIDAY_DIARY.md`](docs/FRIDAY_DIARY.md).

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
# Use mock provider for instant offline use:
FRIDAY_LLM_PROVIDER=mock

# Or configure OpenAI/Ollama/Groq:
# FRIDAY_LLM_PROVIDER=openai
# FRIDAY_LLM_MODEL=gpt-4o-mini
# FRIDAY_LLM_API_KEY=your-api-key-here
# FRIDAY_LLM_BASE_URL=https://api.openai.com/v1
```

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

- `/status` — View current agent status, active provider, model, memory size, and loaded tools.
- `/history` — View the stored conversation history.
- `/tools` — View registered tools and their safety classifications.
- `/clear` — Clear the conversation memory.
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

- [x] **V0.1 — Core Architecture & Foundation** *(Current)*
- [ ] **V0.2 — Basic Agent & Streaming**
- [ ] **V0.3 — Tool System Expansion & Confirmation Gating**
- [ ] **V0.4 — Persistent SQLite & Vector Memory**
- [ ] **V0.5 — Local Voice Interface (Whisper & Kokoro/EdgeTTS)**
- [ ] **V0.6 — Safe Computer Control & Desktop Automation**
- [ ] **V0.7 — Autonomous Workflows & Proactive Actions**
- [ ] **V1.0 — FRIDAY Personal AI**
