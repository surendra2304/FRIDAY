# Cross-agent stall audit — 2026-10-04

Sweep of all nine agents for the four patterns behind the 90-second stall:
(a) a caller that awaits peers serially, (b) unbounded or excessive retry
backoff, (c) no client timeout, (d) a lock held across slow external I/O.

"Cost with peer down" is measured where the path could be driven live; otherwise
it is computed from the configured timeouts and marked as computed.

## Defects fixed this pass

### IntelX — writer lock held across synthesis on the primary path (commit `1ca73d8`)

The commit-before-synthesis fix had only ever been applied to the
`REVIEW_REQUIRED` resumption path. The primary path at
`intelx/orchestration/engine.py` transitioned the run to `SYNTHESIZING` and then
called the synthesizer in the same uncommitted session — the path real
submissions actually take. The existing regression test only matched the *first*
`RunStatus.SYNTHESIZING` in the file, so it passed while the primary path was
still broken.

The ordering test now checks every SYNTHESIZING→synthesizer window and asserts
there are at least two. A second test drives `execute_run` end to end with a
stand-in synthesizer and times a competing SQLite writer while it runs.

| Scenario | Before | After |
|---|---|---|
| 5 concurrent submissions, 3 peers killed | 5.5s / 10.8s / 16.3s / 21.6s / client-timeout (all HTTP 500) | 5 × HTTP 201 in ~9ms |
| Reverting the primary-path commit | test passes vacuously | **2 tests fail**; competing writer blocked 3.36s |
| Full IntelX suite | — | 191 passed, 2 skipped |
| `test_research_write_deadline.py` × 5 | — | 7 passed each run (6.45–6.59s) |

### Futuris — one dead peer cost a full refresh cycle (commit `7aa2fcf`)

`POST /v1/predictions/refresh-all` generated all 18 universe targets in a serial
loop, each making an outbound IntelX context call. `futuris/connectors/intelx_context.py`
also caught `httpx.RequestError` and then retried a *different endpoint on the
same host* — which cannot succeed when the transport itself failed, and doubled
the wait for every target.

| Measurement | Before | After |
|---|---|---|
| `refresh-all`, fleet healthy | 6.88s | unchanged |
| `refresh-all`, IntelX killed | **61.03s** | 15.38s / 15.27s (bounded) |

Futuris suite: 167 passed.

## Full audit table

