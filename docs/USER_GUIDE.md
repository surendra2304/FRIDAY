# 📖 FRIDAY Ecosystem User Guide & Operations Manual

Welcome to **FRIDAY**, your Autonomous Multi-Agent AI Operating System supervising the **Algorithmic Trading Bot**, **FORGE Autonomous Software Engineering Engine**, and **AI-Universe Intelligence Provider**.

---

## 🚀 Getting Started

FRIDAY acts as the **single hub** for all commands, telemetry, and cross-system workflows.

### 1. Starting the Ecosystem
Ensure all managed subsystems are running or accessible:
- **FRIDAY Core**: Runs locally with voice / text / REST interfaces.
- **Algorithmic Trading Bot**: `http://localhost:5000`
- **FORGE SWE Engine**: `http://localhost:8000`
- **AI-Universe Core**: `http://localhost:8001`

---

## 🎙️ Natural Voice Command Reference

| Subsystem | What You Say | What FRIDAY Does |
| :--- | :--- | :--- |
| **ECOSYSTEM** | `"Status of everything"` | Returns tri-system overview (Trading Bot equity/positions, FORGE builds, AI-Universe confidence). |
| **ECOSYSTEM** | `"Brief me"` | High-level conversational executive summary of all key activities and health. |
| **ECOSYSTEM** | `"What's the health of my systems?"` | Parallel health check across all three subsystems. |
| **FORGE** | `"Forge, build me a portfolio website"` | Expands goal using the `WEBSITE` template and submits build request to FORGE. |
| **FORGE** | `"Show me what Forge built"` | Inspects recent files, verification test suite results, and delivered package. |
| **FORGE** | `"Cancel the Forge task"` | Cancels running task immediately. |
| **TRADING** | `"How are my trades doing?"` | Reports current equity, open positions, daily P&L, and aggregate leverage. |
| **TRADING** | `"Emergency stop trading"` | Triggers panic kill-switch and closes open orders. |
| **AI-UNIVERSE** | `"What does AI Universe predict for BTC?"` | Consults directional forecasts, news sentiment, and whale signals. |

---

## 🔄 Common Multi-System Workflows

### 1. "Build me a trading dashboard for my bot"
1. **Trigger**: You speak *"Forge, build a trading dashboard for my bot"*.
2. **Context Injection**: FRIDAY retrieves Trading Bot endpoint specifications (`GET /api/status`, `GET /api/positions`, `GET /api/pnl`).
3. **Template Preparation**: FRIDAY formats a structured `TRADING_DASHBOARD` build plan.
4. **Confirmation**: FRIDAY asks for your confirmation before dispatching.
5. **Execution**: FORGE plans, codes, tests, and verifies the dashboard.
6. **Review**: FRIDAY alerts you with verification coverage and a preview.

### 2. "How are my trades doing?"
1. **Trigger**: You speak *"How are my trades doing today?"*.
2. **Contextual Retrieval**: FRIDAY fetches cached portfolio telemetry.
3. **Response**: FRIDAY speaks equity, active positions, and daily P&L.
4. **Follow-Up**: You say *"How is it doing?"* $\to$ FRIDAY uses contextual memory to resolve reference to your active strategy.

### 3. "What should I build next?"
1. **Trigger**: You ask *"What should I build next?"* or review suggestions.
2. **Analysis**: FRIDAY's `EcosystemSuggestionsEngine` checks your trading logs and build history.
3. **Recommendation**: E.g., *"Your Supertrend strategy is underperforming — want me to ask Forge to build a strategy analyzer?"*

---

## 📱 Multi-Modal & Mobile Dashboard

- **Desktop UI**: Interactive multi-card layout with central alert feeds and panic kill-switch.
- **Mobile View**: Lightweight responsive HTML dashboard at `/mobile`.
- **Voice Preview**: Automatic transcription and intent preview with confirmation prompts for sensitive commands.

---

## ⚙️ Configuration (.env)

```bash
# Ecosystem Unified Settings
ECOSYSTEM_ENABLED=True
TRADING_BOT_BASE_URL=http://localhost:5000
FORGE_BASE_URL=http://localhost:8000
AI_UNIVERSE_BASE_URL=http://localhost:8001

# Polling Intervals
FORGE_SUPERVISION_INTERVAL_SECONDS=60
FORGE_HEALTH_CHECK_INTERVAL_SECONDS=300
```
