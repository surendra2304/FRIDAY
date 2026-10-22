"""External Analytics Integration Provider for FRIDAY Trading.

Provides data formatting, charting payload generation, and integration hooks for
TradingView webhooks, Lightweight Charts, and third-party risk analysis platforms.
"""

from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.trading.portfolio_analytics import (
    PortfolioAnalyticsEngine,
)
from friday.trading.regime_detector import MarketRegimeDetector
from friday.trading.risk_dashboard import RiskManagementDashboard

logger = get_logger("integrations.external_analytics")


class ExternalAnalyticsProvider:
    """Formats and exports trading analytics to external charting and analytics platforms."""

    def __init__(
        self,
        portfolio_engine: PortfolioAnalyticsEngine | None = None,
        regime_detector: MarketRegimeDetector | None = None,
        risk_dashboard: RiskManagementDashboard | None = None,
    ) -> None:
        self.portfolio_engine = portfolio_engine or PortfolioAnalyticsEngine()
        self.regime_detector = regime_detector or MarketRegimeDetector()
        self.risk_dashboard = risk_dashboard or RiskManagementDashboard()

    def generate_tradingview_payload(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        indicators: list[str] | None = None,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generates TradingView Lightweight Charts compatible configuration payload.

        ``regime.timeframes["1h"]`` raised ``KeyError: '1h'`` for any caller once
        the detector stopped synthesising six timeframes from three constants.
        The overlay now carries the regime only when one could be classified.
        """
        indicators = indicators or ["EMA_20", "EMA_50", "Supertrend", "ATR_Bands"]
        regime = self.regime_detector.detect_regime(
            symbol=symbol,
            market_data=market_data,
            timeframe=timeframe,
        )

        overlay: dict[str, Any] = {
            "state": regime.primary_regime.value,
            "consensus": regime.timeframe_consensus,
            "available": regime.available,
        }
        if regime.available and "1h" in regime.timeframes:
            overlay["adx_1h"] = regime.timeframes["1h"].adx_value

        return {
            "symbol": symbol,
            "exchange": "BINANCE_FUTURES",
            "timeframe": timeframe,
            "theme": "dark",
            "active_indicators": indicators,
            "regime_overlay": overlay,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def generate_portfolio_chart_payload(self) -> dict[str, Any]:
        """Generates rich time-series and allocation chart payloads for UI visualization."""
        metrics = self.portfolio_engine.calculate_metrics()
        risk = self.risk_dashboard.evaluate_risk()

        return {
            "chart_type": "PORTFOLIO_ANALYTICS_OVERVIEW",
            "metrics_available": metrics.available,
            "risk_available": risk.available,
            "total_equity": metrics.total_equity,
            "total_exposure": metrics.total_exposure,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "strategy_allocations": [
                {"name": s.strategy_name, "weight": s.weight, "sharpe": s.sharpe_ratio}
                for s in metrics.strategy_attributions
            ],
            "correlation_matrix": metrics.correlation_matrix,
            "var_95": metrics.var_95_daily,
            "cvar_95": metrics.cvar_95_daily,
            "stress_tests": [s.to_dict() if hasattr(s, "to_dict") else s.__dict__ for s in risk.stress_tests],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_custom_report(self, format: str = "markdown") -> str:
        """Generates formatted executive trading analytics report."""
        metrics = self.portfolio_engine.calculate_metrics()
        regime = self.regime_detector.detect_regime()
        risk = self.risk_dashboard.evaluate_risk()

        from friday.core.readings import format_money, format_number

        # Every figure below used to be formatted unconditionally from a metric
        # object that carried a fabricated portfolio when no account was
        # registered ($10,540.25 equity, $4,500 "baseline exposure", a 3.25%
        # drawdown floor). They are now either reported or explicitly unknown.
        regime_block = (
            f"- **Primary Regime:** `{regime.primary_regime.value}` ({regime.timeframe_consensus})\n"
            f"- **Position Sizing Multiplier:** `{format_number(regime.position_sizing_multiplier, 2, 'x')}`\n"
            f"- **Suitable Strategies:** {', '.join(f'`{s}`' for s in regime.suitable_strategies)}\n"
            if regime.available
            else "- **Primary Regime:** unknown (no market data was supplied; the detector does not guess)\n"
        )
        if not metrics.available:
            return (
                f"# 📊 Institutional Portfolio Analytics & Quantitative Risk Report\n\n"
                f"**Report Generated:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}` | "
                f"**Base Currency:** `USDT`\n\n"
                f"**No account has been registered with the analytics engine**, so there is no equity, "
                f"exposure, Sharpe, Sortino, Calmar or Value-at-Risk to report. Register an account "
                f"(`register_account`) or supply a position list; this report does not invent a "
                f"portfolio to fill its tables.\n\n"
                f"## 🌐 Market Regime Assessment\n{regime_block}"
            )

        report = (
            f"# 📊 Institutional Portfolio Analytics & Quantitative Risk Report\n\n"
            f"**Report Generated:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}` | **Base Currency:** `USDT`\n\n"
            f"## 🏛️ Executive Summary\n"
            f"- **Total Portfolio Equity:** **{format_money(metrics.total_equity)} USDT** "
            f"(Cash: `{format_money(metrics.total_cash)}`)\n"
            f"- **Total Exposure:** **{format_money(metrics.total_exposure)} USDT** "
            f"({format_number(metrics.leverage, 2, 'x')} Leverage)\n"
            f"- **Sharpe Ratio:** **{format_number(metrics.sharpe_ratio, 2)}** | "
            f"**Sortino:** **{format_number(metrics.sortino_ratio, 2)}** | "
            f"**Calmar:** **{format_number(metrics.calmar_ratio, 2)}**\n"
            f"- **Value at Risk (1-day 95%):** **{format_money(metrics.var_95_daily)} USDT** | "
            f"**CVaR (Expected Shortfall):** **{format_money(metrics.cvar_95_daily)} USDT**\n\n"
            f"## 🌐 Market Regime Assessment\n{regime_block}\n"
            f"## 🗺️ Strategy Attribution & Correlation\n"
            f"| Strategy | Weight | Sharpe | Total Return | Max DD |\n"
            f"| :--- | :---: | :---: | :---: | :---: |\n"
        )

        for s in metrics.strategy_attributions:
            report += f"| `{s.strategy_name}` | {s.weight * 100:.0f}% | {s.sharpe_ratio:.2f} | {s.total_return_pct:+.2f}% | {s.max_drawdown_pct:.2f}% |\n"

        return report
