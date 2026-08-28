# 🌐 FRIDAY Nexus Manager & Website Supervision Manual

This manual details the architecture, capabilities, tools, and operational workflows of **Nexus Manager** (`src/friday/skills/nexus_manager.py`) and **Nexus Supervisor Operator** (`src/friday/operators/nexus_supervisor.py`) in the **FRIDAY Autonomous Operating System**.

---

## 🏛️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Voice Commands ("Website status", "Who's on my site") │
│     • SENSITIVE Approvals with Behavioral Evidence Readouts │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│        FRIDAY Nexus Management & Supervision Core           │
├──────────────────────────────┬──────────────────────────────┤
│  NexusManagerSkill           │  NexusSupervisorOperator     │
│  • Full API Client (10 Tools)│  • 30s Polling Cycle         │
│  • Lead Pipeline by Stage    │  • Incident Voice Alerts     │
│  • Strategy Learnings & Lift │  • Lead Detect (>0.8 Score)  │
│  • AI Universe Log Audits    │  • Conversion Anomaly Alerts │
│  • UNTRUSTED_EXTERNAL Tagging│  • Unreachable Service Guard │
└──────────────────────────────┴──────────────────────────────┘
```

---

## 🛠️ 1. NexusManagerSkill Tools & API Client

| Method Name | Description | Output Details |
| :--- | :--- | :--- |
| `get_site_overview()` | Comprehensive website status | Live visitors, sessions, conversion rates, trend, incident counts, agent status. |
| `get_live_visitors()` | Real-time active sessions | Active page paths, dwell time, behavioral intent scores ($0.0 - 1.0$), inferred company. |
| `get_lead_pipeline()` | Sales pipeline by stage | Grouped by `DISCOVERY`, `EVALUATION`, `DECISION`, and `CLOSED_WON` with recommended next actions. |
| `get_incidents()` | Active incidents | List of active website errors with severity ratings (`CRITICAL`, `HIGH`, etc.). |
| `get_pending_approvals()` | Optimization actions | Pending A/B tests, copy hotfixes, and UI modifications with evidence and lift projections. |
| `approve_nexus_action(id)` | Approves pending action | SENSITIVE: Marks action approved and triggers production deployment. |
| `reject_nexus_action(id, reason)` | Rejects pending action | SENSITIVE: Rejects action with recorded justification. |
| `start_nexus_workflow(name, params)` | Workflow trigger | Initiates growth or diagnosis workflows via policy engine. |
| `get_intelligence_log(limit)` | AI-Universe debate logs | Full consultation reasoning chains, models consulted, and confidence scores. |
| `get_strategy_performance()` | Growth strategy audit | Historical lift measurements, promotion status, and empirical learnings. |
| `query_nexus_analytics(question)` | Natural language analytics | Conversational responses to visitor, bounce rate, or funnel questions. |
| `run_website_health_check()` | Full operational audit | Gateway, event pipeline, lead scoring engine, and guardrail health check. |

---

## 🗣️ 2. Natural Voice Commands

| Spoken Phrase | Triggered Action | Sample Spoken Response |
| :--- | :--- | :--- |
| *"Website status"* | `get_site_overview()` | *"🌐 Website Health: Status is HEALTHY (98.6/100). Traffic: 5,120 visitors (3 live) \| Conversion Rate: 3.82% (+4.6%)."* |
| *"Who's on my website?"* | `get_live_visitors()` | *"There are currently 3 active visitors: • Visitor from acme-corp.com on `/pricing` — Intent: VERY_HIGH (0.92)..."* |
| *"Any new leads?"* | `get_lead_pipeline()` | *"Nexus is tracking 3 active prospective leads: • acme-corp.com (Score: 94/100, Stage: DECISION)..."* |
| *"What's my conversion rate?"* | `get_site_overview()` | *"📊 Today's website conversion rate is 3.82% (+4.6% vs yesterday). Yesterday was 3.65%."* |
| *"Any website problems?"* | `get_incidents()` | *"✅ Nominal operations. There are 0 active website incidents or outages."* |
| *"Show the lead pipeline"* | `get_lead_pipeline()` | *"🎯 Nexus Lead Pipeline: Decision (1): acme-corp.com • Evaluation (1): fintech-scaleup.io • Discovery (1)..."* |
| *"Approve that Nexus action"* | `approve_nexus_action()` | *"✅ Action Approved & Deployed: `act_hero_contrast_v3`. Evidence: +11.4% CTR over 4,500 mobile visits."* |
| *"Why did Nexus recommend that?"* | `get_intelligence_log()` | *"🧠 Nexus Decision Reasoning Chain: Recommendation: Adopt 'Autonomous Intelligence...' (Confidence: 94.0%)..."* |
| *"What has Nexus learned?"* | `get_strategy_performance()` | *"📈 Nexus Growth Learnings: ✅ Dynamic Social Proof Badging (+14.8% lift) • ❌ Aggressive Exit-Intent Popup (-6.4%)."* |
| *"Run website health check"* | `run_website_health_check()` | *"🏥 Website Operational Audit: Status is HEALTHY (98.6/100). API Gateway: ONLINE (Port 8002)..."* |

---

## 🛡️ 3. Nexus Supervisor Operator (30-Second Polling)

The `NexusSupervisorOperator` monitors Nexus every 30 seconds and fires 5 classes of alerts:
1. **New Website Incident**: Emits voice alert with severity rating (*"🚨 Attention: New website incident [CRITICAL] detected..."*).
2. **High-Intent Lead Detected**: Emits notification when a visitor intent score exceeds **$0.80$** with key behavioral evidence.
3. **Pending Approval Stale**: Reminds the operator when optimization actions have been pending for **$> 30\text{ minutes}$**.
4. **Conversion Rate Anomaly**: Triggers proactive voice alert when conversion rate drops **$> 15\%$** below baseline (*"⚠️ Conversion rate dropped 18.4% below baseline. Would you like me to run an autonomous diagnosis?"*).
5. **Nexus Unreachable**: Triggers critical voice and system alerts when Nexus is unreachable for **$> 2\text{ minutes}$**.

---

## 🔒 4. Trust Level Invariant: UNTRUSTED_EXTERNAL

All data originating from external web visitors, sessions, form submissions, or third-party tracking is tagged with `TrustLevel.UNTRUSTED_EXTERNAL`. This guarantees that:
- Untrusted web payloads cannot elevate execution permissions.
- Prompt injection vectors embedded in URLs, referrer headers, or form fields are sanitized.
