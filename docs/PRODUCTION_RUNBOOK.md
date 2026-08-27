# 📘 FRIDAY Production Operations Runbook

This runbook defines standard operating procedures (SOPs), scheduled maintenance, incident troubleshooting, and emergency protocols for the multi-system supervisory architecture (**FRIDAY AI OS**, **Algorithmic Trading Bot**, and **AI-Universe Intelligence**).

---

## 🏛️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                 AI-Universe Intelligence                    │
│            (External Multi-Agent Advisory API)              │
└──────────────────────────────┬──────────────────────────────┘
                               │ Scheduled Strategy Telemetry
                               ▼ (/v1/trading/consult)
┌─────────────────────────────────────────────────────────────┐
│             Algorithmic Trading Bot (Binance)               │
│   • Hardcoded Safety Gates (Max Leverage 5x, Max DD 5%)     │
│   • Execution Engine & Kill-Switch API (/api/panic)         │
│   • Append-Only Advisory Log (advisory_log.jsonl)           │
└──────────────────────────────▲──────────────────────────────┘
                               │
                               │ Telemetry & Emergency Controls
                               ▼ (GET /api/*, POST /api/panic)
┌─────────────────────────────────────────────────────────────┐
│                  FRIDAY AI Operating System                 │
│   • ProductionDashboard & ProductionMonitor (30s Polling)   │
│   • ProductionAlertManager (Prioritization & Routing)       │
│   • EmergencyProcedureManager (Trading Halt & Rollback)     │
│   • Skills: advisory_supervisor, ab_test_monitor, testnet   │
│   • Memory Trust: TrustLevel.UNTRUSTED_EXTERNAL             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Standard Operational Checklists

### 1. Daily Operations Checklist (08:00 UTC)
1. **System Health Verification**:
   - Query FRIDAY: *"System status"*.
   - Verify all 3 tiers report **🟢 ONLINE / HEALTHY**.
   - Check endpoint latencies are $< 500\text{ ms}$.
2. **Trading Performance Audit**:
   - Query FRIDAY: *"Trading performance"*.
   - Confirm current equity, cash balance, and today's cumulative PnL.
   - Inspect open positions and unrealized profit/loss.
3. **AI Advisory Review**:
   - Query FRIDAY: *"Trading morning briefing"*.
   - Check recent recommendation count, applied vs rejected verdicts.
   - Verify no unacknowledged contested advisories.
4. **Active Alert Clearance**:
   - Query FRIDAY: *"Show alerts"*.
   - Acknowledge or resolve any pending warnings.

### 2. Weekly Maintenance Procedures (Sundays 22:00 UTC)
1. **A/B Experiment Evaluation**:
   - Query FRIDAY: *"Generate A/B report"*.
   - Verify if statistical significance ($p < 0.05$) has been reached for active overlays.
2. **Log & Database Hygiene**:
   - Inspect SQLite database size (`friday.db`). Run WAL checkpoint if required.
   - Rotate application logs and verify append-only advisory logs.
3. **Parameter Drift Inspection**:
   - Verify active testnet overlays against baseline configuration files.

### 3. Monthly Performance Review
1. Compute trailing 30-day Sharpe ratio, Sortino ratio, max drawdown, and profit factor.
2. Review audit logs: `EmergencyProcedureManager.get_audit_trail()`.
3. Validate exchange API key permissions and expiration dates.

---

## 🚨 Emergency Response Procedures

### 🛑 Procedure 1: Emergency Trading Halt
**Trigger**: Excessive drawdown, runaway algorithm, anomalous order execution, or catastrophic market event.
- **Voice Command**: *"Emergency halt"* or *"Trigger panic"*
- **API Dispatched**: `POST /api/panic {"release": false}`
- **Precedence**: `CommandPrecedence.FRIDAY_COMMANDS` (Level 50)
- **Effect**: Immediately cancels pending orders and blocks new position creation.

### 🔄 Procedure 2: Emergency Parameter Rollback
**Trigger**: AI parameter overlay resulting in elevated losses, high slippage, or erratic stop-outs.
- **Voice Command**: *"Rollback parameters"*
- **API Dispatched**: `POST /api/testnet/advisory/rollback {"action": "ROLLBACK"}`
- **Effect**: Reverts all testnet and live parameters to default hardcoded baseline.

### ⏸️ Procedure 3: AI Advisory Deactivation
**Trigger**: AI-Universe service degradation, hallucinations, or API errors.
- **Voice Command**: *"Disable testnet advisory"*
- **API Dispatched**: `POST /api/testnet/advisory/toggle {"enabled": false, "mode": "SHADOW"}`
- **Effect**: Switches advisory processing to diagnostic observation only.

---

## 🔧 Incident Troubleshooting Guide

| Symptom / Alert | Root Cause | Immediate Action |
| :--- | :--- | :--- |
| **`BOT_UNREACHABLE`** (Critical) | Trading bot host down, network drop, or Render service crash. | 1. Check cloud hosting status.<br>2. Test direct REST health endpoint.<br>3. Alert primary operator. |
| **`AI_HEALTH_DOWN`** (Warning) | AI-Universe port 8000 offline or model gateway timeout. | 1. FRIDAY auto-falls back to default baseline.<br>2. Check local AI-Universe process status. |
| **`DRAWDOWN_CRITICAL`** (Critical) | Account drawdown breached 5.0% limit. | 1. Issue *"Rollback parameters"*.<br>2. If losses continue, issue *"Emergency halt"*. |
| **`CASCADING_FAILURE`** (Critical) | Multi-endpoint latency spike or concurrent outages. | 1. Dispatches automated multi-channel contact broadcast.<br>2. Engage primary on-call engineer. |

---

## 📞 Escalation Matrix & Contacts

| Tier | Role | Contact | Notification Channels |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Primary Operator (Surendra) | `surendra@example.com` / `+1-555-0199` | Voice, Dashboard, SMS, Email |
| **Tier 2** | Risk Oversight Desk | `risk@example.com` / `+1-555-0198` | SMS, Email, Webhook |
| **Tier 3** | Exchange Operations Desk | Support Portal / Dedicated Line | Support Ticket |

---

## ⚙️ Configuration Reference

| Environment Variable | Description | Default Value |
| :--- | :--- | :--- |
| `TRADING_BOT_URL` | Base URL for Trading Bot REST API | `https://algorithmic-trading-bot-fra.onrender.com` |
| `TRADING_BOT_API_KEY` | Secret authentication token | `X-FRIDAY-API-Key` |
| `AI_UNIVERSE_URL` | Base URL for AI-Universe REST API | `http://localhost:8000` |
| `MAX_DRAWDOWN_LIMIT_PCT` | Hardcoded maximum account drawdown | `5.0%` |
| `MAX_LEVERAGE_LIMIT` | Hardcoded maximum testnet leverage | `5x` |
