# 🧠 FRIDAY Advanced Memory Consolidation & Learning Manual

This document details the biological memory consolidation architecture, nightly episodic-to-semantic compression, cross-session heuristic learning, proactive commitment recall, and memory health monitoring in the **FRIDAY Operating System**.

---

## 🏛️ Cognitive Memory Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Conversational Inquiries & Stated Commitments         │
│     • Cross-Session Recurring Command Sequences             │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Advanced Memory & Learning Core            │
├──────────────────────────────┬──────────────────────────────┤
│  MemoryConsolidationEngine   │  CrossSessionLearning        │
│  • Nightly 03:00 Job         │  • Recurring Pattern Clust   │
│  • Episodic -> Semantic      │  • Dynamic Preference Model  │
│  • 30-Day Half-Life Decay    │  • Contradiction Detection   │
├──────────────────────────────┼──────────────────────────────┤
│  ProactiveMemory             │  MemoryHealthMonitor         │
│  • Future User Commitments   │  • Unbounded Growth Alarm    │
│  • Unfinished Task Resumption│  • Auto-Compaction (>30%)    │
│  • Deadline Extraction       │  • Daily Backup Verification │
├──────────────────────────────┴──────────────────────────────┤
│  Cold Storage: memory/cold_storage/ (Zero Information Loss) │
└─────────────────────────────────────────────────────────────┘
```

---

## 🌙 1. Episodic-to-Semantic Consolidation (Nightly 03:00)

1. **Episodic Events**: High-resolution chronological records of every user command, trading event, Nexus lead, and Forge build.
2. **Semantic Compression**: Distills repetitive granular events into concise generalized insights:
   - *Episodic Stream*: 14 trading bot status inquiries this week.
   - *Semantic Knowledge*: *"User is actively monitoring quantitative trading operations."*
3. **Importance Scoring**:
   $$I = (50 \cdot R_{\text{recency}}) \cdot F_{\text{frequency}} \cdot E_{\text{stress}}$$
4. **Cold Storage Archival**: Raw episodic logs are archived to `memory/cold_storage/episodic_YYYY-MM.json`, ensuring active memory stays fast and compact with zero historical data loss.

---

## 🔄 2. Cross-Session Pattern Learning & Contradiction Detection

1. **Workflow Shortcuts**:
   - Detects recurring sequences (e.g. `trading_status` followed by `forge_status` in the morning) and proposes combined shortcuts: *"Offer combined Trading & Forge Morning Briefing"*.
2. **Learned Preferences**:
   - Response length (brief vs detailed), alert timing (immediate vs batched), and subsystem interest weights.
3. **Behavioral Contradiction Detection**:
   - If user configures negative rule *"stop alerting me about bitcoin"* but queries bitcoin positions 3 times manually, FRIDAY surfaces the contradiction and offers subtle notifications.

---

## ⏰ 3. Proactive Commitments & Unfinished Tasks

1. **Commitment Tracking**:
   - User mentions: *"I will review the trading strategy tomorrow"*.
   - Next day, FRIDAY proactively asks: *"You mentioned reviewing the trading strategy — want the current performance summary?"*
2. **Unfinished Task Resumption**:
   - Interrupted Forge build task detected $\to$ next session FRIDAY asks: *"You started asking Forge to build 'trading dashboard' earlier — want to resume where you left off?"*

---

## 🛡️ 4. Memory Health & Compaction Watchdog

- Monitored by `MemoryHealthMonitor` every 60 seconds.
- Alerts if memory items exceed $50,000$.
- Automatically triggers database compaction when fragmentation exceeds $30\%$.
- Verifies that memory state backup snapshots have been created within the last 24 hours.
