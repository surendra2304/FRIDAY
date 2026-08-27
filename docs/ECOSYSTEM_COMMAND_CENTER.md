# 🌐 FRIDAY Unified Ecosystem Command Center Manual

This document provides the operational guide, architecture, cross-system workflows, daily briefing schedules, and command routing rules for the **Unified Ecosystem Command Center** supervising the **Algorithmic Trading Bot**, **FORGE Software Engineering Engine**, and **AI-Universe Intelligence Provider**.

---

## 🏛️ Unified Command Center Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Single Voice Entrypoint ("Status of everything")      │
│     • Cross-Build Confirmations & Governance Policies       │
└──────────────────────────────▲──────────────────────────────┘
                               │ Voice Commands / Signed Confirmations
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Unified Ecosystem Command Center           │
├──────────────────────────────┬──────────────────────────────┤
│  EcosystemRegistry           │  EcosystemStatusSkill        │
│  • Central Subsystem Catalog │  • Full Multi-System Reports │
│  • Last-Known-Good States    │  • Conversational Briefings  │
│  • Parallel Health Audits    │  • Subsystem Deep Dives      │
├──────────────────────────────┼──────────────────────────────┤
│  CrossSystemOrchestrator     │  EcosystemCommandRouter      │
│  • TRADING_DASHBOARD Builds  │  • Intent Classification     │
│  • PERFORMANCE_REPORTER      │  • Multi-Domain Routing      │
│  • ALERT_SYSTEM Integrations │  • Clarification Engine      │
├──────────────────────────────┼──────────────────────────────┤
│  MasterDailyBriefingWorkflow │  EcosystemDashboardPanel     │
│  • Morning Strategic Debrief │  • Visual Status Cards       │
│  • Evening Wrap-Up           │  • Central Alert Feed        │
└──────┬───────────────────────┼───────────────────────┬──────┘
       │ REST / Venue Bridge   │ LLM Analytics Core    │ Autonomous Builds
       ▼                       ▼                       ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Algorithmic     │  │  AI-Universe     │  │  FORGE SWE       │
│  Trading Bot     │  │  Consultant      │  │  Engine          │
│  (Real Capital)  │  │  (Intelligence)  │  │  (Build Pipeline)│
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Precedence & Invariants:
1. **Safety Precedence**: `Safety Gates (100) > FRIDAY Master Supervisor (50) > AI-Universe Recommendations / FORGE Tasks (10)`.
2. **Explicit Cross-System Confirmation**: Workflows that bridge multiple subsystems (e.g. asking FORGE to build against the Trading Bot API) require explicit operator approval before dispatching.
3. **Independent Operation**: Each subsystem remains fully operational independently; the Command Center is an overarching coordination layer.
4. **Strict Hub-and-Spoke Topology**: FRIDAY is the ONLY hub — subsystems never talk to each other directly.

---

## 🎙️ Voice Command Reference

| Subsystem Target | Natural Voice Command | Response / Execution Action |
| :--- | :--- | :--- |
| **ECOSYSTEM** | `"Status of everything"` | Returns full multi-system status (Trading Bot equity/positions, FORGE builds, AI-Universe providers). |
| **ECOSYSTEM** | `"Brief me"` | High-level conversational executive summary of all key activities and health. |
| **ECOSYSTEM** | `"What's the health of my systems?"` | Runs parallel health checks across Trading Bot, FORGE, and AI-Universe. |
| **TRADING** | `"Trading status"` | Deep dive into Trading Bot equity ($10,450), 3 open positions, and +$420.50 daily P&L. |
| **FORGE** | `"Forge status"` | Deep dive into active builds, last completed deliverable, and 96.0% test coverage. |
| **CROSS-SYSTEM**| `"Forge, build a trading dashboard for my bot"` | Prepares `TRADING_DASHBOARD` cross-build plan linking Bot APIs to FORGE. |
| **CROSS-SYSTEM**| `"Build a report generator for my trading data"` | Prepares `PERFORMANCE_REPORTER` plan calculating Sharpe, Sortino, and drawdowns. |

---

## 📅 Daily Executive Briefings Schedule

1. **Morning Strategic Briefing (08:00 UTC)**:
   - **Trading**: Overnight realized & unrealized P&L, open positions, loss headroom.
   - **FORGE**: Delivered software packages, active build pipelines.
   - **AI-Universe**: Active directional predictions (BTC/ETH/SOL), model confidence.
   - **Ecosystem**: Consolidated tri-system health indicator.
2. **Evening Performance Wrap-Up (20:00 UTC)**:
   - **Trading**: Daily performance closing summary, trade count.
   - **FORGE**: Daily deliverables review.
   - **System**: Operational stability log and security gate status.

---

## ⚙️ Configuration Reference (.env)

```bash
# ============================ UNIFIED ECOSYSTEM COMMAND CENTER ==============================
ECOSYSTEM_ENABLED=True
TRADING_BOT_BASE_URL=http://localhost:5000
FORGE_BASE_URL=http://localhost:8000
AI_UNIVERSE_BASE_URL=http://localhost:8001
```
