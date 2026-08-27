# 🌐 FRIDAY Multi-Exchange Portfolio Operations Manual

This document outlines the multi-exchange architecture, cross-venue risk management, automated supervision triggers, incident mitigation, and weekly review workflows across Binance, Bybit, and OKX.

---

## 🏛️ Multi-Exchange Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Unified Exchange Gateway Tier               │
│     Binance Futures (50%) | Bybit Linear (30%) | OKX (20%)  │
└──────────────────────────────▲──────────────────────────────┘
                               │
       Multi-Venue REST Telemetry (30s) / Smart Routing
                               │
┌──────────────────────────────▼──────────────────────────────┐
│       FRIDAY Multi-Exchange Supervision Tier (Level 50)     │
├──────────────────────────────┬──────────────────────────────┤
│  PortfolioSupervisorOperator │  ExchangeIncidentManager     │
│  • 30s Aggregate Polling     │  • Venue Health & Latency    │
│  • Single-Asset Ceiling (>50%)│  • Dynamic Order Rerouting  │
│  • Allocation Drift (>10%)   │  • Incident History & 30d PIR│
├──────────────────────────────┼──────────────────────────────┤
│  VoiceMultiExchangeSkill     │  WeeklyPortfolioReview       │
│  • Portfolio Overview        │  • Sunday Automated Briefing │
│  • Per-Exchange Performance  │  • Venue/Strategy Attribution│
│  • Arbitrage Scanner         │  • Correlation Matrix        │
│  • Liquidity Comparisons     │  • Capital Drift Rebalancing │
└─────────────────────────────────────────────────────────────┘
```

### Precedence & Risk Invariant:
$$\text{Unified Portfolio Safety Constraints} > \text{Individual Venue Policies} > \text{External Signals}$$
- Single asset cross-exchange exposure is hard-capped at **$50.0\%$** of total portfolio equity.
- Aggregate leverage across all venues cannot exceed the active Capital Level maximum (Level 2: **3.0x**).

---

## 🎙️ Multi-Exchange Voice Command Reference

| Natural Language Command | Triggered Analysis | Spoken Audio / Output Response |
| :--- | :--- | :--- |
| `"Portfolio overview"` | Unified Aggregation | Total equity ($25,000 USDT), venue weights (50% / 30% / 20%), 24h P&L. |
| `"How is Binance doing?"` | Venue Diagnostics | Binance latency (28.5ms), active positions, and +$420.50 USDT P&L today. |
| `"What's my exposure to BTC?"` | Asset Exposure | Total cross-exchange BTC value ($13,500 USDT / 54.0%) and venue distribution. |
| `"Any arbitrage opportunities?"` | Cross-Venue Arb Scanner | Actionable price spreads (e.g. OKX $\to$ Binance +1.10% net profit). |
| `"Exchange health status"` | Health & Uptime | API latency, WebSocket connectivity, and comparative incident count. |
| `"Which exchange has the best liquidity for ETH?"` | Order Book Depth | Spread in bps, depth within 1%, and slippage for $10k orders. |
| `"Show my cross-exchange risk"` | Risk Telemetry | Unified portfolio VaR ($420.50 USDT), leverage (0.85x), and HHI index. |
| `"Rebalance recommendations"` | Allocation Drift | Target vs actual weight variance and recommended transfer amounts. |

---

## 🚨 Exchange Incident Management & Smart Rerouting

1. **Latency Degradation ($> 500\text{ ms}$)**:
   - Alert dispatched to supervisor.
   - Recommended order rerouting: New strategy orders routed to Binance.
2. **WebSocket Disconnection / Rest API Timeout**:
   - Severity Level 2 incident created in `ExchangeIncidentManager`.
   - Active orders on degraded venue monitored via fallback REST polling.
3. **Withdrawal Halts / Liquidation Spreads**:
   - Immediate freeze on capital transfers to affected exchange.

---

## 📅 Weekly Portfolio Review Schedule

- **Automated Sunday 22:00 UTC Execution**:
  - Reviews performance attribution across Binance, Bybit, and OKX.
  - Updates asset correlation matrix (BTC/ETH/SOL).
  - Generates allocation drift correction recommendations.
  - Establishes next week's $500.00 USDT risk budget ceiling.
