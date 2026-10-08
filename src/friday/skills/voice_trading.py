"""Voice-Activated Advanced Trading Analytics Skill for FRIDAY.

Provides interactive voice and text commands for quantitative trading analysis:
- "How is my portfolio performing?" -> Multi-account portfolio metrics, Sharpe, returns
- "What's my current risk exposure?" -> VaR, CVaR, concentration, stress test results
- "How is the [strategy] strategy doing?" -> Strategy-specific performance attribution
- "What's the current market regime?" -> Multi-timeframe trend & volatility detection
- "How do you expect the [strategy] to perform?" -> Predictive return & volatility forecasts
- "Should I rebalance my portfolio?" -> Regime-tailored strategy allocation advice
"""

import re
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.voice_trading")


class VoiceTradingSkill(BaseSkill):
    """Voice trading and quantitative analytics skill."""

    __test__ = False

    name = "voice_trading"
    description = (
        "Provides voice-activated portfolio analytics, multi-timeframe market regime detection, "
        "time-series performance predictions, risk exposure analysis, and rebalancing recommendations."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Quantitative Portfolio & Risk Analytics Specialist. You analyze multi-account "
        "portfolios, classify multi-timeframe market regimes, calculate VaR/CVaR, and forecast strategy performance."
    )
    match_patterns = [
        r"\b(?:how\s+is\s+my\s+portfolio\s+performing|portfolio\s+performance|portfolio\s+analytics)\b",
        r"\b(?:what(?:'s|\s+is)\s+my\s+current\s+risk\s+exposure|risk\s+exposure|risk\s+dashboard|var\s+report)\b",
        r"\b(?:how\s+is\s+the\s+([a-zA-Z0-9_\-]+)\s+strategy\s+doing|strategy\s+performance\s+([a-zA-Z0-9_\-]+))\b",
        r"\b(?:what(?:'s|\s+is)\s+the\s+current\s+market\s+regime|market\s+regime|detect\s+regime)\b",
        r"\b(?:how\s+do\s+you\s+expect\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\s+(?:strategy\s+)?to\s+perform|performance\s+prediction|forecast\s+strategy)\b",
        r"\b(?:should\s+i\s+rebalance\s+my\s+portfolio|rebalance\s+portfolio|rebalancing\s+recommendations)\b",
    ]

    def __init__(
        self,
        portfolio_engine: Any | None = None,
        regime_detector: Any | None = None,
        predictor: Any | None = None,
        risk_dashboard: Any | None = None,
        coordinator: Any | None = None,
    ) -> None:
        self._portfolio_engine = portfolio_engine
        self._regime_detector = regime_detector
        self._predictor = predictor
        self._risk_dashboard = risk_dashboard
        self._coordinator = coordinator

    @property
    def portfolio_engine(self) -> Any:
        if self._portfolio_engine is None:
            from friday.trading.portfolio_analytics import PortfolioAnalyticsEngine
            self._portfolio_engine = PortfolioAnalyticsEngine()
        return self._portfolio_engine

    @property
    def regime_detector(self) -> Any:
        if self._regime_detector is None:
            from friday.trading.regime_detector import MarketRegimeDetector
            self._regime_detector = MarketRegimeDetector()
        return self._regime_detector

    @property
    def predictor(self) -> Any:
        if self._predictor is None:
            from friday.trading.performance_predictor import PerformancePredictionEngine
            self._predictor = PerformancePredictionEngine()
        return self._predictor

    @property
    def risk_dashboard(self) -> Any:
        if self._risk_dashboard is None:
            from friday.trading.risk_dashboard import RiskManagementDashboard
            self._risk_dashboard = RiskManagementDashboard()
        return self._risk_dashboard

    @property
    def coordinator(self) -> Any:
        if self._coordinator is None:
            from friday.trading.strategy_coordinator import MultiStrategyCoordinator
            self._coordinator = MultiStrategyCoordinator(
                analytics_engine=self.portfolio_engine,
                regime_detector=self.regime_detector,
            )
        return self._coordinator

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches natural language voice trading requests."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. Market Regime Detection
            if any(k in clean_req for k in ["market regime", "detect regime"]):
                regime = self.regime_detector.detect_regime()
                if not regime.available:
                    output = (
                        "**No market regime could be classified.** No ADX, Bollinger-band width or "
                        "ATR reading has been supplied, and this detector will not invent one: the "
                        "regime it reports decides position sizing by up to 2.5x."
                    )
                else:
                    output = (
                        f"Current Market Regime is **{regime.primary_regime.value}** ({regime.timeframe_consensus}). "
                        f"Overall risk level is **{regime.risk_level}** with a recommended position sizing multiplier of **{regime.position_sizing_multiplier}x**. "
                        f"Optimal strategies for this regime: {', '.join(f'`{s}`' for s in regime.suitable_strategies)}."
                    )
                step_results.append({"action": "detect_regime", "regime": regime.primary_regime.value})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                    metadata=regime.to_dict(),
                )

            # 2. Risk Exposure & VaR Report
            if any(k in clean_req for k in ["risk exposure", "risk dashboard", "var report", "what's my current risk"]):
                risk_profile = self.risk_dashboard.evaluate_risk()
                md_out = self.risk_dashboard.render_markdown_dashboard(risk_profile)
                step_results.append(
                    {
                        "action": "evaluate_risk",
                        "var_95": risk_profile.var_95_usdt,
                        "available": risk_profile.available,
                    }
                )
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=md_out,
                    step_results=step_results,
                    metadata=risk_profile.to_dict(),
                )

            # 3. Overall portfolio performance. This has to be checked before the
            #    strategy-forecast branch below: "how is my portfolio performing"
            #    contains "perform", so it used to be answered with a forecast for
            #    the default strategy instead of the portfolio it asked about.
            if "portfolio" in clean_req and any(k in clean_req for k in ["perform", "doing", "how is"]):
                metrics = self.portfolio_engine.calculate_metrics()
                from friday.core.readings import format_money, format_number

                if not metrics.available:
                    output = (
                        "No trading account has been registered with the analytics engine, so I have "
                        "no equity, leverage, Sharpe, Sortino or drawdown to report. I am not going to "
                        "quote figures that nothing produced."
                    )
                else:
                    output = (
                        f"Reported portfolio equity is **{format_money(metrics.total_equity)} USDT** "
                        f"with an effective leverage of **{format_number(metrics.leverage, 2, 'x')}**. "
                        f"Risk-adjusted metrics: Sharpe **{format_number(metrics.sharpe_ratio, 2)}**, "
                        f"Sortino **{format_number(metrics.sortino_ratio, 2)}**, maximum drawdown "
                        f"**{format_number(metrics.max_drawdown_pct, 2, '%')}**."
                    )
                step_results.append(
                    {"action": "portfolio_performance", "available": metrics.available}
                )
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                    metadata=metrics.to_dict(),
                )

            # 4. Strategy Performance Prediction
            if any(k in clean_req for k in ["expect", "perform", "forecast", "prediction"]):
                # Extract strategy name if specified
                match_strat = re.search(r"\b(?:the\s+)?([a-zA-Z0-9_\-]+)\s+(?:strategy\s+)?to\s+perform\b", clean_req)
                strat_name = match_strat.group(1) if match_strat else "BTC_Supertrend_Momentum"
                if strat_name in ("ml", "ml_strategy"):
                    strat_name = "ML_Ensemble_Strategy"

                regime = self.regime_detector.detect_regime()
                forecast = self.predictor.forecast_strategy(
                    strategy_name=strat_name,
                    current_regime=regime.primary_regime.value,
                )
                h7 = forecast.horizons["7d"]
                output = (
                    f"Performance forecast for **{strat_name}** in current **{regime.primary_regime.value}** regime:\n"
                    f"• 7-Day Expected Return: **{h7.expected_return_pct:+.2f}%** (95% CI [{h7.confidence_interval_95[0]}%, {h7.confidence_interval_95[1]}%])\n"
                    f"• Expected Sharpe Ratio: **{h7.expected_sharpe:.2f}** with a **{h7.probability_positive * 100:.0f}%** probability of positive alpha.\n"
                    f"• Forecasted 7-Day Volatility: **{h7.expected_volatility_pct:.2f}%**."
                )
                step_results.append({"action": "forecast_strategy", "strategy": strat_name})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                    metadata=forecast.to_dict(),
                )

            # 4. Rebalancing Recommendations
            if any(k in clean_req for k in ["rebalance", "rebalancing"]):
                allocations = self.coordinator.optimize_allocations()
                if not allocations:
                    output = (
                        "I can't recommend rebalancing: no supported market regime has been measured, "
                        "so there is no evidence for target weights. No current weights or orders were changed."
                    )
                else:
                    lines = [
                        "Rule-based target weights for the supplied market regime "
                        "(these are recommendations, not executed orders):"
                    ]
                    for allocation in allocations:
                        current = (
                            f"{allocation.current_weight_pct:.0f}%"
                            if allocation.current_weight_pct is not None
                            else "not reported"
                        )
                        lines.append(
                            f"• **{allocation.strategy_name}**: Target Weight "
                            f"**{allocation.target_weight_pct:.0f}%** (Current: {current}) — "
                            f"Status: `{allocation.status}` ({allocation.reason})"
                        )
                    output = "\n".join(lines)
                step_results.append({"action": "rebalance_recommendations", "allocation_count": len(allocations)})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                )

            # 5. Individual Strategy Performance
            match_strat_perf = re.search(r"\bhow\s+is\s+the\s+([a-zA-Z0-9_\-]+)\s+strategy\s+doing\b", clean_req)
            if match_strat_perf:
                target_strat = match_strat_perf.group(1)
                metrics = self.portfolio_engine.calculate_metrics()
                matching = [s for s in metrics.strategy_attributions if target_strat.lower() in s.strategy_name.lower()]
                if matching:
                    s = matching[0]
                    from friday.core.readings import format_money, format_number

                    output = (
                        f"Performance for **{s.strategy_name}** (from its recorded return stream):\n"
                        f"• Total Return: **{format_number(s.total_return_pct, 2, '%')}**\n"
                        f"• Sharpe Ratio: **{format_number(s.sharpe_ratio, 2)}**\n"
                        f"• Portfolio Weight: **{s.weight * 100:.0f}%** "
                        f"(Equity: {format_money(s.equity)} USDT)\n"
                        f"• Max Drawdown: **{format_number(s.max_drawdown_pct, 2, '%')}**"
                    )
                elif not metrics.available:
                    output = (
                        f"I have no performance record for **{target_strat}**: no account and no "
                        f"return stream have been registered, so I cannot say how it is doing."
                    )
                else:
                    output = (
                        f"No strategy matching **{target_strat}** appears in the recorded performance "
                        f"attribution. I will not describe a strategy I have no record of."
                    )

                step_results.append({"action": "strategy_performance", "strategy": target_strat})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                )

            # 6. Default: Overall Portfolio Performance. "performing solidly across
            # Binance Futures Testnet and Paper accounts" was asserted with no
            # account of any kind registered, followed by four formatted numbers.
            metrics = self.portfolio_engine.calculate_metrics()
            from friday.core.readings import format_money, format_number

            if not metrics.available:
                output = (
                    "I have no portfolio analytics to report: no trading account has been registered "
                    "with the analytics engine, so there is no equity, leverage, Sharpe or drawdown "
                    "figure. I will not describe a portfolio I cannot see."
                )
            else:
                output = (
                    f"Reported portfolio equity is **{format_money(metrics.total_equity)} USDT** with an "
                    f"effective leverage of **{format_number(metrics.leverage, 2, 'x')}**. "
                    f"Risk-adjusted metrics: **Sharpe {format_number(metrics.sharpe_ratio, 2)}**, "
                    f"**Sortino {format_number(metrics.sortino_ratio, 2)}**, maximum drawdown "
                    f"**{format_number(metrics.max_drawdown_pct, 2, '%')}**."
                )
            step_results.append({"action": "portfolio_performance", "equity": metrics.total_equity})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=output,
                step_results=step_results,
                metadata=metrics.to_dict(),
            )

        except Exception as e:
            logger.error(f"[VOICE_TRADING] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Voice trading analytics encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )
