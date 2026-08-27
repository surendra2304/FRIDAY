# 🧠 FRIDAY Market Intelligence & Prediction Oversight Manual

This document outlines the market intelligence pipeline, alternative data ingestion (news NLP, on-chain whale flows, social sentiment), prediction accuracy calibration standards, and 15-minute background vigilance procedures.

---

## 🏛️ Market Intelligence Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 AI-Universe Deep Prediction Core            │
│       • Multi-horizon directional forecasts (BTC, ETH, SOL) │
│       • Alternative data ingestion & NLP sentiment engine   │
└──────────────────────────────┬──────────────────────────────┘
                               │ Structured Predictions & Telemetry
                               ▼
┌─────────────────────────────────────────────────────────────┐
│          FRIDAY Intelligence Oversight Tier (Level 50)      │
├──────────────────────────────┬──────────────────────────────┤
│  IntelligenceEngine          │  IntelligenceVigilance       │
│  • Asset Direction & Probs   │  • Adverse Predictions (>75%)│
│  • On-Chain Whale Tracking   │  • Sentiment Surge Alerts    │
│  • Rolling Brier Calibration │  • Accuracy Decay (<60%)     │
├──────────────────────────────┼──────────────────────────────┤
│  IntelligenceBriefingSkill   │  MorningIntelligenceWorkflow │
│  • Market Intel Report       │  • Overnight News Impact     │
│  • Asset Deep Prediction     │  • Daily Directional Posture │
│  • Accuracy Audit            │  • Conversational Briefing   │
└──────────────────────────────┴──────────────────────────────┘
```

### Invariant & Governance Principle:
$$\text{Intelligence inputs are informational inputs, NOT execution directives.}$$
- The operator and hardcoded safety gates hold full authority.
- All AI predictions and sentiment telemetry persisted to memory carry `TrustLevel.UNTRUSTED_EXTERNAL`.

---

## 🎙️ Intelligence Voice Command Reference

| Natural Language Command | Analysis / Action | Spoken Output Response |
| :--- | :--- | :--- |
| `"Market intelligence report"` | Full Market Debrief | News sentiment, Fear & Greed index, on-chain net flows, and active asset forecasts. |
| `"What does the model predict for BTC?"` | Asset Directional Deep Dive | 76% bullish probability, +2.4% expected move, key support ($63.2k), resistance ($66.5k). |
| `"What does the model predict for ETH?"` | Asset Directional Deep Dive | 58% bearish probability, -1.2% expected move, key support ($3,420), resistance ($3,620). |
| `"How accurate have predictions been?"` | 30-Day Accuracy Audit | Rolling 78.5% directional accuracy, Brier score 0.142, and calibration health. |
| `"Any intelligence alerts?"` | Anomaly Inspection | Summarizes active whale accumulation events and adverse prediction alerts. |

---

## 🚨 Intelligence Vigilance Alert Catalog

1. **Adverse Prediction Alert (WARNING)**:
   - Trigger: Model indicates $> 75\%$ directional probability contrary to an active open position (e.g. Bearish prediction while holding Long).
   - Action: Voice warning and visual dashboard escalation.
2. **Sentiment Surge Alert (INFO/WARNING)**:
   - Trigger: Fear & Greed index enters extreme territory ($>75$ or $<25$) or social sentiment 3-sigma spike.
   - Action: Logged to memory and announced during briefings.
3. **Whale Accumulation / Inflow Alert (INFO)**:
   - Trigger: Large net exchange outflows ($>5,000\text{ BTC}$) or single transfers $>10,000\text{ BTC}$.
   - Action: Institutional flow notification.
4. **Model Accuracy Decay Alert (WARNING)**:
   - Trigger: 30-day directional prediction accuracy falls below $60.0\%$.
   - Action: Model recalibration request logged to evolution lab.

---

## 🌅 Morning Intelligence Briefing Structure

- **Delivered Daily at 08:00 UTC**:
  1. Overnight NLP sentiment narrative impact.
  2. 24-hour directional and volatility forecasts for held assets.
  3. On-chain whale accumulation metrics.
  4. Model calibration status.
