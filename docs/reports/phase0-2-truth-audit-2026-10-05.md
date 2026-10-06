# FRIDAY — Phase 0–2 Truth Audit

**Date:** 2026-10-05
**Auditor:** Arena agent (principal engineer, sole owner of this repo for this session)
**Branch:** `arena/01a10cba-friday` @ `f64f8d6`
**Environment:** Linux (Debian, Python 3.11.2), fresh venv, **no outbound network egress**
**Verdict:** Phases 3–5 withheld pending owner go-ahead, per the brief.

> Every claim below is backed by a command that was actually run in this session. Where a
> claim could not be verified because of the sandbox's lack of network egress, it is
> labelled **CONFIGURED-BUT-UNVERIFIED** and the reason is stated.

---

## PHASE 0 — TOTAL COMPREHENSION

### (a) What this project IS, and its dream state

FRIDAY is **not** a chatbot repo. It is a **9-node personal AI operating system**: one local
Python "central OS" (`src/friday`, 85,092 LOC across 447 modules) plus eight cloud peer
microservices it supervises — Inference (LLM gateway), Memora (memory fabric), Stratex
(trading), IntelX (research), Futuris (forecasting), Cortex (web ops), Forge (software
engineering), Sentinel (security). A separate Next.js command centre lives in `ui/`, and a
second hardening package `src/friday_deep` (contracts, plan validator, tool firewall,
collaboration loop) provides zero-trust runtime invariants.

