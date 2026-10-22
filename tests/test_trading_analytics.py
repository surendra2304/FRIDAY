"""Comprehensive Test Suite for FRIDAY Advanced Trading Analytics & Portfolio Management."""


from friday.integrations.external_analytics import ExternalAnalyticsProvider
from friday.skills.registry import SkillRegistry
from friday.skills.voice_trading import VoiceTradingSkill
from friday.trading.performance_predictor import PerformancePredictionEngine
from friday.trading.portfolio_analytics import AccountSummary, PortfolioAnalyticsEngine
from friday.trading.regime_detector import MarketRegimeDetector, MarketState
from friday.trading.risk_dashboard import RiskManagementDashboard
from friday.trading.strategy_coordinator import MultiStrategyCoordinator

# =========================================================================
# 1. Portfolio Analytics Engine Tests
# =========================================================================

def test_portfolio_analytics_metrics_calculation():
    """Verify calculation of Sharpe, Sortino, Calmar, VaR, CVaR, and correlation matrix."""
    engine = PortfolioAnalyticsEngine(risk_free_rate=0.04)

    # Register sample account
    acc = AccountSummary(
        account_id="acc_testnet_01",
        account_type="TESTNET",
        equity=10540.25,
        cash=8200.00,
        unrealized_pnl=140.25,
        realized_pnl=400.00,
        active_positions=[
            {"symbol": "BTCUSDT", "size": 0.05, "mark_price": 64000.0},
            {"symbol": "ETHUSDT", "size": 0.50, "mark_price": 2600.0},
        ],
    )
    engine.register_account(acc)
    # Return streams must be *recorded*; the engine used to seed three invented
    # ones (BTC/ETH/Volatility) whenever nothing was recorded, so this test's
    # Sharpe/Sortino/Calmar assertions were being satisfied by fabricated data.
    engine.record_strategy_returns(
        "BTC_Trend_Supertrend", [0.012, 0.008, -0.005, 0.015, 0.004, -0.002, 0.018, 0.009]
    )
    engine.record_strategy_returns(
        "ETH_Mean_Reversion", [0.006, -0.003, 0.008, -0.004, 0.007, 0.005, -0.002, 0.006]
    )
    engine.record_strategy_returns(
        "Volatility_Breakout", [0.021, -0.012, 0.018, -0.008, 0.014, -0.005, 0.025, -0.004]
    )

    metrics = engine.calculate_metrics()
    assert metrics.available is True
    assert metrics.ratios_available is True
    assert metrics.total_equity == 10540.25
    assert metrics.total_exposure > 0
    assert metrics.sharpe_ratio > 0
    assert metrics.sortino_ratio > 0
    assert metrics.calmar_ratio > 0
    assert metrics.var_95_daily > 0
    assert metrics.cvar_95_daily >= metrics.var_95_daily
    assert metrics.var_99_daily >= metrics.var_95_daily
    assert len(metrics.correlation_matrix) >= 3
    assert len(metrics.strategy_attributions) >= 3
    assert isinstance(metrics.to_dict(), dict)


# =========================================================================
# 2. Market Regime Detection Tests
# =========================================================================

