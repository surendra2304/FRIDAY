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
- **Self-development (`self_develop`)**: The registered tool plans a missing capability, synthesizes and smoke-tests a candidate, then reports whether it reached review/owner authority; it does not claim installation before the gate completes. The legacy `SelfImprovementWorkflow` is not wired into the live tool path and is not a supported production workflow.
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

> **Operational truth:** This table is a static repository capability inventory. Its historical `PASS` and `PRODUCTION` labels are not current live-deployment evidence. `/api/agents/supervision` reports background peer endpoint reachability only; HTTP 200 does not prove task execution, memory persistence, or event delivery. Use dated, reproducible workflow receipts for those claims.

| Subsystem / Capability | Module Path | Test Status | Operational State |
| :--- | :--- | :---: | :---: |
| **Skills System & Capability Gating** | `src/friday/skills/` | ✅ PASS | **PRODUCTION** |
| **Persistent Event-Driven Operators** | `src/friday/operators/` | ✅ PASS | **PRODUCTION** |
| **Trace-Based Learning & Dynamic Routing** | `src/friday/learning/` | ✅ PASS | **PRODUCTION** |
| **Device Control Abstractions (Windows / Android)** | `src/friday/devices/` | ✅ PASS | **PRODUCTION** |
| **Self-Development Tools (`self_develop`, `self_repair`)** | `src/friday/tools/builtin/self_development.py` | ✅ PASS | **PRODUCTION (tools)** — `SelfImprovementWorkflow` itself is **CONFIGURED-BUT-UNVERIFIED**: it is not wired into a live tool path, and its Phase-31 test exercises mocks (BUG-003 remainder) |
| **Autonomous Web Research Specialist (`ResearchAgent`)** | `src/friday/agents/specialists/research_agent.py` | ✅ PASS | **PRODUCTION** |
| **Autonomous Self-Coding Dev Agent (`DeveloperAgent`)** | `src/friday/workflows/dev_workflow.py` | ✅ PASS | **CONFIGURED-BUT-UNVERIFIED** — the pipeline is tested, but no live run has pulled a real GitHub issue or opened a real PR from this checkout |
| **Unified Multi-Provider AI Gateway (Groq->Mistral->OpenRouter->AI Universe)** | `src/friday/llm/factory.py` | ✅ PASS | **PRODUCTION** |
| **Multi-Agent Specialist Delegation (BaseAgent, Registry, Decomposer, Router)** | `src/friday/agents/` | ✅ PASS | **REAL in-process** — the eight *cloud* peers are **CONFIGURED-BUT-UNVERIFIED**: `ask_*` still reads health endpoints rather than dispatching tasks (BUG-004) |
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
| **Standing-Mandate Autonomy & Gated Self-Repair** | `src/friday/autonomous/`, `src/friday/cognition/` | ✅ PASS | **PRODUCTION (proven on a real repo, unattended; rollback exercised)** |
| **Cognition Mesh / Minds / Memory Bridge** | `src/friday/cognition/mesh.py`, `mind.py`, `memory_bridge.py` | ✅ PASS | **REAL in-process**; live cloud peer calls **CONFIGURED-BUT-UNVERIFIED** (no egress here) |
| **Peer Task Delegation** | `src/friday/ecosystem/fleet_client.py` | ⚠️ PARTIAL | **CONFIGURED-BUT-UNVERIFIED** — `ask_*` currently reads health endpoints (BUG-004) |

### Autonomous Self-Repair & Cognition (2026-10-05)

The autonomy layer is real and was proven on a real repository, unattended:

- **Standing autonomy mandates** — `python -m friday --grant-autonomy [--autonomy-hours N]
  [--autonomy-scope …] [--autonomy-paths …]` issues a signed, expiring, scoped, revocable
  mandate; `--autonomy-status` reports `ACTIVE` / `AWAITING_MANDATE` / `NO_KEY`, and
  `--revoke-autonomy` withdraws it. Nothing is applied without one.
- **The repair loop** — detect → diagnose → prove in a sandbox copy → signed review →
  gate → apply → verify on the real tree, with **automatic rollback** if the real tree
  rejects a sandbox-proven patch. `python -m friday --reflex-run [imports,tests,fleet,…]`
  runs one pass now; the API service runs the same brain on an interval.
