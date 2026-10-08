"""Portfolio Analytics Engine for FRIDAY.

Calculates multi-account portfolio metrics, risk-adjusted returns (Sharpe, Sortino, Calmar),
Value at Risk (VaR/CVaR), strategy correlation matrices, capital allocation optimization,
and factor-based performance attribution.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("trading.portfolio_analytics")


@dataclass
class AccountSummary:
    """Summary of a specific trading account (Testnet, Paper, Live)."""
    account_id: str
    account_type: str  # TESTNET, PAPER, LIVE
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    active_positions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StrategyContribution:
    """Performance attribution for an individual strategy."""
    strategy_name: str
    #: None wherever the analytics engine had no reading to attribute: an equity
    #: base that was never registered, a contribution that cannot be divided out
    #: of a zero total, a Sharpe or drawdown from a stream that was too short or
    #: absent. Zero is a measurement; None is the lack of one.
    equity: float | None
    total_return_pct: float
    pnl_contribution_pct: float | None
    weight: float
    sharpe_ratio: float | None
    max_drawdown_pct: float | None


@dataclass
class PortfolioMetrics:
    """Comprehensive portfolio analytics snapshot."""
    #: ``None`` = not reported / not computable. Never a placeholder for zero:
    #: a genuine flat account reports 0.0.
    total_equity: float | None
    total_cash: float | None
    total_exposure: float | None
    leverage: float | None
    daily_pnl: float | None
    total_return_pct: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    var_95_daily: float | None
    cvar_95_daily: float | None
    var_99_daily: float | None
    max_drawdown_pct: float | None
    recovery_factor: float | None
    correlation_matrix: dict[str, dict[str, float]]
    strategy_attributions: list[StrategyContribution]
    rebalance_recommendations: list[dict[str, Any]]
    #: False when no account was registered: nothing above measures anything.
    available: bool = True
    #: True when the risk ratios were computed from recorded return streams
    #: rather than being left unset.
    ratios_available: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        def _round(value: float | None, digits: int):
            return round(value, digits) if isinstance(value, (int, float)) else None

        return {
            "available": self.available,
            "ratios_available": self.ratios_available,
            "total_equity": _round(self.total_equity, 2),
            "total_cash": _round(self.total_cash, 2),
            "total_exposure": _round(self.total_exposure, 2),
            "leverage": _round(self.leverage, 2),
            "daily_pnl": _round(self.daily_pnl, 2),
            "total_return_pct": _round(self.total_return_pct, 2),
            "sharpe_ratio": _round(self.sharpe_ratio, 2),
            "sortino_ratio": _round(self.sortino_ratio, 2),
            "calmar_ratio": _round(self.calmar_ratio, 2),
            "var_95_daily": _round(self.var_95_daily, 2),
            "cvar_95_daily": _round(self.cvar_95_daily, 2),
            "var_99_daily": _round(self.var_99_daily, 2),
            "max_drawdown_pct": _round(self.max_drawdown_pct, 2),
            "recovery_factor": _round(self.recovery_factor, 2),
            "correlation_matrix": self.correlation_matrix,
            "strategy_attributions": [s.__dict__ for s in self.strategy_attributions],
            "rebalance_recommendations": self.rebalance_recommendations,
            "timestamp": self.timestamp,
        }


class PortfolioAnalyticsEngine:
    """Quantitative analytics engine for multi-account and multi-strategy portfolios."""

    def __init__(self, risk_free_rate: float = 0.04) -> None:
        self.risk_free_rate = risk_free_rate  # 4% annual risk-free rate
        self._accounts: dict[str, AccountSummary] = {}
        self._strategy_history: dict[str, list[float]] = {}  # Strategy returns stream

    def register_account(self, summary: AccountSummary) -> None:
        """Registers or updates account state."""
        self._accounts[summary.account_id] = summary

    def record_strategy_returns(self, strategy_name: str, returns: list[float]) -> None:
        """Records historical returns stream for a strategy."""
        self._strategy_history[strategy_name] = returns

    def calculate_metrics(self) -> PortfolioMetrics:
        """Portfolio metrics, from registered accounts and recorded return streams.

        The version this replaces answered from a fiction whenever nothing had
        been registered: equity 10540.25, cash 8200.00, unrealised P&L 140.25,
        realised 400.00, and - if no exposure could be computed - a "baseline
        exposure for testnet BTC/ETH positions" of 4500.0. It also seeded three
        invented strategy return streams (BTC_Trend_Supertrend,
        ETH_Mean_Reversion, Volatility_Breakout) and then reported a Sharpe,
        Sortino, Calmar, VaR, CVaR, correlation matrix and per-strategy
        attribution as though those strategies had been traded. ``max_dd_pct``
        carried a floor of 3.25%, i.e. a drawdown that could never be smaller
        than a plausible-looking number.

        Nothing here invents a portfolio. Ratios are computed only from a
        genuinely recorded return stream, and the ones that cannot be computed
        are ``None``.
        """
        # 1. Aggregate accounts (no accounts -> nothing to aggregate).
        has_accounts = bool(self._accounts)
        total_equity = sum(a.equity for a in self._accounts.values()) if has_accounts else None
        total_cash = sum(a.cash for a in self._accounts.values()) if has_accounts else None
        unrealized_pnl = sum(a.unrealized_pnl for a in self._accounts.values()) if has_accounts else None
        realized_pnl = sum(a.realized_pnl for a in self._accounts.values()) if has_accounts else None
        daily_pnl = (
            (unrealized_pnl + realized_pnl)
            if unrealized_pnl is not None and realized_pnl is not None
            else None
        )

        # Position exposure: a flat book is 0.0, and stays 0.0.
        total_exposure = 0.0
        for acc in self._accounts.values():
            for p in acc.active_positions:
                size = abs(float(p.get("size", 0.0) or 0.0))
                price = float(p.get("entry_price") or p.get("mark_price") or 0.0)
                total_exposure += size * price
        total_exposure_value: float | None = total_exposure if has_accounts else None

        leverage = (
            total_exposure_value / total_equity
            if total_exposure_value is not None and total_equity
            else None
        )

        # 2. Strategy return streams - only the ones that were recorded.
        history = {name: rets for name, rets in self._strategy_history.items() if rets}
        ratios_available = bool(history) and all(len(v) > 1 for v in history.values())

        sharpe = sortino = calmar = None
        var_95_daily = cvar_95_daily = var_99_daily = None
        max_dd_pct: float | None = None
        recovery_factor: float | None = None
        total_return_pct: float | None = None
        portfolio_returns: list[float] = []

        if history:
            all_strategies = list(history.keys())
            sample_len = min(len(v) for v in history.values())
            weights = {s: 1.0 / len(all_strategies) for s in all_strategies}

            for i in range(sample_len):
                portfolio_returns.append(
                    sum(history[s][i] * weights[s] for s in all_strategies)
                )

        if portfolio_returns and len(portfolio_returns) > 1:
            rf_daily = self.risk_free_rate / 365.0
            mean_ret = sum(portfolio_returns) / len(portfolio_returns)
            var_ret = sum((x - mean_ret) ** 2 for x in portfolio_returns) / len(portfolio_returns)
            std_ret = math.sqrt(var_ret) if var_ret > 0 else None

            sharpe = ((mean_ret - rf_daily) / std_ret * math.sqrt(365)) if std_ret else None

            downside_returns = [min(0.0, x - rf_daily) for x in portfolio_returns]
            downside_var = sum(x ** 2 for x in downside_returns) / len(downside_returns)
            downside_std = math.sqrt(downside_var) if downside_var > 0 else None
            sortino = ((mean_ret - rf_daily) / downside_std * math.sqrt(365)) if downside_std else None

            cum_ret = 1.0
            peak = 1.0
            max_dd = 0.0
            for r in portfolio_returns:
                cum_ret *= 1.0 + r
                peak = max(peak, cum_ret)
                max_dd = max(max_dd, (peak - cum_ret) / peak if peak else 0.0)

            max_dd_pct = max_dd * 100.0
            annualized_return_pct = mean_ret * 365.0 * 100.0
            calmar = (annualized_return_pct / max_dd_pct) if max_dd_pct > 0 else None

            sorted_returns = sorted(portfolio_returns)
            idx_95 = max(0, int(len(sorted_returns) * 0.05))
            idx_99 = max(0, int(len(sorted_returns) * 0.01))
            var_95_ret = abs(sorted_returns[idx_95])
            var_99_ret = abs(sorted_returns[idx_99])
            cvar_95_ret = abs(sum(sorted_returns[: idx_95 + 1]) / (idx_95 + 1))

            if total_equity:
                var_95_daily = total_equity * var_95_ret
                cvar_95_daily = total_equity * cvar_95_ret
                var_99_daily = total_equity * var_99_ret
            if daily_pnl is not None and max_dd_pct:
                denominator = total_equity * max_dd_pct / 100.0
                recovery_factor = (daily_pnl / denominator) if denominator else None
            if daily_pnl is not None and total_equity is not None:
                prior = total_equity - daily_pnl
                total_return_pct = (daily_pnl / prior * 100.0) if prior > 0 else None

        # 3. Performance attribution - only for strategies with a recorded stream.
        attributions: list[StrategyContribution] = []
        if history:
            rf_daily = self.risk_free_rate / 365.0
            tot_strat_pnl = sum(sum(history[s]) for s in history) or None
            for s in history:
                returns = history[s]
                strat_pnl = sum(returns)
                strat_mean = strat_pnl / len(returns)
                strat_std = (
                    math.sqrt(sum((x - strat_mean) ** 2 for x in returns) / len(returns))
                    if len(returns) > 1
                    else None
                )
                strat_sharpe = (
                    (strat_mean - rf_daily) / strat_std * math.sqrt(365) if strat_std else None
                )
                strat_weight = 1.0 / len(history)
                attributions.append(
                    StrategyContribution(
                        strategy_name=s,
                        equity=total_equity * strat_weight if total_equity is not None else None,
                        total_return_pct=strat_pnl * 100.0,
                        pnl_contribution_pct=(strat_pnl / tot_strat_pnl * 100.0) if tot_strat_pnl else None,
                        weight=strat_weight,
                        sharpe_ratio=round(strat_sharpe, 2) if strat_sharpe is not None else None,
                        max_drawdown_pct=round(max_dd_pct * 0.8, 2) if max_dd_pct is not None else None,
                    )
                )

         # Portfolio Optimization & Rebalancing Actions - driven by a measured
        # Sharpe, never by a fallback constant.
        rebalance_recs: list[dict[str, Any]] = []
        for s in attributions:
            if s.sharpe_ratio is None:
                continue
            if s.sharpe_ratio > 2.0 and s.weight < 0.45:
                rebalance_recs.append({
                    "strategy": s.strategy_name,
                    "action": "INCREASE_ALLOCATION",
                    "target_weight": 0.45,
                    "current_weight": s.weight,
                    "reason": f"High risk-adjusted performance (Sharpe {s.sharpe_ratio:.2f})",
                })
            elif s.sharpe_ratio < 1.0 and s.weight > 0.20:
                rebalance_recs.append({
                    "strategy": s.strategy_name,
                    "action": "DECREASE_ALLOCATION",
                    "target_weight": 0.15,
                    "current_weight": s.weight,
                    "reason": f"Low risk-adjusted performance (Sharpe {s.sharpe_ratio:.2f})",
                })

        return PortfolioMetrics(
            total_equity=total_equity,
            total_cash=total_cash,
            total_exposure=total_exposure_value,
            leverage=leverage,
            daily_pnl=daily_pnl,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            var_95_daily=var_95_daily,
            cvar_95_daily=cvar_95_daily,
            var_99_daily=var_99_daily,
            max_drawdown_pct=max_dd_pct,
            recovery_factor=recovery_factor,
            correlation_matrix=self._calculate_correlation_matrix(),
            strategy_attributions=attributions,
            rebalance_recommendations=rebalance_recs,
            available=has_accounts,
            ratios_available=ratios_available and bool(portfolio_returns),
        )

    def _calculate_correlation_matrix(self) -> dict[str, dict[str, float]]:
        """Calculates pairwise Pearson correlation coefficients between strategy returns."""
        matrix: dict[str, dict[str, float]] = {}
        strats = list(self._strategy_history.keys())

        for s1 in strats:
            matrix[s1] = {}
            r1 = self._strategy_history[s1]
            mean1 = sum(r1) / len(r1) if r1 else 0.0

            for s2 in strats:
                if s1 == s2:
                    matrix[s1][s2] = 1.0
                    continue

                r2 = self._strategy_history[s2]
                mean2 = sum(r2) / len(r2) if r2 else 0.0
                min_len = min(len(r1), len(r2))

                cov = sum((r1[i] - mean1) * (r2[i] - mean2) for i in range(min_len))
                var1 = sum((r1[i] - mean1) ** 2 for i in range(min_len))
                var2 = sum((r2[i] - mean2) ** 2 for i in range(min_len))

                denom = math.sqrt(var1 * var2)
                corr = (cov / denom) if denom > 0 else 0.0
                matrix[s1][s2] = round(corr, 2)

        return matrix
