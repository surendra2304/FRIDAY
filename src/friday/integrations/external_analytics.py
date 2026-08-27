# -*- coding: utf-8 -*-
"""External Analytics Integration Provider for FRIDAY Trading.

Provides data formatting, charting payload generation, and integration hooks for
TradingView webhooks, Lightweight Charts, and third-party risk analysis platforms.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.trading.portfolio_analytics import PortfolioAnalyticsEngine, PortfolioMetrics
from friday.trading.regime_detector import MarketRegimeDetector
from friday.trading.risk_dashboard import RiskManagementDashboard

logger = get_logger("integrations.external_analytics")


class ExternalAnalyticsProvider:
    """Formats and exports trading analytics to external charting and analytics platforms."""

    def __init__(
        self,
        portfolio_engine: Optional[PortfolioAnalyticsEngine] = None,
        regime_detector: Optional[MarketRegimeDetector] = None,
        risk_dashboard: Optional[RiskManagementDashboard] = None,
    ) -> None:
        self.portfolio_engine = portfolio_engine or PortfolioAnalyticsEngine()
        self.regime_detector = regime_detector or MarketRegimeDetector()
        self.risk_dashboard = risk_dashboard or RiskManagementDashboard()

    def generate_tradingview_payload(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        indicators: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generates TradingView Lightweight Charts compatible configuration payload."""
        indicators = indicators or ["EMA_20", "EMA_50", "Supertrend", "ATR_Bands"]
        regime = self.regime_detector.detect_regime(symbol=symbol)

        return {
            "symbol": symbol,
            "exchange": "BINANCE_FUTURES",
            "timeframe": timeframe,
            "theme": "dark",
            "active_indicators": indicators,
            "regime_overlay": {
                "state": regime.primary_regime.value,
                "consensus": regime.timeframe_consensus,
                "adx_1h": regime.timeframes["1h"].adx_value,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def generate_portfolio_chart_payload(self) -> Dict[str, Any]:
        """Generates rich time-series and allocation chart payloads for UI visualization."""
        metrics = self.portfolio_engine.calculate_metrics()
        risk = self.risk_dashboard.evaluate_risk()

        return {
            "chart_type": "PORTFOLIO_ANALYTICS_OVERVIEW",
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

        report = (
            f"# 📊 Institutional Portfolio Analytics & Quantitative Risk Report\n\n"
            f"**Report Generated:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}` | **Base Currency:** `USDT`\n\n"
            f"## 🏛️ Executive Summary\n"
            f"- **Total Portfolio Equity:** **${metrics.total_equity:,.2f} USDT** (Cash: `${metrics.total_cash:,.2f}`)\n"
            f"- **Total Exposure:** **${metrics.total_exposure:,.2f} USDT** ({metrics.leverage:.2f}x Leverage)\n"
            f"- **Sharpe Ratio:** **{metrics.sharpe_ratio:.2f}** | **Sortino:** **{metrics.sortino_ratio:.2f}** | **Calmar:** **{metrics.calmar_ratio:.2f}**\n"
            f"- **Value at Risk (1-day 95%):** **${metrics.var_95_daily:,.2f} USDT** | **CVaR (Expected Shortfall):** **${metrics.cvar_95_daily:,.2f} USDT**\n\n"
            f"## 🌐 Market Regime Assessment\n"
            f"- **Primary Regime:** `{regime.primary_regime.value}` ({regime.timeframe_consensus})\n"
            f"- **Position Sizing Multiplier:** `{regime.position_sizing_multiplier}x`\n"
            f"- **Suitable Strategies:** {', '.join(f'`{s}`' for s in regime.suitable_strategies)}\n\n"
            f"## 🗺️ Strategy Attribution & Correlation\n"
            f"| Strategy | Weight | Sharpe | Total Return | Max DD |\n"
            f"| :--- | :---: | :---: | :---: | :---: |\n"
        )

        for s in metrics.strategy_attributions:
            report += f"| `{s.strategy_name}` | {s.weight * 100:.0f}% | {s.sharpe_ratio:.2f} | {s.total_return_pct:+.2f}% | {s.max_drawdown_pct:.2f}% |\n"

        return report