- **Owner-only approval** — approval authority is a positively identified owner
  (`FRIDAY_USER_NAME`, or `owner`); no agent, and no name nobody configured, can approve.
- **Evidence honesty** — an unreachable peer is `UNREACHABLE`, never "degraded"; a
  non-answer is not counted as a response; failure is never formatted as success.

What has been proven, with commands and output, is in
`docs/reports/phase5-autonomy-proof-2026-10-05.md`. What has **not** been proven —
live cloud peers, live LLM providers, semantic recall, peer *task delegation* — is
listed there as **CONFIGURED-BUT-UNVERIFIED** with the reason. Open defects are in
`docs/FRIDAY_KNOWN_ISSUES.md`.

#### LIVE-DEPLOYMENT CHECK (do this on a machine with internet)

```bash
python -m pytest tests/test_extreme_pressure.py -q      # hostile conditions, expect 23 passed
export FRIDAY_REFLEX_REPO=/path/to/a/real/repo
export FRIDAY_SELF_REPAIR_REVIEW_KEY=<review-key>
export FRIDAY_AUTONOMY_KEY=<owner-key>                  # never commit this
python -m friday --reflex-run tests                     # expect NO changes, AWAITING_MANDATE
python -m friday --grant-autonomy --autonomy-hours 1 --autonomy-scope source_repair
python -m friday --reflex-run tests                     # expect RESOLVED or ROLLED_BACK, never a silent edit
python -m friday --reflex-run fleet                     # expect honest per-peer results, not eight successes
python -m friday --revoke-autonomy all
```

### Cloud Fleet Supervision

The cloud FRIDAY API starts a background peer reachability poll while its process is running. By default it refreshes every five minutes; set `FRIDAY_FLEET_SUPERVISION_INTERVAL_SECONDS` to change the interval (minimum 30 seconds). `GET /api/agents/supervision` reports the latest snapshot age, per-agent HTTP status, and whether all eight configured peer endpoints responded. This snapshot is held in process memory and resets when the service restarts. It does not run tasks for peers, verify Memora writes, deliver IntelX events, or alert Surendra. Those capabilities are not implemented by this monitor.

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

# Install the core assistant (voice biometrics and Qt desktop UI stay optional)
pip install -e .

# Optional PyQt6 desktop companion and global hotkey
pip install -e ".[desktop]"
# Linux desktop sessions may also need the host libGL.so.1 / Qt runtime

# Optional neural voice-biometric profiles (Linux may need Python headers for webrtcvad)
pip install -e ".[voice-bio]"

# Configure environment
copy .env.example .env
```

### 3. Launch Modes
```powershell
# Interactive text terminal mode (with Split-View UI)
friday

# Full-duplex real-time voice mode (Gemini Live with local laptop tools)
friday --voice

# System health inspection & diagnostics
friday --doctor

# Run multi-provider performance benchmark laboratory
friday --run-lab

# Optional PyQt6 desktop companion (install the desktop extra first)
friday --desktop
# or
friday-desktop
```

`--voice` and `--local-voice` start FRIDAY's microphone and speaker pipeline with Gemini Live for speech recognition and conversation; audio is sent to the configured Gemini provider and provider quota/terms apply. Laptop tools execute on the local machine through FRIDAY's authorization path. Use `Ctrl+C` to stop voice mode.

---

## 🛡️ Security & Safety Model
1. **Tiered Tool Execution**:
   - `SAFE`: Non-destructive actions (e.g. read file, search web, get time) execute immediately.
   - `SENSITIVE`: Actions modifying data or system state (e.g. write file, send email, launch app) require capability verification.
   - `DANGEROUS`: High-risk actions (e.g. delete file, kill process, execute arbitrary shell) require signed cryptographic authorization.
2. **Zero-Secret Scrubber (`SecretScrubber`)**: Automatically redacts API keys, tokens, and credentials from all exception strings, audit logs, and external payloads.
3. **Memory Trust Boundaries**: Untrusted external inputs are tagged `TrustLevel.UNTRUSTED_EXTERNAL` to prevent prompt injection attacks into long-term vector memory.
