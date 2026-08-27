# 🔮 FRIDAY Proactive Automation & Scheduled Intelligence Manual

This document details dynamic scheduled briefings, pre-inquiry root-cause anomaly investigations, recommendation follow-up workflows, and intelligent notification routing with quiet-hours enforcement in the **FRIDAY Operating System**.

---

## 🏛️ Proactive Intelligence Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Spoken Voice & Mobile Push Channels                   │
│     • Quiet Hours Protection (22:00 – 07:00)                │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│        FRIDAY Proactive Automation & Intelligence Core      │
├──────────────────────────────┬──────────────────────────────┤
│ ScheduledIntelligenceOperator│ ProactiveAnomalyInvestigator │
│ • Routine Wake-Up Learning   │ • Pre-Inquiry Root Cause Trac│
│ • Market Session Alignment   │ • Trading Strategy Driver Res│
│ • Calendar Meeting Skip Rule │ • Cross-Subsystem Outage Map │
├──────────────────────────────┼──────────────────────────────┤
│ AutomatedFollowUpWorkflow    │ SmartNotificationRouter      │
│ • Retrospective Outcome Delta│ • 4 Urgency Tiers (CRIT..LOW)│
│ • 24h Gentle Reminder Flow   │ • Quiet Hours Muting Rule    │
│ • Confidence Calibration     │ • Weekend Batch Learning     │
└──────────────────────────────┴──────────────────────────────┘
```

---

## ⏰ 1. Dynamic Briefing Schedules

- **Learned Morning Routine**: Calculates the user's historical wake-up time window based on morning voice interaction timestamps ($\pm 15\text{min}$) rather than rigid cron timers.
- **Contextual Guards**:
  - *Calendar Busy*: Automatically defers spoken briefings if the user is in a scheduled meeting.
  - *Severe Weather*: Pauses briefings if severe weather alerts are active in the user's area.
  - *Market Session*: Aligns financial briefings with global exchange opening bells.

---

## 🔍 2. Autonomous Pre-Inquiry Anomaly Investigation

- **Trading Drawdown**: Upon detecting a 3% daily loss, FRIDAY queries telemetry, determines the driver strategy (`Supertrend`), audits AI advisory involvement, and synthesizes a spoken briefing:
  > *"Trading bot hit 3% daily loss. Supertrend strategy was the driver. I've prepared a summary — want to hear it?"*
- **Nexus Growth Drops**: Correlates sudden conversion dips with recent deployment IDs.
- **Cross-Subsystem Cascades**: Distinguishes between software bugs and upstream provider outages (e.g. AI-Universe latency cascading into Forge timeouts).

---

## 🔄 3. Automated Recommendation Follow-Ups

- **Outcome Retrospectives**: Measures performance deltas after recommendations (*"I suggested pausing Supertrend 2 days ago — here's what happened since: +240.0 USDT"*).
- **24-Hour Unacted Reminders**: Gentle check-ins for acknowledged recommendations.
- **Feedback Calibration**: Automatically adjusts future recommendation confidence based on verified historical outcomes.

---

## 📢 4. Smart Notification Routing & Quiet Hours

| Tier | Delivery Mechanism | Quiet Hours (22:00–07:00) Behavior |
| :--- | :--- | :--- |
| **CRITICAL** | Voice + Push + Dashboard immediately | **Bypasses Quiet Hours** (Spoken Alert) |
| **HIGH** | Voice (if active) + Push + Dashboard | Muted voice $\to$ Push + Dashboard |
| **MEDIUM** | Batched into next scheduled briefing | Batched silently |
| **LOW** | Dashboard silently | Silent |
