# FRIDAY — Autonomous Multi-Agent AI Operating System

[![CI Pipeline](https://github.com/surendra2304/FRIDAY/actions/workflows/ci.yml/badge.svg)](https://github.com/surendra2304/FRIDAY/actions/workflows/ci.yml)

> **F**ully **R**esponsive **I**ntelligent **D**igital **A**ssistant for **Y**ou

FRIDAY is a modular, extensible, **Autonomous Multi-Agent AI Operating System** built with a cloud-first, safety-first architecture, clean component separation, a high-throughput **Unified Multi-Provider AI Gateway** (`Groq` -> `Mistral` -> `OpenRouter` -> `AI Universe`), dedicated Gemini Real-Time Voice/Vision isolation, foundational **Multi-Agent Specialist Delegation** (`BaseAgent`, `AgentRegistry`, `TaskDecomposer`, `AgentRouter`), tiered tool execution policies, contextual persistent memory, proactive background monitoring, scientific experimentation framework (`FRIDAY Lab`), futuristic split-view observability, and external AI Universe SDK integration.

---

## 🌟 Core System Capabilities

### 🎙️ 1. Voice & Real-Time Perception
- **Full-Duplex Voice Engine (`GeminiLiveSession`)**: Continuous bidirectional audio streaming via Google Gemini Live API with automatic multi-key credential pool rotation (`GeminiCredentialPool`).
- **Server-Side Voice Activity Detection (VAD)**: Turn-taking and natural barge-in driven directly by server VAD, eliminating mid-sentence audio cut-offs.
- **Multimodal Screen Perception**: High-speed Windows GDI frame grabbing with SHA-256 caching and local Tesseract OCR preference to avoid unnecessary cloud roundtrips.
- **The Screen Watcher (`ScreenWatcherService`)**: Background screen observer identifying error tracebacks or email drafts to offer proactive, contextual assistance.
- **Voice Biometrics (`VoiceProfileManager`)**: Speaker verification engine using 256-dimensional neural voice embeddings to verify authorized users.

### 🧠 2. Multi-Agent Core & Cognitive Loop
- **Specialist Agent Delegation**: Specialized agents (`DeveloperAgent`, `ResearchAgent`, `SelfDevAgent`, `SystemControllerAgent`, `GeneralAgent`) configured with dedicated tools, instructions, and scoped working memory.
- **Autonomous Think Loop**: Inner monologue scratchpad (`<thought>` tags) forcing pre-action reasoning ("What is my goal? What tool do I need? What do I expect?") before executing commands.
- **Cognitive Self-Correction**: 3-retry diagnostic loop feeding tool execution errors back into the LLM context to dynamically revise plans instead of aborting.
- **Trace-Based Learning (`TraceAnalyzer`)**: Execution trace database logging goals, tools, models, latency, and success rates. Dynamically boosts fast, high-success tool/provider paths (< 2s) and de-prioritizes failing providers.
- **10-Phase Cognitive Engine**: Structured loop (`UNDERSTAND` ➔ `CLARIFY` ➔ `PLAN` ➔ `CHECK` ➔ `AUTHORIZE` ➔ `EXECUTE` ➔ `OBSERVE` ➔ `VERIFY` ➔ `LEARN` ➔ `COMPLETE`).

### ⚡ 3. Skills System & Persistent Operators
- **Reusable Skills (`BaseSkill`, `SkillRegistry`)**: Tool macros grouping multi-step actions and specialized prompts with strict declared `required_capabilities` (e.g. `["shell_exec", "file_read", "network_access"]`).
- **Capability Gating**: Security authorizer evaluates required capabilities against active environment policies before execution.
- **Persistent Event-Driven Operators (`BaseOperator`, `OperatorManager`)**: Background state machines triggered by filesystem changes (`watchdog`), process events (`psutil`), conditional thresholds, or intervals.
- **Operator Chaining (`op1 | op2`)**: Pipeline outputs from one operator directly into subsequent operator triggers.

### 🖥️ 4. Computer Control & Device Abstractions
- **Universal Device Control Abstraction (`BaseDeviceController`)**: Platform-agnostic interface (`open_app`, `click`, `type_text`, `screenshot`, `read_screen_text`).
- **Windows Device Controller (`WindowsDeviceController`)**: Native Win32 UI Automation, App Paths resolution, smart auto-focus keyboard typing, volume control (`pycaw`), and power management.
- **Android Controller Stub (`AndroidDeviceController`)**: Architecture scaffolding for mobile automation via ADB (Android Debug Bridge).
- **Active Device Resolution**: Dynamic factory `get_device_controller()` driven by `FRIDAY_ACTIVE_DEVICE` configuration.

### 🔄 5. Autonomous Workflows
- **Recursive Self-Improvement (`SelfImprovementWorkflow`)**: Scans codebase AST ➔ synthesizes new tools ➔ writes code ➔ runs unit tests ➔ commits and pushes to GitHub with explicit terminal authorization.
- **Autonomous Dev Workflow (`AutonomousDevWorkflow`)**: Pulls remote GitHub issues, implements code solutions via `DeveloperAgent`, verifies with pytest, and creates pull requests.
- **Morning Briefing Workflow (`MorningBriefingWorkflow`)**: Synthesizes `.ics` calendar schedules and live weather into spoken morning briefings.
- **Voice Email Workflow (`EmailDraftingWorkflow`)**: Composes professional emails from voice commands and securely delivers via SMTP with STARTTLS.
- **Smart Home Integration**: Controls IoT lights, plugs, and switches via local REST APIs.

### 📈 7. Stratex Algorithmic Trading Platform & Advisory Supervision (Binance Futures Testnet)
- **Direct Stratex <-> Inference Link**: The cloud-hosted trading engine (`http://localhost:8000`) queries Inference directly on a schedule via `/v1/trading/consult`, logging all advice to `advisory_log.jsonl`.
- **FRIDAY as Supervisor (`AdvisorySupervisorSkill`)**: FRIDAY monitors the bot, inspects AI advisories, detects contested proposals (`verdict=REJECT` + `confidence > 0.7`), explains decisions in plain language, and generates trading morning briefings.
- **Immutable Command Precedence**:
  $$\text{Safety Gates (Trading Bot)} > \text{FRIDAY Commands (Supervisor)} > \text{AI-Universe Recommendations (Advisor)}$$
  FRIDAY commands can override AI advisories, but can **never** bypass or weaken the bot's hardcoded safety gates. All panic commands invoke the trading bot's authoritative kill-switch (`POST /api/panic`).
- **Persistent Advisory Watchdog (`AdvisoryWatchdogOperator`)**: Background operator polling `/api/advisory/recent` every 15 minutes, alerting on contested advisories, AI-Universe outages, or bot disconnects, tagged with `TrustLevel.UNTRUSTED_EXTERNAL` in memory.
- **Supervision Endpoints**:
  - `GET /api/status`: Queries live equity, unrealized/realized PnL, profit factor, win rate, and open positions.
  - `GET /api/advisory/recent?limit=N`: Retrieves append-only advisory decisions and verdict logs.
  - `GET /api/advisory/state`: Inspects current AI parameter overlay and AI-Universe health.
  - `POST /api/panic`: Emergency kill-switch blocking new orders (SENSITIVE/DANGEROUS authorization gated).


---

## 📊 Capability & Verification Matrix

| Subsystem / Capability | Module Path | Test Status | Operational State |
| :--- | :--- | :---: | :---: |
| **Skills System & Capability Gating** | `src/friday/skills/` | ✅ PASS | **PRODUCTION** |
| **Persistent Event-Driven Operators** | `src/friday/operators/` | ✅ PASS | **PRODUCTION** |
| **Trace-Based Learning & Dynamic Routing** | `src/friday/learning/` | ✅ PASS | **PRODUCTION** |
| **Device Control Abstractions (Windows / Android)** | `src/friday/devices/` | ✅ PASS | **PRODUCTION** |
| **Recursive Self-Improvement & SelfDevAgent** | `src/friday/workflows/self_improve_workflow.py` | ✅ PASS | **PRODUCTION** |
| **Autonomous Web Research Specialist (`ResearchAgent`)** | `src/friday/agents/specialists/research_agent.py` | ✅ PASS | **PRODUCTION** |
| **Autonomous Self-Coding Dev Agent (`DeveloperAgent`)** | `src/friday/workflows/dev_workflow.py` | ✅ PASS | **PRODUCTION** |
| **Unified Multi-Provider AI Gateway (Groq->Mistral->OpenRouter->AI Universe)** | `src/friday/llm/factory.py` | ✅ PASS | **PRODUCTION** |
| **Multi-Agent Specialist Delegation (BaseAgent, Registry, Decomposer, Router)** | `src/friday/agents/` | ✅ PASS | **PRODUCTION** |
| **Memory 2.0 Knowledge Base & Compactor (4-Layer, BM25, FTS5)** | `src/friday/memory/` | ✅ PASS | **PRODUCTION** |
| **Full-Duplex Gemini Live Voice Streaming (Server-Side VAD)** | `src/friday/voice/gemini_live_session.py` | ✅ PASS | **PRODUCTION** |
| **Windows Computer Control & Auto-Focus Typing** | `src/friday/tools/builtin/type_text.py` | ✅ PASS | **PRODUCTION** |
| **Proactive Screen Reading (The Watcher)** | `src/friday/vision/screen_watcher.py` | ✅ PASS | **PRODUCTION** |
| **Calendar Schedule & Morning Briefing Workflow** | `src/friday/workflows/briefing_workflow.py` | ✅ PASS | **PRODUCTION** |
| **Voice Email Drafting & SMTP Delivery (`send_email`)** | `src/friday/workflows/email_workflow.py` | ✅ PASS | **PRODUCTION** |
| **IoT & Smart Home Control Hub** | `src/friday/tools/builtin/smart_home.py` | ✅ PASS | **PRODUCTION** |
| **Git & GitHub Issue Automation** | `src/friday/tools/builtin/git_tools.py` | ✅ PASS | **PRODUCTION** |
| **System Resource Manager & CPU Alerting** | `src/friday/tools/builtin/system_monitor.py` | ✅ PASS | **PRODUCTION** |
| **FRIDAY Lab (A/B Benchmarking & Dynamic Routing)** | `src/friday/lab/` | ✅ PASS | **PRODUCTION** |
| **Futuristic Split-View UI & Timeline Replay** | `src/friday/cli/main.py`, `src/friday/observability/timeline.py` | ✅ PASS | **PRODUCTION** |
| **AI Universe SDK Contract & Orchestrator** | `src/friday/integrations/` | ✅ PASS | **PRODUCTION** |
| **10-Phase Cognitive Intelligence Loop** | `src/friday/agent/cognitive.py` | ✅ PASS | **PRODUCTION** |
| **Multi-Attribute Capability Router** | `src/friday/routing/capability_router.py` | ✅ PASS | **PRODUCTION** |
| **Unified 15-Category Domain Error Taxonomy** | `src/friday/core/exceptions.py` | ✅ PASS | **PRODUCTION** |
| **FridayDoctor System Health Diagnostics** | `src/friday/core/doctor.py` | ✅ PASS | **PRODUCTION** |
| **HMAC-SHA256 Authorization & Safety Gating** | `src/friday/core/auth.py` | ✅ PASS | **PRODUCTION** |
| **Trading Bot Operator (Binance Futures Testnet)** | `src/friday/skills/trading_bot_operator.py` | ✅ PASS | **PRODUCTION** |

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python**: 3.10+ (Recommended: Python 3.11)
- **OS**: Windows 10/11 (with optional Android/Remote device controllers)
- **API Keys**:
  - `FRIDAY_GEMINI_API_KEY`: For real-time voice, vision OCR, and semantic embeddings.
  - `FRIDAY_GROQ_API_KEY`: For sub-second primary text reasoning and cognitive loop execution.
  - `FRIDAY_MISTRAL_API_KEY` & `FRIDAY_OPENROUTER_API_KEY`: For high-availability failover.

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/surendra2304/FRIDAY.git
cd FRIDAY

# Install dependencies
pip install -e .

# Configure environment
copy .env.example .env
```

### 3. Launch Modes
```powershell
# Interactive text terminal mode (with Split-View UI)
friday

# Full-duplex real-time voice mode (Gemini Live with Server-Side VAD)
friday --voice

# System health inspection & diagnostics
friday --doctor

# Run multi-provider performance benchmark laboratory
friday --run-lab
```

---

## 🛡️ Security & Safety Model
1. **Tiered Tool Execution**:
   - `SAFE`: Non-destructive actions (e.g. read file, search web, get time) execute immediately.
   - `SENSITIVE`: Actions modifying data or system state (e.g. write file, send email, launch app) require capability verification.
   - `DANGEROUS`: High-risk actions (e.g. delete file, kill process, execute arbitrary shell) require signed cryptographic authorization.
2. **Zero-Secret Scrubber (`SecretScrubber`)**: Automatically redacts API keys, tokens, and credentials from all exception strings, audit logs, and external payloads.
3. **Memory Trust Boundaries**: Untrusted external inputs are tagged `TrustLevel.UNTRUSTED_EXTERNAL` to prevent prompt injection attacks into long-term vector memory.
