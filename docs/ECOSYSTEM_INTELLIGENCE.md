# 🧠 Unified Ecosystem Intelligence Reporting Manual

This document details the multi-subsystem intelligence aggregation, automated executive reporting, conversational queries, cross-system anomaly detection, and 90-day retention storage in the **FRIDAY Operating System**.

---

## 🏛️ Intelligence Pipeline & Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Voice & Text Briefings ("Generate morning briefing")  │
│     • Conversational Queries ("Compare leads to profits")   │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Unified Intelligence Engine                │
├──────────────────────────────┬──────────────────────────────┤
│  EcosystemIntelligenceService│  ConversationalEcosystemQuery│
│  • Morning Executive Briefing│  • Multi-Subsystem Answers   │
│  • Evening Performance Delta │  • Cross-Domain Comparisons  │
│  • Sunday Weekly Strategic   │  • Unified Health Audits     │
├──────────────────────────────┼──────────────────────────────┤
│  EcosystemAnomalyDetection   │  UnifiedIntelligencePanel    │
│  • Cascading Failure Rules   │  • Composite Health Gauge    │
│  • Correlated Build Outages  │  • Real-Time Metric Matrix   │
│  • 90-Day Retention Pruner   │  • 1-Click Briefing Actions  │
└──────┬───────────────┬───────┴───────┬──────────────────────┘
       │               │               │               │
       ▼               ▼               ▼               ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│  Trading Bot ││  Nexus Web   ││  FORGE SWE   ││ AI-Universe  │
│  (Port 5000) ││  (Port 8002) ││  (Port 8000) ││  (Port 8001) │
└──────────────┘└──────────────┘└──────────────┘└──────────────┘
```

---

## 📊 Executive Reporting Schedule

### 1. Morning Executive Briefing (`generate_morning_briefing`)
- **Focus**: Overnight trading performance, Nexus visitor counts & enterprise leads, FORGE build readiness, AI-Universe availability, and weighted composite health score.
- **Trigger**: Spoken command *"Morning briefing"* or automated 08:00 UTC schedule.

### 2. Evening Performance Wrap-Up (`generate_evening_wrapup`)
- **Focus**: Daily realized P&L deltas, closed trading positions, delivered software packages, enterprise lead conversions, and tomorrow's operational outlook.
- **Trigger**: Spoken command *"Evening wrap-up"* or automated 20:00 UTC schedule.

### 3. Weekly Strategic Report (`generate_weekly_report`)
- **Focus**: Sunday evening week-over-week performance matrix, Sharpe ratio, conversion rate lift, build velocity, and proactive resource allocation recommendations.
- **Trigger**: Spoken command *"Weekly report"* or automated Sunday 21:00 UTC schedule.

---

## ⚖️ Composite Health Score Formula

The global ecosystem health score is computed as a weighted composite:

$$\text{Health Score} = 0.30 \cdot S_{\text{Trading}} + 0.25 \cdot S_{\text{Nexus}} + 0.25 \cdot S_{\text{Forge}} + 0.20 \cdot S_{\text{AI}}$$

---

## 🚨 Cross-System Anomaly Detection Rules

1. **Cascading Failure**: $\ge 2$ subsystems simultaneously enter `DEGRADED`, `ERROR`, or `UNAVAILABLE` states.
2. **Correlated Build Failure**: FORGE build tasks fail while AI-Universe LLM providers report latency spikes or outages.
3. **Market / Web Anomaly**: Trading bot experiences sudden drawdown ($\ge 3.5\%$) during high website traffic surges ($\ge 8,000$ visitors).
4. **Unusual Quietness**: Zero activity across all four subsystems during operational hours.

---

## 📁 90-Day Retention Persistence

All reports are persisted in JSON and Markdown formats:
- Location: `reports/ecosystem/YYYY-MM-DD_{type}_{id}.json` and `.md`
- Automatic Retention: Reports older than 90 days are pruned automatically on every report generation cycle.