**The dream state** (read off the code, the diary, and `docs/DEEP_UPGRADE_ARCHITECTURE.md`,
and confirmed by the owner's stated goal at the end of the brief):

1. **An autonomous brain** — FRIDAY detects an error in its own code, its runtime, or any of
   the eight peer agents, and *fixes it itself*, without asking the owner.
2. **No refusals** — asked to do something it has never done, FRIDAY reasons like a human,
   composes the capability, and executes it, instead of reporting a missing capability.
3. **One connected mind per agent** — FRIDAY *and* all eight peers think, recall memories,
   talk to each other, repair their own systems, and help each other.

### (b) Request / execution flow, naming real files, classes and functions

Text/voice ingress → cognitive loop → tools → memory → response:

| # | Stage | Real code path |
|---|---|---|
| 1 | HTTP ingress | `src/friday/api/server.py::execute_command` (`POST /api/command`, line 638) behind `_require_control_access` (line 177). `/api/chat` (line 1022) is a thin alias. |
| 2 | Voice ingress | `src/friday/voice/gemini_live_session.py::GeminiLiveSession` ↔ `voice/gemini_provider.py`; tool calls cross into the same `FridayAgent`. |
| 3 | Deterministic fast paths | `src/friday/agent/agent.py::FridayAgent.chat` → `agent/mixins/fast_paths.py` (`FastPathMixin`): regex-matched commands (`"fix yourself"`, app launch, agent directives) bypass the LLM entirely. |
| 4 | Cognition | `agent/mixins/cognitive.py` (`CognitiveMixin`) → `agent/cognitive.py::CognitiveIntelligenceEngine` runs the 10 phases (`UNDERSTAND → … → COMPLETE`); `agent/state.py::ReasoningStateMachine` + `agent/goal.py` hold task state. |
| 5 | Provider call | `llm/factory.py::create_llm_provider` builds `FallbackChainLLMProvider` (`llm/fallback_chain_provider.py`) over Groq → Mistral → OpenRouter → AIUniverse; **Gemini is reserved for voice/vision/embeddings**. |
| 6 | Tool dispatch | `agent/mixins/tools.py::ToolExecutionMixin` → `tools/registry.py::ToolRegistry` → `tools/orchestrator.py`; each tool declares a `SafetyLevel` and is gated by `core/auth.py::DefaultSecureAuthorizer` (HMAC capability tokens) and `friday_deep/security/tool_firewall.py`. |
| 7 | Peer delegation | `autonomous/controller.py::AutonomousController.execute_agent_control` → `ecosystem/fleet_client.py::FleetClient.ask_*` over HTTP; `TaskEnvelope`/`TaskResult` in `core/task_envelope.py`. |
| 8 | Memory | `memory/factory.py::create_memory` → `memory/sqlite.py` (FTS5 + BM25 compaction) or `memory/memora_client.py` (cloud); trust tagging via `core/types.py::TrustLevel`. |
| 9 | Self-repair | `autonomous/repair_loop.py::AutonomousRepairLoop` (scheduler) → `autonomous/repair_trigger.py::RepairTrigger` (propose + review) → `autonomous/self_repair.py::SelfRepairGate` (approval + apply + rollback) → `POST /api/self-repair/*` in `api/server.py`. |

### (c) The five most important files

1. **`src/friday/agent/agent.py`** (865 LOC) + its four mixins — the agent itself; everything
   else exists to serve this class.
2. **`src/friday/api/server.py`** (1,262 LOC, 60+ routes) — the only always-on operational
   surface; it owns the cloud lifespan tasks (fleet supervision, Memora consumer, repair loop).
3. **`src/friday/autonomous/self_repair.py`** (1,064 LOC) — the security heart of the whole
   system: a fail-closed, receipt-emitting repair gate. Understanding its rules is a
   prerequisite for granting any autonomy.
4. **`src/friday/ecosystem/fleet_client.py`** (991 LOC) — the only channel to the eight peers;
   every "FRIDAY controls the fleet" claim resolves here.
5. **`src/friday/core/config.py`** (711 LOC) — 120+ settings and the legacy→`FRIDAY_*` alias
   map; most "works on my machine" bugs in this repo are config-default bugs.

### (d) What surprised me

1. **The repo's honesty culture is real and unusually rigorous.** Comments like *"a review
   must be a signed document, not a claimed identity"*, `evidence_class` fields on every
   receipt, and refusal enums instead of exceptions. This is not typical AI-hype code.
2. **…and it is exactly inverted where the owner needs it most.** The system is scrupulously
   honest about *not* doing things (`repairs_attempted: []`, `advisory_only: True`,
   `task_completion_verified: False`) — so it is *honest and useless* for the stated dream:
   it reports that it cannot repair instead of repairing.
3. **The prompt lies to the model.** `agent/prompts.py:94` and
   `voice/gemini_live_session.py:318` instruct: *"You MUST use the `SelfImprovementWorkflow` …
   Call the workflow tool"* — and that workflow is registered nowhere and instantiated
   nowhere in `src/` (proof in BUG-003).
4. **`friday_deep` is a second, parallel implementation** of planning/routing/memory/security
   that the main agent mostly does not use. Two cognitive architectures coexist.
5. **Duplicate route registration** in the single most important file (three paths registered
   twice). Classic sign of merges without a route-existence test.
6. **75 evidence artifacts are committed** under `reports_and_data/` but they are unreachable
   from any test — evidence of past work, not a safety net.

---

## PHASE 1 — TRUTH AUDIT

### 1.1 Install (fresh)

```
$ python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
error: externally-managed-environment          # Debian PEP-668 guard
$ .venv/bin/pip install -e ".[dev]"
      cbits/pywebrtcvad.c:1:10: fatal error: Python.h: No such file or directory
      ERROR: Failed building wheel for webrtcvad
      Failed to build webrtcvad
      error: failed-wheel-build-for-install
```

**Result: `pip install -e ".[dev]"` FAILS on a clean Linux box** because `resemblyzer`
(pulled in unconditionally for voice biometrics) has no wheel and its C extension needs
`python3-dev`. GitHub's `ubuntu-latest` runner happens to ship the headers, so CI masks this.
I installed the remaining 26 dependencies + the package itself:

```
Successfully installed PyGithub-2.10.0 ... uvicorn-0.54.0 uvloop-0.23.0 ... (chromadb, google-genai, fastapi, …)
Successfully installed friday-agent-0.1.0
friday import OK /home/user/FRIDAY/src/friday/__init__.py
```

Then, to match CI exactly (`pip install -e ".[dev,browser]"`):

```
$ .venv/bin/pip install "browser-use>=0.1.0" "playwright>=1.40.0"
Successfully installed ... browser-use-0.13.10 playwright-1.63.0 ...
# side effect: this DOWNGRADES google-genai 2.28.0 -> 1.65.0 and openai 3.24.0 -> 2.26.0
```

### 1.2 Linter

```
$ python -m ruff check src/ tests/
All checks passed!
```

### 1.3 Type checker

```
$ python -m mypy src/
Success: no issues found in 447 source files
```

### 1.4 Full test suite (CI's exact selection)

```
$ python -m pytest -m "not live and not hardware and not windows" -q
1 failed, 1629 passed, 6 skipped, 23 deselected in 116.76s
  FAILED tests/test_browser_use_integration.py::test_browser_use_executor_availability
    assert executor.has_playwright_package is True   # playwright not yet installed by me
```

After installing the `browser` extra that CI installs:

```
$ python -m pytest -m "not live and not hardware and not windows" -q
1630 passed, 6 skipped, 23 deselected in 119.01s
```

**No test was modified, skipped or weakened.** The single failure was my incomplete install.
Collection totals: **1,659 tests** (1,642 portable, 10 `windows`, plus `live`/`hardware`).

### 1.5 Module import smoke test (all 431 modules)

```
discovered 431 modules
FAILED IMPORTS: 3
  friday.desktop.app: ModuleNotFoundError: No module named 'PyQt6'
  friday.desktop.orb: ModuleNotFoundError: No module named 'PyQt6'
  friday.desktop.window: ModuleNotFoundError: No module named 'PyQt6'
```

### 1.6 Boot test — the app runs

```
$ python -m uvicorn friday.api.server:app --host 0.0.0.0 --port 8811
INFO:     Application startup complete.
Native SAPI TTS could not initialize COM speaker: No module named 'pythoncom'   # Linux: expected
INFO:     Uvicorn running on http://0.0.0.0:8811
```

Route sweep (`curl` against the live process):

| Endpoint | Result |
|---|---|
| `/health`, `/api/health` | 200, `{"overall":"healthy","evidence_class":"process_liveness",…}` |
| `/api/tools` | 200, 37,807 B tool catalog |
| `/api/agents`, `/api/agents/status`, `/api/agents/supervision` | 200 |
| `/api/autonomous/status` | 200, `{"autonomous_mode":true,…}` |
| `/api/self-repair/autonomous` | 200, `status: NOT_STARTED`, `missing: [5 env vars]` |
| `/api/diagnostics`, `/api/proactive`, `/api/telemetry`, `/api/system_telemetry` | 200 |
| `/api/chat` `"what is the system time"` | 200, correct answer via fast path |

The full cognitive path (`POST /api/command`) fails **only** because this sandbox has no
network egress:

```
$ curl -s https://example.com -o /dev/null -w "%{http_code}"
000        # no egress; DNS resolves, TCP/TLS is blocked
{"reply":"LLM generation failed. … AI Universe communication error: TLS/SSL connection has been closed (EOF)"…}
```

So: **local execution, fast paths, memory, tools, diagnostics, API — REAL and running.
Every cloud-peer behaviour in this repo — CONFIGURED-BUT-UNVERIFIED (no egress from this sandbox).**

### 1.7 Docs vs reality

Documented and **real** (verified by execution): CLI `friday --doctor` (full diagnostic
report, exit 0), the FastAPI surface, tiered safety gating + `SecretScrubber`, SQLite memory
with FTS5, the gated repair pipeline endpoints, the 1,630-test suite, ruff/mypy cleanliness.

Documented but **not real / not wired** (details in Phase 2): the fleet-delegation claim
(6 of 8 `ask_*` methods are health probes), `SelfImprovementWorkflow` (prompt says "you MUST
call it"; nothing registers it), `SelfHealingWorkflow` (dead code, 0 references), module-level
`OFFLINE` peer status (never assigned), `friday-desktop` entry point (PyQt6 undeclared).

Working but **undocumented**: `friday_deep/` — an entire second runtime-hardening package
(plan validator, tool firewall, A2A/MCP bridges, collaboration loop) absent from the README
capability matrix.

---

## PHASE 2 — BUG HUNT

### CRITICAL

#### BUG-001 — Unauthenticated local control API + origin-reflecting CORS = drive-by command execution from any web page

- **File:** `src/friday/api/server.py:161-175` (CORS) and `:177-200` (`_require_control_access`)
- **Root cause:** two independent weaknesses that compose:
  1. `allow_origins=["*"]` **with** `allow_credentials=True` makes Starlette *reflect any
     requesting origin* (it cannot send a literal `*` alongside credentials), so there is no
     origin allow-list at all.
  2. `_require_control_access` returns early for loopback clients:
     `client_is_remote = not ipaddress.ip_address(client_host).is_loopback` → `if not remotely_exposed: return`.
     A page in the owner's own browser *is* a loopback client.
- **Reproduction / evidence (actually run):**

```
$ curl -s -i -X OPTIONS http://127.0.0.1:8811/api/command \
      -H "Origin: https://attacker.example" -H "Access-Control-Request-Method: POST" \
      -H "Access-Control-Request-Headers: content-type" -D - -o /dev/null
HTTP/1.1 200 OK
access-control-allow-origin: https://attacker.example
access-control-allow-credentials: true
access-control-allow-headers: content-type

$ curl -s -X POST http://127.0.0.1:8811/api/command -H "Origin: https://attacker.example" \
      -H "Content-Type: application/json" -d '{"command":"fix yourself"}'
{"reply":"FRIDAY diagnostic: UNVERIFIED. 2/3 local checks passed. …","metadata":{"autonomous":true,…}}

$ curl -s -X POST http://127.0.0.1:8811/api/screenshot -H "Origin: https://attacker.example"
{"reply":"Snipping Tool activated.","metadata":{"action":"screenshot","success":true,…}}
```

  A **foreign origin with no credential executed local actions** on the host. With real LLM
  keys configured (the owner's actual setup) the same request reaches the full tool surface,
  including `execute_command`, file writes and desktop control. `allow_origins=["*"]` also
  defeats the module docstring's claim that CORS exists so the WebGL frontend "can connect".
- **Proposed fix (surgical):** replace wildcard with an explicit origin allow-list from
  config (default: the UI's own origin(s) + `null`-free) and set `allow_credentials=False`;
  in `_require_control_access`, require the API key for every state-changing request even
  from loopback (loopback exemption only for idempotent GET/HEAD); reject requests whose
  `Origin` header is present and not allow-listed. Add a regression test that fails if
  `/api/command` accepts a foreign `Origin` without a key.

### HIGH

#### BUG-002 — The "autonomous brain" is a *reporting* brain: it cannot repair anything, and the repair loop is inert by default

- **Files:** `autonomous/controller.py:343-402` (`execute_self_repair`),
  `:288-336` (`autonomous_failover`), `:102` (`self.enabled = True` hardcoded),
  `autonomous/self_repair.py:53-79` (`NON_OWNER_ACTORS`), `autonomous/repair_loop.py:106-120`
  (`missing()`)
- **Root cause:** three independent brakes, each deliberate:
  1. `execute_self_repair`'s own docstring: *"This routine deliberately does not kill
     processes, clear caches, or edit source code … No repair was attempted."* It returns
     `"repairs_attempted": []` **always**.
  2. `autonomous_failover` is `advisory_only: True` / `"no retry or external action was performed"`.
  3. The real repair pipeline (`SelfRepairGate`) can only reach `REVIEWED`; `apply` requires a
     human approver, and `NON_OWNER_ACTORS` denies `friday`, `forge`, `sentinel` and every
     other agent by name *and* by default for future agents. The unattended loop also refuses
     to run at all unless **five** env vars are set.
- **Evidence (live process):**

```
$ curl -s http://127.0.0.1:8811/api/self-repair/autonomous
{"running":true,"enabled":false,"interval_seconds":900,"status":"NOT_STARTED",
 "missing":["FRIDAY_SELF_REPAIR_TRIGGER_ENABLED","FRIDAY_SELF_REPAIR_WATCHLIST",
            "FRIDAY_SELF_REPAIR_GATE_URL","FRIDAY_SELF_REPAIR_GATE_KEY","FRIDAY_SELF_REPAIR_REVIEW_KEY"]}

$ curl -s -X POST …/api/command -d '{"command":"fix yourself"}'
… "repairs_attempted":[],"success":false
```

  This is precisely the owner's complaint: *"when there is any error … it should be able to
  fix all of them by itself without asking me."* Today it reports and stops.
- **Proposed fix:** an owner-signed **standing autonomy mandate** (see Phase 4 plan) that
  admits a bounded, test-proven, auto-rollback class of repairs to the existing gate, plus a
  working reflex loop that classifies an incident and *acts*. Report-only stays the fallback
  when a repair cannot be proven.

#### BUG-003 — The system prompt orders the model to call a tool that does not exist

- **Files:** `agent/prompts.py:94`, `voice/gemini_live_session.py:318` (the instruction);
  `workflows/self_improve_workflow.py::SelfImprovementWorkflow` (the target);
  `tools/registry.py`, `agent/mixins/tools.py` (where it is absent)
- **Root cause:** `"If the user asks you to modify your own codebase … you MUST use the
  `SelfImprovementWorkflow` … Call the workflow tool."` No tool named for it is registered,
  and `SelfImprovementWorkflow` is never instantiated in `src/` — only imported by
  `workflows/__init__.py` and exercised by tests.
- **Evidence:**

```
$ grep -rn "SelfImprovement" src/friday/tools src/friday/skills --include='*.py'
(no output)
$ python - <<'PY'   # reference scan across src/, excluding the defining file
SelfImprovementWorkflow   src/friday/workflows/self_improve_workflow.py   refs_in_src=4 (export+docstring)  refs_in_tests=7
SelfHealingWorkflow       src/friday/workflows/self_healing_workflow.py   refs_in_src=0                    refs_in_tests=0
PY
```

  The model is therefore told to make a phantom call — so asking FRIDAY to gain a capability
  produces a hallucinated tool call or a failure, never work. Same class: `SelfHealingWorkflow`
  has **zero** references anywhere, including tests.
- **Proposed fix:** register both workflows as real, safety-classified tools
  (`self_improve`, `self_heal`), route them through `SelfDevAgent` + `RunTestsTool` +
  `WriteCodeFileTool`, and give them the same evidence discipline as the repair gate.

#### BUG-004 — "Delegating work to the 8 agents" is a status probe, and success is never verified

- **Files:** `ecosystem/fleet_client.py:512-770` (`ask_stratex/intelx/futuris/cortex/forge/sentinel`
  hit `/api/engine-health`, `/api/v1/healthz`, `/v1/friday/calibration`,
  `/v1/friday/health_summary`, `/api/v1/analytics/summary` + `/api/v1/tasks`,
  `/api/v1/friday/posture` — **all read-only health/status**), `:413-458`
  (`ask_inference` sets `"consensus_reached": True` on any HTTP 200, `max_tokens: 60`),
  `autonomous/controller.py:238-288` (formats a health body as `[AGENT RESPONSE: X]` and
  returns `success: False, task_completion_verified: False` unconditionally).
- **Evidence:** the section header at `fleet_client.py:457` reads
  `"2. LIVE SPECIALIST AGENT EXECUTION (100% REAL DATA, ZERO MOCK)"` while the six methods it
  introduces never dispatch a task. Live run: `ask_*` produced only health payloads.
- **Proposed fix:** a typed peer task channel — `TaskEnvelope` in, async receipt + polling
  `TaskResult` out, with per-peer capability discovery and a completion verifier. Delegation
  must report `SUCCESS` only on a completion receipt.

#### BUG-005 — Evidence inversion: "8 responses OBSERVED" when all 8 peers failed to connect

- **Files:** `autonomous/controller.py:363-370` (builds the check from
  `len(fleet_statuses)`), `ecosystem/fleet_client.py:381-411` (`get_all_statuses` returns an
  `AgentStatus` for *every* peer including exception-constructed `DEGRADED` ones)
- **Evidence (live):**

```
$ curl -s http://127.0.0.1:8811/api/agents/status | jq .status_counts
{ "ONLINE": 0, "DEGRADED": 8, "OFFLINE": 0 }      # every probe raised a connection error
$ curl -s -X POST …/api/command -d '{"command":"fix yourself"}'
… {"name":"peer_health_endpoints","status":"OBSERVED",
   "evidence":{"responses":8,"status_counts":{"DEGRADED":8}}}      # reads as "8 peers answered"
```

  Additionally `"OFFLINE"` is documented (module docstring, README) but **never assigned** —
  `grep -n '"OFFLINE"' src/friday/ecosystem/fleet_client.py` returns nothing — so
  *"the peer told us it is unhealthy"* and *"we could not reach the peer at all"* are the same
  value. In a repo whose entire value proposition is honest evidence, this is a correctness
  bug, not cosmetics.
- **Proposed fix:** split `UNREACHABLE` from `DEGRADED`; count only transport-successful
  responses in `responses`; add `unreachable: N` to the evidence dict.

### MEDIUM

| ID | File + line | Root cause | Evidence | Proposed fix |
|---|---|---|---|---|
| BUG-006 | `api/server.py:946`, `:976`, `:1001` | Three routes registered twice (`/api/android`, `/api/system_telemetry`, `/api/telemetry`). Starlette matches in registration order, so the **second handler of each pair is dead code** — including a Windows-only implementation (`os.path.splitdrive(...) + "C:\\"`) that can never run on Linux. | `grep -n '@app.*"/api/telemetry"' → 232, 1001`; live `/api/telemetry` returned the *first* handler's shape (`battery_available`), never the second's (`storage_usage`) | Delete the two dead handlers; keep one implementation per path. Add a route-uniqueness test over `app.routes`. |
| BUG-007 | `core/config.py:610`, `llm/factory.py:50` & `:70` | The Inference/AI-Universe provider defaults to the **Forge** URL (`https://forge-e9kl.onrender.com`) in three places, while `config.inference_url` (line 328) correctly defaults to `inference-h7bn`. When `inference_url` is blank, FRIDAY's "intelligence core" silently talks to the software-engineering engine. | `config.py:610 default="https://forge-e9kl.onrender.com"` with `description="Alias for Inference Core API"`; `SYSTEM_MANIFEST.md` maps `INFERENCE_URL=https://inference-h7bn.onrender.com` | Point all three at `inference_url`; delete the duplicated literals. |
| BUG-008 | `autonomous/controller.py:102` vs `core/config.py:179`, `.env.example:118` | Two sources of truth for autonomous mode. Controller hardcodes `self.enabled = True  # Enabled by default per user directive`; config defaults `autonomous_mode=False` and the documented env comment says *"Keep owner actions and full-access bypass disabled by default."* `toggle()` is in-memory only, so the switch is lost on restart, and `/api/command` announces *"Autonomous Mode is now ACTIVE … control all 8 specialist agents"*. | live `/api/autonomous/status` → `{"autonomous_mode": true}` with no env var set | Read `settings.autonomous_mode` at construction; persist the toggle (or make it explicitly ephemeral in the API response). |
| BUG-009 | `pyproject.toml:12-35`, `:69` | `resemblyzer` is an unconditional dependency with no portable wheel; `pip install -e .` fails on any Linux host without `python3-dev`. Separately, `[project.scripts] friday-desktop = "friday.desktop.app:run_desktop_app"` requires **PyQt6**, which is declared in no dependency list, so that entry point cannot work after a fresh install. | install log above; import smoke test (3 modules fail) | Move `resemblyzer` behind an extra (`voice-bio`) or a `sys_platform == 'win32'`-independent optional group; add a `desktop` extra containing `PyQt6`. |
| BUG-010 | `memory/` + `agent/agent.py:460` | Failed tool-call artifacts are persisted as long-term memory. Live recall for a brand-new question returned `role:"tool"`, `content:"Error: Duplicate tool call ID 'tc1' ignored."` and `'call_loop'`, with negative BM25 scores. Error strings are memory pollution: they consume recall budget and re-inject failures into context. | the `recalled_memories` array in the `/api/command` response above | Filter non-informative tool errors (duplicate-ID / repeat-guard notices) out of the memory write path; keep them in traces. |
| BUG-011 | `autonomous/self_repair.py:53-79` | `NON_OWNER_ACTORS` is an allow-by-default deny-list keyed on actor *name*. A new agent added tomorrow is admitted unless someone remembers to edit this set — the comment claims the opposite ("excluded by default rather than admitted by omission"). | the set lists 15 literals; membership is by string equality with `approver.strip().lower()` | Invert it: only a positively-identified owner (*not* in the agent namespace) may approve. |

### LOW

| ID | File | Finding |
|---|---|---|
| BUG-012 | `api/server.py:638`, `:1022` | Failure responses return **HTTP 200** with `success:false` in the body (verified live). Callers cannot distinguish a refused command from a completed one without parsing metadata. |
| BUG-013 | `ecosystem/fleet_client.py:75` | `_shared_client` is a lazily-created `httpx.AsyncClient` never closed on shutdown → socket/loop-resource leak on reload. |
| BUG-014 | `ecosystem/fleet_client.py:450` | `max_tokens: 60` for the inference fast lane is too small for anything but a status quip; `consensus_reached: True` is asserted without comparing multiple models. |
| BUG-015 | `docs/FRIDAY_KNOWN_ISSUES.md` | Register has 3 entries (all Low/Medium, stale); it records none of the findings above. |
| BUG-016 | `reports_and_data/` (75 tracked files) | Committed run artifacts with no test or doc referencing them; they will drift silently. |

### Deliberately *not* reported as bugs

- Missing LLM keys, no audio hardware, `pythoncom`/SAPI absence and every peer failure in this
  sandbox are **environmental** (no egress: `curl https://example.com` → `000`).
- `windows`-marked tests failing on Linux is by design (`-m "not windows"` in CI).
- The 6 skips are marker-driven (`pytest.mark.skipif` for a local contract stack + Windows input).

---

## Summary

| Category | Count |
|---|---|
| CRITICAL | 1 (BUG-001) |
| HIGH | 4 (BUG-002 … BUG-005) |
| MEDIUM | 6 (BUG-006 … BUG-011) |
| LOW | 5 (BUG-012 … BUG-016) |

**The single sentence that matters:** FRIDAY has an excellent safety cage and almost no animal
inside it. Every mechanism the owner asked for — self-repair, capability synthesis, verified
peer delegation, shared memory — exists as a *scaffold that reports honestly that it did
nothing*. The audit found no fake results and no hidden secrets (the repo's own
`security_check.py` passes: *"zero tracked .env files and zero genuine hardcoded secrets"*),
which means the work ahead is wiring and finishing, not demolition.

**Awaiting owner decision on Phases 3–4 (see the accompanying plan).**