def test_market_regime_detection_uses_only_measured_timeframes_and_direction():
    """One observation must not become six timeframes or a fabricated bull trend."""
    detector = MarketRegimeDetector()

    # Case A: independently measured timeframes, with directional evidence.
    regime_bull = detector.detect_regime(
        symbol="BTCUSDT",
        market_data={
            "timeframes": {
                "1m": {"adx": 28.8, "bbw_pct": 4.05, "atr_pct": 1.62, "trend_direction": "BULLISH"},
                "1h": {"adx": 32.0, "bbw_pct": 4.5, "atr_pct": 1.8, "plus_di": 36.0, "minus_di": 18.0},
                "4h": {"adx": 35.0, "bbw_pct": 5.0, "atr_pct": 2.1, "trend_direction": "BEARISH"},
            }
        },
    )
    assert regime_bull.primary_regime is MarketState.TRENDING_BULL_STRONG
    assert regime_bull.position_sizing_multiplier == 1.25
    assert "BTC_Supertrend_Momentum" in regime_bull.suitable_strategies
    assert len(regime_bull.timeframes) == 3
    assert regime_bull.timeframes["1h"].adx_value == 32.0
    assert regime_bull.timeframes["4h"].adx_value == 35.0
    assert "2 of 3" in regime_bull.timeframe_consensus

    # Case B: an explicit direction can classify a strong bearish regime.
    regime_bear = detector.detect_regime(
        market_data={
            "1h": {
                "adx": 34.0,
                "bbw_pct": 4.2,
                "atr_pct": 1.7,
                "plus_di": 16.0,
                "minus_di": 31.0,
            }
        }
    )
    assert regime_bear.primary_regime is MarketState.TRENDING_BEAR_STRONG
    assert regime_bear.timeframes["1h"].trend_direction == "BEARISH"

    # Case C: Quiet ranging uses the one supplied reading without copying it.
    regime_quiet = detector.detect_regime(
        symbol="BTCUSDT",
        market_data={"1h": {"adx": 15.0, "bbw_pct": 1.5, "atr_pct": 0.8}},
    )
    assert regime_quiet.primary_regime == MarketState.RANGING_QUIET
    assert regime_quiet.stop_loss_adjustment_factor <= 0.85
    assert "Bollinger_Mean_Reversion" in regime_quiet.suitable_strategies
    assert list(regime_quiet.timeframes) == ["1h"]
    assert "one measured timeframe (1h)" in regime_quiet.timeframe_consensus


def test_unattributed_or_invalid_market_data_fails_closed():
    detector = MarketRegimeDetector()
    unattributed = detector.detect_regime(
        market_data={"adx": 32.0, "bbw_pct": 4.5, "atr_pct": 1.8}
    )
    assert not unattributed.available
    assert unattributed.position_sizing_multiplier is None
    assert "timeframe attribution is missing" in unattributed.explanation

    single = detector.detect_regime(
        market_data={"adx": 32.0, "bbw_pct": 4.5, "atr_pct": 1.8},
        timeframe="1h",
    )
    assert single.available
    assert len(single.timeframes) == 1
    assert single.timeframes["1h"].adx_value == 32.0
    assert single.primary_regime is MarketState.BREAKOUT
    assert single.position_sizing_multiplier == 0.70
    assert "No cross-timeframe consensus" in single.timeframe_consensus

    invalid = detector.detect_regime(
        market_data={"1h": {"adx": float("nan"), "bbw_pct": 4.5, "atr_pct": 1.8}}
    )
    assert not invalid.available
    assert invalid.position_sizing_multiplier is None


# =========================================================================
# 3. Performance Prediction Engine Tests
# =========================================================================

def test_performance_prediction_horizons_and_intervals():
    """Verify multi-horizon returns, volatility forecasts, and confidence bands."""
    predictor = PerformancePredictionEngine()
    forecast = predictor.forecast_strategy(
        strategy_name="BTC_Supertrend_Momentum",
        historical_returns=[0.015, 0.010, -0.004, 0.018, 0.005, -0.003, 0.020],
        current_regime="TRENDING_BULL_STRONG",
    )

    assert forecast.strategy_name == "BTC_Supertrend_Momentum"
    assert "1d" in forecast.horizons
    assert "7d" in forecast.horizons
    assert "30d" in forecast.horizons

    h7 = forecast.horizons["7d"]
    assert h7.expected_return_pct > 0
    assert h7.confidence_interval_95[0] < h7.confidence_interval_95[1]
    assert h7.probability_positive > 0.50
    assert "position_multiplier" in forecast.proactive_parameter_adjustments


# =========================================================================
# 4. Risk Management Dashboard & Stress Testing Tests
# =========================================================================

