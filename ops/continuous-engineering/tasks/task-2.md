# Task 2 — Quantitative strategy, research and forecasting

## Assigned repositories
- Stratex: research/backtest/forward-validation and risk-controlled trading framework.
- IntelX: evidence-driven research, source provenance, claim verification and cited results.
- Futuris: predictive intelligence, calibrated forecasts and governed decision support.

## Mission
Implement reliable, reproducible product functionality across the three assigned repositories. Code and tests are the primary deliverable; reports are only secondary evidence of work.

## First-cycle priorities
1. Inspect source, tests, issues and current branches in all three repositories. Map the current user-facing path and select one high-impact incomplete implementation per repository.
2. Stratex: prioritize backtesting/forward validation, execution abstractions, fee/slippage modelling, position sizing and risk gates. Default to paper/testnet; never enable live trading or place real orders. Make all time-series splits leakage-resistant and deterministic.
3. IntelX: prioritize source adapters, stable evidence identifiers, provenance tracking, claim-to-source linkage, contradiction handling, citation validation and repeatable export. Never fabricate citations or silently promote an unverified claim.
4. Futuris: prioritize forecast schemas, probability calibration, baselines, time-aware evaluation, confidence intervals, prediction history and explicit uncertainty. Keep decision support separate from automatic high-impact actions.
5. Add tests for missing data, time-zone boundaries, stale sources, API failures, invalid inputs, risk limit edges and reproducibility.

## Definition of useful progress
- Implement features and corresponding unit/integration tests; execute relevant test, lint, type-check and build commands.
- Fix failures introduced by the session. If an external service is inaccessible, use honest deterministic fakes and preserve a clear integration boundary.
- Avoid new dependencies unless justified. Never commit credentials, account data, exchange secrets, or API tokens.
- Never initiate live trading, withdraw funds, execute orders with real accounts, or bypass risk limits.
- Do not pad code to meet a line target. Cumulative work should naturally deliver thousands of meaningful lines across the actual product capabilities and tests.

## End-of-run obligations
Rewrite the task checkpoint and next-run prompt with precise changes per repository, tests and results, unresolved problems, and the exact first coding step next time. The next run continues unfinished implementation without restarting research from scratch.
