# Phase E2 — First honest strategy validation: evidence record

**Date of record:** 2026-10-02 · **Owner:** Surendra
**Label: LIVE market data (real exchange candles), PAPER simulation. No order was placed.**

Plan text: *"real data, fees/slippage, out-of-sample holdout, forward paper — honest
expectancy/drawdown before any performance language."*

---

## 1. The headline result, stated first

**The strategy is not validated. Overall verdict: `INSUFFICIENT_EVIDENCE`.**

One of three assets cleared the project's own Gate 1 (profit factor ≥ 1.30 with
≥ 100 trades), and it cleared it by *exactly* zero trades. That is not a pass; it
is a coin flip that landed. No performance claim is made anywhere in this phase,
and the registry's `VALIDATED` label has been corrected to match the evidence.

## 2. What the audit found: governance was already right

The first thing worth recording is what was **not** wrong. Stratex's governance
layer is genuinely well built and was already honest before this phase:

```python
# PRODUCTION_STRATEGY_REGISTRY["adx_ema"]
"status": "OBSERVE_ONLY",
"oos_win_rate_prior": None,
"validated_assets": [],
"reason": "Observe only: historical OOS claims are not reproducible because the
           referenced OHLCV inputs are absent; the checked-in walk-forward report
           records 34 frozen-config holdout trades and a FRAGILE verdict."
```

and a post-processing block actively withdraws stored priors from any entry that
has not been promoted:

```python
for _strategy_entry in PRODUCTION_STRATEGY_REGISTRY.values():
    if _strategy_entry.get("status") != "VALIDATED":
        _strategy_entry["oos_win_rate_prior"] = None
        _strategy_entry["expected_net_edge_bps"] = None
        _strategy_entry["validated_assets"] = []
```

`tests/test_governance_enforcement.py` pins an **empty executable set** with the
comment *"An empty executable set is safer than promoting an unverified prior."*
The repository's own `research/upgrade_2026_08/walk_forward_report.json` records
its verdict as `FRAGILE: selected parameters drift across folds — treat live
config with caution`.

So the "VALIDATED" flag I went looking for was **not** the one controlling
execution. Good. This was not a case of a strategy quietly trading on a fake claim.

## 3. The real defect: one strategy bypassed governance

There *was* a genuine inconsistency, and it was narrow.

Three raw config dicts exist. `ADX_EMA_STRATEGY` and `ADX_EMA_STRATEGY_V2` had
already been cleaned — their OOS fields nulled, with an explanatory comment. The
third, `ADX_EMA_MTF_STRATEGY`, had not:

```
--- ADX_EMA_MTF_STRATEGY (raw config dict) ---
  OOS_WIN_RATE_PRIOR       = 0.516
  OOS_VALIDATION_STATUS    = 'VALIDATED'
  OOS_VALIDATED_ASSETS     = 16 assets
--- PRODUCTION_STRATEGY_REGISTRY[adx_ema_mtf] (governance-filtered) ---
  status                   = 'DISABLED'
  oos_win_rate_prior       = None
  validated_assets         = [] (len=0)
```

And this is where it mattered, because `strategy_adx_ema_mtf.py` reads the **raw
dict**, not the registry:

```python
_OOS_WIN_RATE_PRIOR = _CFG.get("OOS_WIN_RATE_PRIOR", 0.516)   # the .get() default was the bypass
```

Measured before the fix:

```
strategy_adx_ema_mtf._OOS_WIN_RATE_PRIOR = 0.516
```

So a strategy governance had marked `DISABLED` was still emitting a **0.516
win-rate confidence on every signal**, and the config advertised **16 "validated"
assets** that no reproducible holdout had cleared. The `.get(..., 0.516)` default
made it worse: even deleting the key would have silently reinstated the number.

Fixed by nulling the MTF dict's OOS fields to match its siblings, removing the
`.get()` default, and adding `tests/test_oos_claims_are_not_runtime_priors.py`,
which pins the general rule across all three dicts:

> status != "VALIDATED" ⇒ no prior, no validated-asset list, ever.

## 4. The holdout validator

New: `research/validation/holdout_validation.py`, run via
`research/validation/run_adx_ema_holdout.py`.

It exists because the repository had excellent validation *machinery* — a
walk-forward engine, a six-gate quantitative gauntlet, SHA-256-verified market
data caches that refuse to generate substitute data — but no single answer to the
question that matters: *for the parameters that ship, what happened on data
nobody looked at while they were being chosen?*

Properties that make its output trustworthy:

- **Chronological split, never shuffled.** The holdout is strictly later in time.
- **No look-ahead.** Signals are read through bar *i*; entries fill at the **open of
  bar i+1**, per the repo's own `EXECUTION_MODEL: next_candle_open`. A trade is
  never taken on the print that produced its own signal.
- **The strategy's own ATR**, so stop distances are the ones that would actually
  be placed.
- **Costs charged on both sides**, position sized by risk, so drawdown is a real
  percentage. When one bar could hit both stop and target, the **stop** is assumed.
- **It refuses to render a verdict below 100 holdout trades** — the same threshold
  as Gate 1 of `evolution/validation_gauntlet.py`, so "validated" means the same
  thing everywhere in the repository.

