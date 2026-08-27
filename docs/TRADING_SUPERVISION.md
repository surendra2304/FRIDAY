# Trading Supervision & AI-Universe Advisory Architecture

## Overview

FRIDAY operates as an autonomous **Supervisor** over the cloud-hosted Algorithmic Trading Bot on Binance Futures Testnet (`https://algorithmic-trading-bot-fra.onrender.com`). 

In this architecture, the **Trading Bot maintains a direct scheduled telemetry connection with AI-Universe** (`/v1/trading/consult`), receiving deliberative advisory recommendations and recording every evaluation to an append-only advisory log (`advisory_log.jsonl`). FRIDAY monitors bot metrics, supervises AI advisory decisions, detects contested recommendations, provides plain-language explanations, and holds the emergency panic kill-switch.

---

## 🏗️ Architecture Diagram

```mermaid
graph TD
    subgraph "Trading Bot Engine (Binance Futures Testnet)"
        BotAPI["Trading Bot REST API (/api/status, /api/advisory/*, /api/panic)"]
        SafetyGates["Hardcoded Safety Gates (Max Drawdown, Risk Limits, Position Sizing)"]
        ExecutionEngine["Order Execution Engine (SL/TP Brackets)"]
        AdvisoryLog["Append-Only Advisory Log (advisory_log.jsonl)"]
        
        BotAPI --> SafetyGates
        SafetyGates --> ExecutionEngine
        SafetyGates --> AdvisoryLog
    end

    subgraph "External Multi-Agent Intelligence"
        AIUniverse["AI-Universe (/v1/trading/consult)"]
    end

    subgraph "FRIDAY AI Operating System (Supervisor)"
        SupervisorSkill["AdvisorySupervisorSkill (Briefings, Explanations, Monitoring)"]
        BotOperator["TradingBotOperator Skill (Status, Overlay State, Panic API)"]
        WatchdogOp["AdvisoryWatchdogOperator (15-min Background Polling)"]
        PrecedenceEngine["Command Precedence Validator (trading_precedence.py)"]
        Memory["FRIDAY Memory (TrustLevel.UNTRUSTED_EXTERNAL for AI advice)"]
    end

    %% Direct Bot to AI-Universe Connection
    BotAPI <-->|"Direct Scheduled Consult"| AIUniverse

    %% FRIDAY Supervision
    SupervisorSkill -->|"GET /api/advisory/*, /api/status"| BotAPI
    BotOperator -->|"GET /api/status, POST /api/panic"| BotAPI
    WatchdogOp -->|"Polls 15m & Alerts"| BotAPI
    WatchdogOp -->|"Logs Untrusted External"| Memory
    PrecedenceEngine -->|"Enforces Invariants"| BotOperator
```

---

## ⚖️ Immutable Command Precedence

Command precedence is immutable and strictly enforced by `src/friday/skills/trading_precedence.py`:

$$\text{Safety Gates (Trading Bot - Level 100)} > \text{FRIDAY Commands (Supervisor - Level 50)} > \text{AI-Universe Recommendations (Advisor - Level 10)}$$

1. **Safety Gates (Level 100)**: The Trading Bot's hardcoded risk limits, maximum drawdown boundaries, and testnet safety guarantees represent the absolute highest authority. FRIDAY cannot weaken or bypass these gates.
2. **FRIDAY Commands (Level 50)**: FRIDAY acts as the human supervisor's autonomous delegate. FRIDAY can manually override AI-Universe recommendations or trigger emergency panic kill-switches.
3. **AI-Universe Recommendations (Level 10)**: AI-Universe provides consultative strategy and parameter adjustments. Recommendations only apply if they strictly comply with the Trading Bot's safety gates.
4. **Kill-Switch Invariant**: When FRIDAY issues `trigger_panic()`, it calls the Trading Bot's **own kill-switch API** (`POST /api/panic`). FRIDAY does not implement its own separate trading order canceler.

---

## 🎙️ Natural Language Commands

| User Voice / Text Query | Action Executed | Risk / Safety Level |
| :--- | :--- | :---: |
| `"How is the trading bot doing?"` | Returns bot status (equity, PnL, open positions) + summary of AI advisory activity. | `SAFE` |
| `"What did AI-Universe recommend?"` | Retrieves recent AI recommendations from `/api/advisory/recent` with verdicts and confidence. | `SAFE` |
| `"Show me rejected advisories"` | Filters recent advisory log for `REJECT` verdicts and explains rejection reasons. | `SAFE` |
| `"What parameters has the AI changed?"` | Retrieves active parameter overlay from `/api/advisory/state`. | `SAFE` |
| `"Trading morning briefing"` | Synthesizes a comprehensive spoken daily summary of positions, equity, PnL, and AI advisories. | `SAFE` |
| `"Explain advisory <decision_id>"` | Breaks down a specific advisory decision, AI confidence, and the exact safety bounds evaluated. | `SAFE` |
| `"Activate panic / Kill switch"` | Invokes trading bot `POST /api/panic` to block all new order placement. | `DANGEROUS` (Gated) |
| `"Release panic / Resume trading"` | Invokes trading bot `POST /api/panic {"release": true}` to resume operations. | `SENSITIVE` (Gated) |