| # | Agent | File:line | Pattern | Live? | Cost with peer down | Verdict |
|---|---|---|---|---|---|---|
| 1 | IntelX | `intelx/orchestration/engine.py:504` (now 509) | d — DB lock across slow I/O | **Yes** | Serialized every other writer; 5 concurrent submissions → 5×500 over 5.5–21.6s | **Fixed** |
| 2 | IntelX | `intelx/integrations/ecosystem_dispatch.py:38` | a — serial peer awaits | Yes | Was 3 × peer timeout; bounded by `TOTAL_BUDGET_SECONDS = 15.0` | **Fixed earlier** (`bcffc2a`) |
| 3 | IntelX | `intelx/api/v1/friday.py:496` | d — `asyncio.Lock` over `session.commit()` | Yes | Serializes only the run-creation write | **Correct as-is** |
| 4 | Futuris | `futuris/api/routers/predictions.py:483` | a — 16 serial targets, each an IntelX call | **Yes** | **61.03s measured** | **Fixed** |
| 5 | Futuris | `futuris/api/routers/predictions.py:375` | a — same loop in `GET /matrix`, fills only missing targets | Yes | 61.0s on a cold store; ~0.4s warm | **Fixed** (same budget) |
| 6 | Futuris | `futuris/connectors/intelx_context.py:106` | a — retries a 2nd endpoint on a dead host | Yes | Doubled every dead-peer wait (1.5s→3s × 16) | **Fixed** |
| 7 | Futuris | `futuris/integrations/friday_client.py:73,92,111` | c — `AsyncClient` with no explicit timeout | **No** — module referenced nowhere else in the package | httpx default 5.0s if ever wired up | **Dead code** |
| 8 | Sentinel | `sentinel/integrations/intelx_client.py:71` | a — 2 candidates, same host, 8s each | **Yes** (imported at `apps/api/main.py:1102`) | **16s** computed (2 × 8.0s) | **Structural** — same shape as #4; needs the transport-error rule |
| 9 | Sentinel | `sentinel/integrations/friday/client.py:27,33,39,52` | c — 30s timeouts | Yes | 30s per call | **Structural** — too long for a free-tier peer |
| 10 | Sentinel | `sentinel/core/intelligence/llm_provider.py:102` | b — `max_retries + 1` attempts, no backoff sleep | Yes | 3 × `self._timeout` | Bounded; **acceptable** |
| 11 | FRIDAY | `src/friday/ecosystem/fleet_client.py:388-398` | a — 8 peer probes | Yes | **`asyncio.gather`**, 3.5s worst case | **Correct** — concurrent |
| 12 | FRIDAY | `src/friday/autonomous/controller.py:349` | d — `_repair_lock` held across `get_all_statuses` | **Yes** (`POST /api/autonomous/repair`; also called from the chat exception handler at `server.py:938`) | **3.44–3.50s measured** with 5 peers down (healthy 2.55–4.70s) | **Structural** — bounded, but serializes concurrent repairs |
| 13 | FRIDAY | `src/friday/core/service_registry.py:249` | a — 8 services probed serially at startup | Startup only | 29s computed (4+4+4+4+5+4+2+2) | **Structural** — startup path, not a request |
| 14 | FRIDAY | `src/friday/ecosystem/fleet_client.py:595` | a — local→cloud fail-over | Yes | 1.5s + 2.5s = 4s | **Acceptable** — bounded fail-over |
| 15 | Stratex | `intelligence/intelx_client.py:88,111` | a — 2 sequential calls, same host, 5s each | Yes | 10s computed | **Structural** — same shape as #8 |
| 16 | Stratex | `intelligence/futuris_client.py:56,95` | d — lock around cache only, **not** the network call | Yes | 3.0s per call | **Correct** — the pattern done right |
| 17 | Stratex | `intelligence/prediction_client.py:68` | c — explicit 5s | Yes | 5s | **Acceptable** |
| 18 | Stratex | `autonomy/mesh_decision.py:130` | c — explicit `urlopen` timeout | Yes | per-call `timeout` | **Acceptable** |
| 19 | Forge | `app/api/webhooks.py:59,76` | b — 3 attempts, `0.2 × 2^(n-1)` | Yes | 3 × 3.0s + 0.6s = ~9.8s | **Acceptable** — bounded |
| 20 | Forge | `app/verification/checkers.py:596` | a — 20 sequential readiness probes | Yes (local dev server) | 20 × (0.2 + 1.0) = 24s | **Structural** — loop cap, local target |
| 21 | Forge | `app/verification/checkers.py:680` | a — serial per-asset fetch | Yes (local) | N_assets × 2.0s, unbounded in principle | **Structural** |
| 22 | Forge | `app/integrations/intelx_client.py:250,334` / `futuris_client.py:95` | c — explicit 2.0s | Yes | 2s | **Acceptable** — tight |
| 23 | Inference | `app/alerts.py:44` | a — serial webhook loop | Yes | N_urls × 5.0s (N is 0 in practice) | **Acceptable** |
| 24 | Inference | `app/providers/gemini.py:129,237` | b — `max_attempts` loop | Yes | bounded by `max_attempts` × 10.0s | **Acceptable** |
| 25 | Inference | `app/inference_runtime/fallback_executor.py:29` | a — sequential provider candidates | Yes | N_providers × per-provider timeout | **Structural** — bounded by registry size |
| 26 | Cortex | `apps/api/src/cortex_api/production_router.py:230` | a — serial WebSocket sends | Yes | local socket writes, **not a peer call** | **Not applicable** |
| 27 | Cortex | `apps/api/src/cortex_api/friday_router.py:584` | c — explicit 15.0s | Yes | 15s | **Structural** — long for a free-tier peer |
| 28 | Cortex | `cortex_upgrade/toolbus.py:49` | d — lock across arbitrary tool handler | **No** — only referenced from landing-page HTML strings | n/a | **Dead/upgrade code** |
| 29 | Memora | `apps/api/main.py:64` | c — Turso pipeline, `timeout=10` | Yes | 10s, single call | **Acceptable** |
| 30 | Memora | `sdk/memora_client.py` (9 call sites) | c — `urlopen(timeout=self.timeout)` | Yes | per-call | **Acceptable** |

### Patterns with zero occurrences

- **Unbounded backoff:** none. Every retry loop in live agent code is bounded by a
  literal or a constructor `int`. The one exponential sleep
  (`FRIDAY/src/friday/memory/embeddings/gemini.py:219`,
  `1.0 * backoff_factor**attempt`) is capped by `max_retries: int = 3`,
  `backoff_factor: float = 2.0` → ≤ 4s.
- **No client timeout at all:** none. Every blocking client in live agent code
  passes a timeout. The `httpx.AsyncClient()` calls without an explicit timeout
  (#7, plus `FRIDAY/src/friday/core/service_registry.py:249` and
  `Forge/app/verification/checkers.py:599,680`) inherit httpx's documented 5.0s
  default, so they are bounded — just not obviously so.
- **DB lock across external I/O:** one occurrence (#1), now fixed.

## Not reproduced

`forge: huge_string` raised one `WinError 10054` (connection forcibly closed) in a
full adversarial probe run, giving 64/65. Forge stayed listening throughout. The
same 2 MB payload sent directly afterwards returned normally, and a full re-run
gave **65/65 clean**. Not root-caused; recorded as transient.

## Verification of this pass

| Check | Result |
|---|---|
| IntelX full suite | 191 passed, 2 skipped (46.5s) |
| Futuris full suite | 167 passed (7m20s) |
| `test_research_write_deadline.py` × 5 consecutive | 7 passed every run (6.45–6.59s) |
| Revert check (primary-path commit removed) | 2 tests fail; competing writer blocked 3.36s |
| `local_mesh_probe.py` | 19/19 passed |
| `adversarial_mesh_probe.py` | 65/65 clean (after one transient, above) |
| Fleet | all nine ports 8101–8109 listening |