## 5. A look-ahead bug I introduced, and caught

The first run of the new validator reported BTCUSDT **PF 1.802, expectancy +14.05,
win rate 69.8%, max drawdown 2.32%** — a much prettier result than the final one.

It was wrong. The first version entered at the close of the same bar that produced
the signal, which is trading on a print you cannot act on, and it violated the
repository's own stated execution assumption. After fixing it to fill at the next
candle's open and using the strategy's own ATR:

| | trades | PF | expectancy | win rate | max DD | net |
|---|---|---|---|---|---|---|
| **with look-ahead (wrong)** | 63 | 1.802 | +14.05 | 69.8% | 2.32% | +8.85% |
| **next-candle-open (correct)** | 70 | **1.480** | **+9.55** | 65.7% | **3.67%** | +6.68% |

**Fixing the bias cut the profit factor by 18% and increased drawdown by 58%.**
This is the single most useful number in this phase: it is the price of a
plausible-looking backtest, and it is why the first result was discarded rather
than reported.

## 6. The measured holdout results — real data, real costs

All runs: chronological holdout beginning **2025-06-09**, entries at next candle
open, **10 bps fee + 5 bps slippage per side**, 0.5% of equity risked per trade.
Data: `BINANCE_TESTNET_READ_ONLY`, 32,886 candles per symbol, SHA-256 recorded in
the result.

| Symbol | Trades | Expectancy | PF | Win rate | Max DD | Net | Verdict |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 70 | +9.55 | 1.480 | 65.7% | 3.67% | +6.68% | `INSUFFICIENT_EVIDENCE` (70 < 100) |
| ETHUSDT | 100 | +12.32 | 1.628 | 67.0% | 2.04% | +12.32% | `PASSED_HOLDOUT` |
| SOLUSDT | 92 | +24.29 | 2.679 | 76.1% | 1.88% | +22.35% | `INSUFFICIENT_EVIDENCE` (92 < 100) |

**Aggregate verdict: `INSUFFICIENT_EVIDENCE`.** One of three, clearing by zero
trades.

## 7. Why this is not a performance claim — the limitations

These matter more than the numbers above, and they are why no strategy was
promoted:

1. **One regime.** All three holdouts cover the *same* window (2025-06-09 onward)
   — a strong crypto uptrend. A trend-following strategy is expected to do well in
   a trend. Nothing here tests ranging or choppy conditions.
2. **Not independent samples.** The three results share one macro regime and are
   heavily correlated. Pooling them would give 262 trades and clear Gate 1
   comfortably — **that pool was deliberately not computed**, because treating
   three coins in one bull market as three independent experiments is precisely
   the error this phase exists to catch.
3. **One symbol passed, by zero trades.** 100 ≥ 100 is the definition of a
   knife-edge result, not a robust one.
4. **Selection history is unaccounted for.** These parameters were themselves
   chosen after looking at this market. A single holdout does not undo that; it
   bounds the damage, it does not erase it.
5. **Paper simulation only.** No order was placed. Fills, funding, liquidation and
   exchange behaviour are modelled, not observed.

## 8. Forward paper — deliberately not started

The plan's last clause is "forward paper". It is not started, and the reason is
not scheduling: running a strategy forward before it has cleared the holdout would
manufacture a track record for something the evidence does not support, and a
short paper run would be easy to mistake for validation. It becomes meaningful
only after a holdout that actually passes.

## 9. Tests and CI

| Suite | Result |
|---|---|
| `tests/test_holdout_validation.py` | 12 passed |
| `tests/test_oos_claims_are_not_runtime_priors.py` | 12 passed |
| with `test_strategy_adx_ema.py`, `test_governance_enforcement.py`, `test_strategy_adx_ema_mtf.py`, `test_multi_strategy_production_architecture.py` | **77 passed** |
| `ruff check` on all touched files | clean |

The holdout tests use synthetic frames **only** to exercise plumbing (split
boundaries, cost accounting, verdict rules). No performance number in this
document comes from synthetic data.

**CI gap closed.** Stratex's workflow was path-filtered to one narrow test, so the
new honesty tests would never have run. The workflow now triggers on strategy
config, strategy module and validator changes, and runs the three suites. It sets
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, so `-p pytest_mock` is passed explicitly —
without it the governance test's `mocker` fixture errors, which is why that
command is recorded here rather than left to be discovered on CI.

## 10. What is still not done

- **Forward paper has not run** (§8).
- **Multi-regime testing has not run.** The single-regime limitation (§7.1) is
  the biggest gap and needs data spanning ranging and choppy periods.
- **The other strategies have not been holdout-tested.** Only the shipped
  `adx_ema` config was measured; `adx_ema_mtf` and the rest remain untested
  (though `adx_ema_mtf` is `DISABLED` and now carries no claims).
- **`research/validation/` results are not recorded as an artifact.** The runner
  prints JSON; nothing persists it. The next change should write a dated
  report alongside `walk_forward_report.json`.
- **No live-candle run is committed.** `data_cache/holdout/` is a local cache
  with SHA-256 provenance sidecars, deliberately untracked, so CI regenerates
  from the exchange rather than trusting a checked-in price series.