---

## 🚨 Advisory Watchdog Operator (`AdvisoryWatchdogOperator`)

Running as a persistent background operator managed by `OperatorManager`, the `AdvisoryWatchdogOperator` evaluates trading state every 15 minutes:

- **Trigger Condition 1: Contested Advisory**: Emits a warning alert if a decision has `verdict=REJECT` and `confidence > 0.70` (where AI proposed an aggressive adjustment that safety gates blocked).
- **Trigger Condition 2: AI-Universe Outage**: Emits a warning alert if AI-Universe health reports `DOWN` or `UNREACHABLE` while enabled.
- **Trigger Condition 3: Trading Bot Unreachable**: Emits a critical alert if the trading bot REST API fails to respond.
- **Memory Trust Boundary**: All external advisory summaries and alerts persisted into FRIDAY's SQLite memory are marked with `TrustLevel.UNTRUSTED_EXTERNAL` to maintain cognitive boundaries.

---

## 🧪 Mock Server Setup & Testing

### Mock Server Implementation (`tests/mock_trading_bot.py`)
FRIDAY provides an in-process and threaded HTTP mock server (`MockTradingBotServer`) simulating all trading bot endpoints:
- `GET /api/status`: Generates live equity, unrealized/realized PnL, profit factor, and active positions.
- `GET /api/advisory/recent`: Returns customizable advisory log records with verdicts (`APPLY`, `REJECT`, `HOLD`), confidence scores, and reasons.
- `GET /api/advisory/state`: Returns active AI parameter overlays and AI-Universe service health.
- `POST /api/panic`: Simulates emergency order blocking and panic release with command precedence verification.

### Test Scenarios Supported:
1. **`mixed`**: Realistic telemetry with 1 applied advisory, 1 contested rejected advisory (>70% confidence), 1 low-confidence hold, and active parameter overlay (`btc_sl_pct=0.4`).
2. **`all_rejected`**: All proposals rejected by bot safety gates (e.g. leverage limits, max stop loss boundaries).
3. **`all_applied`**: All proposals compliant with risk thresholds and applied to the active parameter overlay.
4. **`ai_universe_down`**: AI-Universe service reporting `DOWN` (HTTP 503 error telemetry).
5. **`unreachable`**: Simulates complete trading bot server downtime and connection drops.

### Example Server Usage:
```python
from tests.mock_trading_bot import MockTradingBotServer
from friday.skills.trading_bot_operator import TradingBotOperator

# Start threaded mock server on custom port
server = MockTradingBotServer(port=8999, scenario="mixed")
base_url = server.start()

# Connect operator
operator = TradingBotOperator(base_url=base_url)
summary = operator.get_advisory_summary()

# Switch scenario dynamically
server.set_scenario("all_rejected")
server.stop()
```

---

## 📊 Test Coverage & Verification Report

### Test Suites & Status (35 / 35 Passing):

| Test Suite | Focus Area | Status |
| :--- | :--- | :---: |
| **`tests/test_advisory_commands.py`** | Natural language voice/text commands across all 5 bot scenarios | ✅ **PASS** (8/8) |
| **`tests/test_advisory_watchdog.py`** | 15-minute polling, multi-condition triggers, and untrusted memory logging | ✅ **PASS** (5/5) |
| **`tests/test_precedence.py`** | Precedence tagging, invariant validation, and safety gate protection | ✅ **PASS** (5/5) |
| **`tests/test_full_integration.py`** | End-to-end cognitive loop routing, memory persistence, and advisory explanations | ✅ **PASS** (4/4) |
| **`tests/test_advisory_supervisor.py`** | Core supervisor skill methods, capability gating, and briefing composition | ✅ **PASS** (13/13) |

### Precedence Verification Results:
- **Safety Gate Invariant**: Attempts to issue commands with safety bypass intentions (`bypass_safety_gates`, `override_risk_limits`, `force_live_trading`) are intercepted and rejected with `Precedence Invariant Violation`.
- **Audit Tagging**: Outbound commands generated by FRIDAY carry `precedence_level: 50 (FRIDAY_COMMANDS)` and explicitly declare `can_bypass_bot_safety_gates: False`.
- **Kill-Switch Verification**: Panic execution dispatches to the trading bot's authoritative `/api/panic` endpoint without implementing custom or conflicting cancel logic.

