# 🎙️ FRIDAY Advanced Voice Operations & NLP Command Manual

This document details the compound intent routing, contextual memory with pronoun and temporal resolution, proactive suggestion engines, multi-turn dialogs with biometric security, and sub-2-second latency optimizations in the **FRIDAY Operating System**.

---

## 🏛️ Voice & Natural Language Cognitive Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Compound Commands ("Build a dashboard and check trades")│
│     • Follow-up Inquiries ("What about yesterday?")         │
│     • Biometric Confirmations ("Confirmed, alpha-niner")   │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Advanced Voice Operations Core             │
├──────────────────────────────┬──────────────────────────────┤
│  IntentRouter                │  ContextualConversationMemory│
│  • Multi-Intent Splitter     │  • 24h Context Expiration    │
│  • 4-Domain Entity Extractor │  • Pronoun Reference ("it")  │
│  • Sub-Intent Execution Graph│  • Temporal Follow-Up Window │
├──────────────────────────────┼──────────────────────────────┤
│  MultiTurnDialogManager      │  EcosystemSuggestionsEngine  │
│  • Ambiguity Clarification   │  • Trading Underperformance  │
│  • Biometric Confirmation    │  • Nexus Lead Proactivity    │
│  • Offline Subsystem Recovery│  • Monday Briefing Trigger   │
├──────────────────────────────┴──────────────────────────────┤
│  Performance Optimization: <2s Simple, <1s Panic, 30s TTL   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧩 Compound Multi-Intent Parsing Matrix

| User Compound Voice Command | Decomposed Sub-Intents | Subsystem Routing |
| :--- | :--- | :--- |
| *"Build me a trading dashboard and check my positions"* | 1. `FORGE_BUILD` (`template="TRADING_DASHBOARD"`)<br>2. `TRADING_POSITIONS` | 1. FORGE Engine (Port 8000)<br>2. Trading Bot (Port 5000) |
| *"How are my website and trades doing?"* | 1. `NEXUS_STATUS`<br>2. `TRADING_STATUS` | 1. Nexus Engine (Port 8002)<br>2. Trading Bot (Port 5000) |
| *"Show my leads and check portfolio risk"* | 1. `NEXUS_LEADS`<br>2. `TRADING_STATUS` | 1. Nexus Engine<br>2. Trading Bot |

---

## 🧠 Contextual Pronoun & Temporal Resolution

1. **Pronoun Reference**:
   - *"How is it doing?"* $\to$ Resolves to the most recently discussed strategy, active build, or website metric.
2. **Temporal Follow-Up**:
   - Query 1: *"How did the website do today?"*
   - Query 2: *"What about yesterday?"* $\to$ Resolves target subsystem (`nexus`) and applies new time window (`yesterday`).

---

## 🔒 Biometric Security for Dangerous Actions

- **Trigger Operations**: Emergency trading halt (`EMERGENCY_HALT`), active growth experiment cancellation (`PAUSE_EXPERIMENT`), strategy parameter purge.
- **Workflow**:
  1. System checks safety level and detects high risk.
  2. Dialog manager prompts: *"DANGEROUS ACTION: {action} requires voice biometric confirmation."*
  3. Operator responds with biometric clearance phrase (*"Confirmed"*, *"Authorized"*).
  4. Clearance verified and executed.

---

## ⚡ Performance SLAs & Latency Targets

| Request Tier | Latency Target | Optimization Mechanisms |
| :--- | :--- | :--- |
| **Emergency Panic Stop** | **$< 1.0\text{s}$** | Direct circuit breaker bypass, priority thread execution |
| **Simple Voice Query** | **$< 2.0\text{s}$** | In-memory 30-second TTL cache, pre-warmed telemetry sockets |
| **Complex Multi-Report** | **$< 10.0\text{s}$** | Parallel worker pool across all four subsystems |