def test_risk_management_dashboard_and_stress_testing():
    """Verify HHI concentration, Monte Carlo simulation, and historical stress tests."""
    dashboard = RiskManagementDashboard()
    profile = dashboard.evaluate_risk(
        equity=10540.25,
        positions=[
            {"symbol": "BTCUSDT", "size": 0.05, "mark_price": 64000.0},
            {"symbol": "ETHUSDT", "size": 0.50, "mark_price": 2600.0},
        ],
    )

    assert profile.concentration_hhi < 1.0
    assert profile.concentration_rating in ("DIVERSIFIED", "MODERATE", "HIGHLY_CONCENTRATED")
    assert profile.var_95_usdt > 0
    assert len(profile.stress_tests) == 3
    assert any("2020 March Flash Crash" in s.scenario_name for s in profile.stress_tests)
    assert any("Monte Carlo" in s.scenario_name for s in profile.stress_tests)

    md = dashboard.render_markdown_dashboard(profile)
    assert "# 🛡️ FRIDAY Portfolio Risk Management Dashboard" in md
    assert "Value at Risk" in md
    assert "Stress Testing & Crisis Simulations" in md


# =========================================================================
# 5. Multi-Strategy Coordinator Tests
# =========================================================================

def test_multi_strategy_coordinator_allocations_and_conflict_resolution():
    """Verify dynamic strategy rotation and directional conflict resolution."""
    coordinator = MultiStrategyCoordinator()

    # 1. Allocation optimization in Strong Trend
    allocations = coordinator.optimize_allocations(current_regime=MarketState.TRENDING_BULL_STRONG)
    assert len(allocations) >= 3
    trend_alloc = next(a for a in allocations if a.strategy_name == "BTC_Trend_Supertrend")
    assert trend_alloc.target_weight_pct >= 45.0
    assert trend_alloc.current_weight_pct is None
    assert trend_alloc.status == "ACTIVE"

    # A missing live regime is not silently converted into a balanced portfolio.
    assert coordinator.optimize_allocations() == []

    measured = coordinator.optimize_allocations(
        current_regime=MarketState.TRENDING_BULL_STRONG,
        strategy_metrics={"BTC_Trend_Supertrend": {"current_weight": 0.20}},
    )
    measured_trend = next(a for a in measured if a.strategy_name == "BTC_Trend_Supertrend")
    measured_mean_reversion = next(a for a in measured if a.strategy_name == "ETH_Mean_Reversion")
    assert measured_trend.current_weight_pct == 20.0
    assert measured_mean_reversion.current_weight_pct is None

    # 2. Directional conflict resolution
    conflict = coordinator.resolve_strategy_conflict(
        symbol="BTCUSDT",
        strategy_signals={"BTC_Trend": "LONG", "BTC_MeanRev": "SHORT"},
        current_regime=MarketState.TRENDING_BULL_STRONG,
    )
    assert conflict.resolved_action == "LONG"
    assert conflict.confidence >= 0.80

    unknown_regime_conflict = coordinator.resolve_strategy_conflict(
        symbol="BTCUSDT",
        strategy_signals={"BTC_Trend": "LONG", "BTC_MeanRev": "SHORT"},
    )
    assert unknown_regime_conflict.resolved_action == "LONG"
    assert "No supported market regime is available" in unknown_regime_conflict.resolution_rationale
    assert "neutral regime" not in unknown_regime_conflict.resolution_rationale


# =========================================================================
# 6. External Analytics Integration Tests
# =========================================================================

