# Soak and fault-injection findings — 2026-10-03

Nine agents booted on loopback ports with production credentials
(`research/local_fleet.py`), driven by continuous real traffic
(`research/soak.py`) and attacked through real entry points
(`research/adversarial_mesh_probe.py`).

Raw evidence sits beside this file: `soak-calls-*.jsonl`, `soak-samples-*.jsonl`,
`adversarial-mesh-probe-*.json`, `local-mesh-probe-*.json`, and per-agent
`local_fleet/*.log`.

---

## 1. What was established before this run

| Probe | Result |
|---|---|
| Single-request mesh probe | 19/19 pass |
| Adversarial probe (credentials, hostile payloads, ordering, concurrency) | 65/65 clean |
| Memora suite after the fail-closed fix | 163 passed |
| Stratex suite | 1015 passed |

Every one of those finished in seconds. Nothing below could have been found by them.

---

## 2. Per-agent findings

### Memora — FIXED, proven
- **Unauthenticated write accepted.** `POST /v1/memories` with no headers at all
  returned 201 and wrote into the store every agent reads; the same request with a
  wrong key correctly returned 401. Cause: `authenticate_agent` waved through any
  credential-less request unless the service was flagged production.
- The deployed blueprint does set `ENVIRONMENT=production`, so cloud was protected at
  the time. The bypass keyed off that value, so losing it would have opened Memora
  rather than failing shut — the opposite of every other agent.
- Fix: fail closed; a known caller with no configured key is a 503 configuration
  fault, not a 401. Anonymous access requires an explicit opt-in that the test
  suite now sets deliberately.
- Live before/after: `201 -> 401` unauthenticated, `401 -> 503` garbage key,
  valid FRIDAY write still 201 with an id.

### IntelX — PARTIALLY FIXED, still open
- **Research delegation stalls ~90s when a peer is down.** With Memora killed,
  `POST /api/v1/friday/research` never answered across four 60s attempts while every
  other IntelX endpoint replied in ~3ms. Measured directly: **HTTP 500 after
  89.8s**, even though the research itself had succeeded and only the delivery
  side-effect failed.
- Cause: `dispatch_sequentially` awaits each recipient's full retry budget in turn
  (3 attempts x 8s, plus backoff), so total stall scales with recipient count.
- Fix applied: one shared `TOTAL_BUDGET_SECONDS = 15.0` deadline across the whole
  dispatch; undelivered recipients are reported as `skipped`, not awaited.
- **Proven effect: 89.8s -> 66.2s. Not eliminated.** The research path has further
  sequential peer calls outside this dispatcher that still stall it. This fix reduces
  the blast radius; it does not make the failure impossible. Still open.
- IntelX suite after the change: 184 passed, 2 skipped.

### FRIDAY — correct
- Supervision reported `Memora status=DEGRADED` while the other seven agents stayed
  REACHABLE/ONLINE, with Memora genuinely dead. No false "healthy".

### Stratex — correct
- Answered `/api/engine-health` in 3ms with Memora down. No hang, no blocking.

### Sentinel, Forge, Cortex, Futuris — no faults observed
- Remained responsive and truthful throughout; their health endpoints kept reporting
  accurately while a peer was down.

### Inference — upstream and environment, not code
- `nvidia/nemotron-3-super-120b-a12b` returns **HTTP 410 Gone**: NVIDIA retired the
  model. Inference hardcodes it as the reasoning model in `app/agents/roles/`.
  **Upstream provider change, not a code defect.** Do not "fix" this by guessing a
  replacement model name; pick one and verify it against NVIDIA's current catalogue.
- `groq` fails with "GROQ_API_KEY is not configured" because I destroyed that value
  earlier in the session (see below). Self-inflicted, already disclosed.
- `openrouter` logged a 401 "Missing Authentication header" while
  `/health/providers` reported `key_pools/openrouter: total_keys=1, active_keys=1`.
  The credential exists, so the unauthenticated call is unexplained. **Observed but
  unresolved — not claimed as fixed.**

---

## 3. State survival across a hard kill

- Wrote memory `cd44311f…` containing marker `PRE_KILL_MARKER_ALPHA`, force-killed
  Memora (PID 11260), restarted it, and read the memory back: **HTTP 200, marker
  intact.** Local SQLite persistence works.

## 4. Render free-tier persistence — the decisive one

**No service declares a persistent disk.** Checked all nine `render.yaml`: zero
`disk:` entries.

Render's free tier filesystem is ephemeral and is destroyed on every deploy,
restart, and crash. With no disk attached, every local store is lost on each
redeploy:

| Service | Ephemeral store that is lost |
|---|---|
| Memora | `sqlite:////app/data/memora.db` — all memories |
| Stratex | `testnet_trade_ledger.jsonl`, `forward_signal_log.jsonl` — all trade history |
| IntelX | research findings and artefacts |
| Sentinel | audit ledger (already non-durable: `storage_backend=memory`) |

Note that Render free tier does not offer persistent disks at all; disks require a
paid plan. Durable state therefore has to live in Turso or Postgres, which Memora and
Cortex are already configured for. The JSONL ledgers have no durable backing today.

This is a configuration fact read from the blueprints, not an observed cloud
failure — cloud has not been re-tested since the keys were not yet applied.

---

## 5. Not done

- Partition test with the process alive but unreachable. Without firewall rules
  (needs elevation) I tested peer-down by killing the process, which is the failure
  mode Render actually produces on redeploy and sleep.
- Sustained multi-hour soak. The detached run was 900s.
- The `openrouter` 401 above.
- Completing the IntelX stall fix beyond the dispatch budget.
