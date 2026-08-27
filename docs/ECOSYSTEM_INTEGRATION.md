# 🌐 FRIDAY Unified Ecosystem Master Control & FORGE Integration Manual

This document details the architecture, cryptographic authentication protocols, cross-system orchestration, and voice controls connecting the **Algorithmic Trading Bot**, **AI-Universe Core**, and **FORGE (Autonomous Software Engineering Engine)** under the **FRIDAY Operating System**.

---

## 🏛️ Ecosystem Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Voice & natural language command interface            │
│     • Biometric-authenticated autonomy governance           │
└──────────────────────────────▲──────────────────────────────┘
                               │ Voice Commands / Signed Decisions
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Master Ecosystem Tier (Level 50)           │
├──────────────────────────────┬──────────────────────────────┤
│  EcosystemOrchestrator       │  EcosystemMasterDashboard    │
│  • 30s Health Monitoring     │  • Tri-System Status Grid    │
│  • Cross-System Routing      │  • Color-Coded Activity Feed │
│  • Priority Queuing          │  • Emergency Master Controls │
├──────────────────────────────┼──────────────────────────────┤
│  ForgeManagerSkill           │  ForgeMonitorOperator        │
│  • Software Task Assignment  │  • 60s Build Pipeline Watch  │
│  • Artifact & Output Review  │  • Task Completion Alerts    │
│  • Non-Blocking Background   │  • Failure & Delay Vigilance │
├──────────────────────────────┼──────────────────────────────┤
│  VoiceEcosystemSkill         │  ForgeAuthClient             │
│  • Trading Voice Commands    │  • HMAC-SHA256 Signing       │
│  • FORGE Build Voice Control │  • Token-Bucket Rate Limiter │
│  • AI-Universe Consultation  │  • Schema Validation Engine  │
└──────┬───────────────────────┼───────────────────────┬──────┘
       │ REST / Signed API     │ LLM Consultations     │ HMAC Signed
       ▼                       ▼                       ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Algorithmic     │  │  AI-Universe     │  │  FORGE Engine    │
│  Trading Bot     │  │  Consultant      │  │  Autonomous SWE  │
│  (Real Capital)  │  │  (Intelligence)  │  │  (Build Pipelines│
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Invariant & Boundary Principles:
1. **FRIDAY Hub Topology**: FRIDAY is the **ONLY** system that communicates with all others. The Trading Bot and FORGE do **NOT** communicate directly.
2. **Memory Isolation**: All external telemetry, tasks, and artifacts received from FORGE are tagged `TrustLevel.UNTRUSTED_EXTERNAL`.
3. **Non-Blocking Background Tasks**: Software engineering jobs dispatched to FORGE run asynchronously in the background.
4. **Safety Precedence**: `Safety Gates (100) > FRIDAY Master Supervisor (50) > AI Recommendations / FORGE Requests (10)`.

---

## 🔐 FORGE Cryptographic Authentication & Endpoints

| Endpoint | Method | Purpose | Authentication |
| :--- | :---: | :--- | :---: |
| `/api/v1/forge/build` | `POST` | Dispatches new autonomous software task. | `HMAC-SHA256` |
| `/api/v1/forge/tasks/{task_id}` | `GET` | Queries execution status, progress, artifacts. | `HMAC-SHA256` |
| `/api/v1/forge/tasks/{task_id}/cancel` | `POST` | Cancels running build pipeline (`SENSITIVE`). | `HMAC-SHA256` |
| `/api/v1/forge/health` | `GET` | Health and queue capacity telemetry. | `Bearer Key` |

### HMAC Signature Format:
$$\text{Signature} = \text{HMAC-SHA256}\Big(K_{\text{FORGE}}, \text{Timestamp} + \text{Method} + \text{Path} + \text{JSON\_Body}\Big)$$
- Headers included: `X-FRIDAY-Client-Id`, `X-FRIDAY-Timestamp`, `X-FRIDAY-Signature`, `Authorization`.
- Rate Limiting: Token-bucket algorithm strictly enforcing a maximum of **10 requests / minute**.

---

## 🎙️ Unified Voice Command Catalog

### 1. Trading Bot Subsystem
- `"Trading status"` $\to$ Reports venue connections (Binance/Bybit/OKX), active capital, positions, and daily P&L.
- `"Portfolio risk"` $\to$ Reports aggregate leverage (0.85x), daily loss headroom, and concentration metrics.
- `"Emergency stop trading"` $\to$ Dispatches `/api/panic` kill switch neutralizing all open positions.

### 2. FORGE Software Engineering Subsystem
- `"Build [software description]"` $\to$ Dispatches asynchronous task to FORGE (`POST /api/v1/forge/build`).
- `"FORGE status"` $\to$ Reports active vs completed builds and overall pipeline health.
- `"Check task [task_id]"` $\to$ Reports progress %, test coverage %, and verification status.
- `"Show FORGE artifacts"` $\to$ Lists recent software source files and delivery packages.
- `"Cancel FORGE task [task_id]"` $\to$ Cancels running build pipeline (`SENSITIVE` capability verified).

### 3. AI-Universe Subsystem
- `"AI Universe status"` $\to$ Reports consultant latency, multi-agent debate status, and model confidence.
- `"Trading analysis"` $\to$ Synthesizes directional forecasts and risk drivers for held assets.
- `"Consult about [topic]"` $\to$ Initiates deep consultative debrief.

### 4. Global Ecosystem Subsystem
- `"Ecosystem status"` $\to$ Summarizes health across all 3 subsystems under the current autonomy mode.
- `"What's happening?"` $\to$ Returns color-coded cross-system activity feed (Trading=Blue, FORGE=Orange, AI=Green, FRIDAY=Purple).
- `"System health"` $\to$ Executes 3-way health audit across Trading Bot, FORGE, and AI-Universe.

---

## ⚙️ Configuration Reference (.env)

```bash
# ============================ FORGE (AUTONOMOUS SWE ENGINE) ==============================
FRIDAY_FORGE_API_URL=http://localhost:8001
FRIDAY_FORGE_API_KEY=your_forge_api_key_here
FRIDAY_FORGE_ENABLED=true
FRIDAY_FORGE_MAX_CONCURRENT_TASKS=3
FRIDAY_FORGE_TASK_TIMEOUT=1800
```