def test_external_analytics_provider_payloads():
    """Verify TradingView configuration payloads and report generation."""
    provider = ExternalAnalyticsProvider()

    tv_payload = provider.generate_tradingview_payload(
        symbol="BTCUSDT", timeframe="1h", market_data={"adx": 30.0, "bbw_pct": 3.8, "atr_pct": 1.6}
    )
    assert tv_payload["symbol"] == "BTCUSDT"
    assert tv_payload["exchange"] == "BINANCE_FUTURES"
    assert "active_indicators" in tv_payload
    assert tv_payload["regime_overlay"]["available"] is True
    assert tv_payload["regime_overlay"]["adx_1h"] == 30.0
    assert "No cross-timeframe consensus" in tv_payload["regime_overlay"]["consensus"]

    # Without market data the overlay says so instead of raising KeyError('1h').
    bare = provider.generate_tradingview_payload(symbol="BTCUSDT", timeframe="1h")
    assert bare["regime_overlay"]["available"] is False
    assert "adx_1h" not in bare["regime_overlay"]

    # The chart payload reports whether the numbers behind it exist, rather than
    # rendering a portfolio the engine invented.
    chart_payload = provider.generate_portfolio_chart_payload()
    assert chart_payload["chart_type"] == "PORTFOLIO_ANALYTICS_OVERVIEW"
    assert chart_payload["metrics_available"] is False
    assert chart_payload["risk_available"] is False
    assert chart_payload["sharpe_ratio"] is None

    report_md = provider.generate_custom_report(format="markdown")
    assert "# 📊 Institutional Portfolio Analytics & Quantitative Risk Report" in report_md
    assert "does not invent a portfolio" in report_md


# =========================================================================
# 7. Voice Trading Skill Tests
# =========================================================================

def test_voice_trading_skill_commands():
    """Verify VoiceTradingSkill parses and responds to all quantitative voice commands."""
    skill = VoiceTradingSkill()

    # 1. "How is my portfolio performing?" with nothing registered: the answer
    # must be that the portfolio is unknown, not a Sharpe ratio from a
    # fabricated account.
    res1 = skill.execute("How is my portfolio performing?")
    assert res1.success is True
    assert "No trading account has been registered" in res1.output

    # With an account and a recorded return stream, the real numbers appear.
    from friday.trading.portfolio_analytics import AccountSummary

    skill.portfolio_engine.register_account(
        AccountSummary(
            account_id="acc_testnet_01",
            account_type="TESTNET",
            equity=10540.25,
            cash=8200.00,
            unrealized_pnl=140.25,
            realized_pnl=400.00,
            active_positions=[{"symbol": "BTCUSDT", "size": 0.05, "mark_price": 64000.0}],
        )
    )
    skill.portfolio_engine.record_strategy_returns(
        "BTC_Trend_Supertrend", [0.012, 0.008, -0.005, 0.015, 0.004, -0.002, 0.018, 0.009]
    )
    res1b = skill.execute("How is my portfolio performing?")
    assert "Reported portfolio equity is **$10,540.25 USDT**" in res1b.output
    assert "Sharpe" in res1b.output

    # 2. "What's my current risk exposure?"
    res2 = skill.execute("What's my current risk exposure?")
    assert res2.success is True
    assert "Portfolio Risk Management Dashboard" in res2.output

    # 3. "What's the current market regime?" - with no indicator data supplied,
    # the skill must refuse to classify rather than guess (its regime drives
    # position sizing).
    res3 = skill.execute("What's the current market regime?")
    assert res3.success is True
    assert "No market regime could be classified" in res3.output

    # 4. "How do you expect the ML strategy to perform?"
    res4 = skill.execute("How do you expect the ML strategy to perform?")
    assert res4.success is True
    assert "Performance forecast for" in res4.output

    # 5. "Should I rebalance my portfolio?"
    res5 = skill.execute("Should I rebalance my portfolio?")
    assert res5.success is True
    assert "can't recommend rebalancing" in res5.output
    assert "no supported market regime has been measured" in res5.output
    assert "Target Weight" not in res5.output

    # 6. "How is the BTC_Trend strategy doing?" - the skill now answers from the
    # recorded attribution for that strategy rather than asserting "positive
    # risk-adjusted returns" for anything it has no record of.
    res6 = skill.execute("How is the BTC_Trend strategy doing?")
    assert res6.success is True
    assert "Performance for **BTC_Trend_Supertrend**" in res6.output

    res6b = skill.execute("How is the no_such_strategy strategy doing?")
    assert res6b.success is True
    assert "No strategy matching" in res6b.output


def test_voice_trading_registered_in_registry():
    """Verify VoiceTradingSkill is registered by default in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("voice_trading")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
