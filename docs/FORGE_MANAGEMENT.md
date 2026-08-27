# 🛠️ FORGE Task Manager & Deep Integration Manual

This document details the architecture, managerial role, REST endpoints, task template expansions, 60s lifecycle supervision, deliverable reviews, and health monitoring for **FORGE (Autonomous Software Engineering Engine)** in the **FRIDAY Operating System**.

---

## 🏛️ Architecture & Managerial Boundary

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Voice Requests ("Forge, build me a portfolio website")│
│     • Review Approvals & Cancellation Gating                │
└──────────────────────────────▲──────────────────────────────┘
                               │ Voice Commands / SENSITIVE Approvals
┌──────────────────────────────▼──────────────────────────────┐
│                  FRIDAY: FORGE's Manager                    │
├──────────────────────────────┬──────────────────────────────┤
│  ForgeManagerSkill           │  ForgeTemplateLibrary        │
│  • submit_build_request      │  • WEBSITE / CLI_TOOL        │
│  • get_task_status / logs    │  • API_SERVICE / DASHBOARD   │
│  • inspect_task / artifacts  │  • SCRIPT / Custom           │
├──────────────────────────────┼──────────────────────────────┤
│  ForgeSupervisorOperator     │  ForgeReviewWorkflow         │
│  • 60s Lifecycle Watchdog    │  • Artifact Summaries        │
│  • State Transitions Audit   │  • Test Coverage Audit       │
│  • Delay & Failure Alerts    │  • Spoken Deliverable Review │
├──────────────────────────────┼──────────────────────────────┤
│  ForgeHealthOperator         │  FridayDoctor Integration    │
│  • 5m Service Uptime Check   │  • Subsystem Health Audit    │
│  • AI-Universe Bridge Check  │  • Remediation Diagnostics   │
└──────────────────────────────┬──────────────────────────────┘
                               │ HMAC-SHA256 Signed REST API
┌──────────────────────────────▼──────────────────────────────┐
│          FORGE Autonomous Software Engineering Engine       │
│   (Autonomous Planning, Coding, Verification & Packaging)   │
└─────────────────────────────────────────────────────────────┘
```

### Option A: Strict Hub-and-Spoke Invariants:
1. **FORGE Knows ONLY AI-Universe**: FORGE is fueled by AI-Universe's reasoning and API keys; FORGE does **NOT** know FRIDAY exists and FORGE's code never mentions FRIDAY.
2. **FRIDAY is the Sole Hub**: FRIDAY pulls telemetry and task results from FORGE's REST API; FORGE never pushes to FRIDAY.
3. **Context Injection at Submission**: All multi-system context injection (e.g. trading bot API specifications) happens at task submission time inside the goal payload.
4. **FRIDAY NEVER Writes Code Itself**: All software building is delegated to FORGE. FRIDAY acts strictly as the manager (templating, scheduling, supervising, and verifying).
5. **Untrusted Memory Isolation**: All FORGE responses, inspection reports, and task artifacts are tagged `TrustLevel.UNTRUSTED_EXTERNAL`.
6. **Capability Gating**: Submitting build requests and cancelling tasks require `forge_control` and `network_access` capabilities.

---

## 🎙️ Voice Command Reference

### SAFE Commands (No Auth Required):
- `"Forge status"` $\to$ Overall FORGE health, active builds count, completed deliverables count.
- `"What tasks has Forge been assigned?"` $\to$ List of recent software tasks with state and progress %.
- `"How is the website build going?"` $\to$ Real-time status of the matching task description.
- `"Show me what Forge built"` $\to$ Inspection of the latest completed build deliverable.
- `"Forge logs"` $\to$ Readout of the latest execution logs from the active build pipeline.
- `"What did Forge deliver?"` $\to$ Summary of completed artifact packages and verification manifests.

### SENSITIVE Commands (`forge_control` Capability Gated):
- `"Ask Forge to build [goal description]"` / `"Forge, build me a portfolio website"` $\to$ Expands goal with structured template and submits build request.
- `"Cancel the Forge task"` $\to$ Cancels the currently running task.
- `"Forge, build a CLI tool for [description]"` $\to$ Expands using the CLI_TOOL template.
- `"Forge, build a FastAPI service for [description]"` $\to$ Expands using the API_SERVICE template.

---

## 📋 Task Templates Library

| Template Type | Target Output | Enriched Engineering Specification |
| :--- | :--- | :--- |
| **`WEBSITE`** | Responsive Web App | Semantic HTML5, modern CSS (Flexbox/Grid), vanilla JS, ARIA accessibility, dark mode toggle. |
| **`CLI_TOOL`** | Python CLI Utility | Argparse interface, JSON persistence, comprehensive error handling, and help documentation. |
| **`API_SERVICE`**| FastAPI Microservice| Pydantic v2 schemas, health endpoints, OpenAPI documentation, and pytest test suite. |
| **`DASHBOARD`**  | Real-Time UI | WebSocket live streaming, responsive charts, and component state managers. |
| **`SCRIPT`**     | Python Script | Modular functions, logging, CLI flags, and robust error handling. |

---

## ⚙️ Configuration Reference (.env)

```bash
# ============================ FORGE (AUTONOMOUS SWE ENGINE) ==============================
FORGE_BASE_URL=http://localhost:8000
FRIDAY_FORGE_API_URL=http://localhost:8000
FRIDAY_FORGE_API_KEY=your_forge_api_key_here
FORGE_ENABLED=True
FRIDAY_FORGE_ENABLED=true
FRIDAY_FORGE_MAX_CONCURRENT_TASKS=3
FRIDAY_FORGE_TASK_TIMEOUT=1800
FORGE_SUPERVISION_INTERVAL_SECONDS=60
FORGE_HEALTH_CHECK_INTERVAL_SECONDS=300
```
