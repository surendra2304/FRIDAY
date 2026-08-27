# 🌐 Nexus Website & Growth Engine Integration Manual

This document details the architecture, capability gating, voice commands, 60-second vigilance operator, and dashboard monitoring for **Nexus (Autonomous Website & Growth Engine)** in the **FRIDAY Operating System**.

---

## 🏛️ Architecture & Governance Invariants

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Voice Requests ("Website status", "Any leads?")       │
│     • Approval Reviews & Experiment Control                 │
└──────────────────────────────▲──────────────────────────────┘
                               │ Voice Commands / SENSITIVE Approvals
┌──────────────────────────────▼──────────────────────────────┐
│           FRIDAY Ecosystem Command Center                   │
├──────────────────────────────┬──────────────────────────────┤
│  NexusOperatorSkill          │  NexusVigilanceOperator      │
│  • get_site_status           │  • 60s Health & Incident Poll│
│  • get_high_intent_leads     │  • High-Intent Lead Alerts   │
│  • diagnose_conversion_drop  │  • Stale Approvals (>30m)    │
│  • explain_nexus_decision    │  • Outage Alarms (>2m)       │
├──────────────────────────────┼──────────────────────────────┤
│  EcosystemRegistry           │  EcosystemDashboardPanel     │
│  • Subsystem Entry: "nexus"  │  • Real-Time Growth Card     │
│  • Category: "growth" (🌐)   │  • Lead & Incident Feeds     │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST (GET /v1/friday/command)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│          Nexus Autonomous Website & Growth Engine           │
│   • Multi-Armed Bandit Growth Experiments                   │
│   • High-Intent Lead Identification Engine                  │
│   • Internal Policy Authorization Engine                    │
└──────────────────────────────▲──────────────────────────────┘
                               │ Reasoning Consultations
┌──────────────────────────────┴──────────────────────────────┐
│               AI-Universe Intelligence Core                 │
└─────────────────────────────────────────────────────────────┘
```

### Core Invariants:
1. **Nexus Policy Engine Compliance**: FRIDAY never bypasses Nexus's internal policy engine; all modifications and workflow triggers execute strictly through Nexus's authorization rules.
2. **Untrusted Memory Isolation**: All visitor telemetry, lead records, and diagnostic reports persisted to FRIDAY memory carry `TrustLevel.UNTRUSTED_EXTERNAL`.
3. **Capability Gating**: Inspecting and controlling Nexus operations requires `["network_access", "nexus_control"]` capabilities.

---

## 🎙️ Voice Command Reference

| Category | Natural Voice Command | Execution & Spoken Output |
| :--- | :--- | :--- |
| **SAFE** | `"Website status"` | *"Website Health Status: HEALTHY (98.4/100). Traffic today: 4,280 visitors \| Conversion rate: 3.65% \| Leads detected: 14 \| Active experiments: 2."* |
| **SAFE** | `"Any high-intent visitors?"` | Lists top detected enterprise leads with intent scores (e.g. Acme Corp, score 94/100) and behavioral dwell-time evidence. |
| **SAFE** | `"Why did conversions drop?"` | Triggers autonomous conversion drop diagnosis and reports root cause (e.g. Mobile Safari checkout layout shift). |
| **SAFE** | `"Any website incidents?"` | Reports active incidents with severity ratings (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`). |
| **SAFE** | `"Explain that Nexus decision"` | Reads out the complete multi-step reasoning chain and AI-Universe consultation consensus. |
| **SENSITIVE** | `"Pause the website experiment"` | Safely pauses the active growth experiment after operator confirmation. |

---

## ⚙️ Configuration Reference (.env)

```bash
# ============================ NEXUS (WEBSITE & GROWTH ENGINE) ==============================
NEXUS_BASE_URL=http://localhost:8002
NEXUS_ENABLED=True
NEXUS_VIGILANCE_INTERVAL_SECONDS=60
```
