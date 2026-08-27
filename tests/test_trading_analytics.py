# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Advanced Trading Analytics & Portfolio Management."""

import pytest

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

    metrics = engine.calculate_metrics()
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

def test_market_regime_detection_multi_timeframe():
    """Verify multi-timeframe regime detection and indicator evaluations."""
    detector = MarketRegimeDetector()

    # Case A: Strong Trending Bull
    regime_bull = detector.detect_regime(symbol="BTCUSDT", market_data={"adx": 32.0, "bbw_pct": 4.5, "atr_pct": 1.8})
    assert regime_bull.primary_regime in (MarketState.TRENDING_BULL_STRONG, MarketState.BREAKOUT)
    assert regime_bull.position_sizing_multiplier >= 1.20
    assert "BTC_Supertrend_Momentum" in regime_bull.suitable_strategies
    assert len(regime_bull.timeframes) == 6

    # Case B: Quiet Ranging
    regime_quiet = detector.detect_regime(symbol="BTCUSDT", market_data={"adx": 15.0, "bbw_pct": 1.5, "atr_pct": 0.8})
    assert regime_quiet.primary_regime == MarketState.RANGING_QUIET
    assert regime_quiet.stop_loss_adjustment_factor <= 0.85
    assert "Bollinger_Mean_Reversion" in regime_quiet.suitable_strategies


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
    assert trend_alloc.status == "ACTIVE"

    # 2. Directional conflict resolution
    conflict = coordinator.resolve_strategy_conflict(
        symbol="BTCUSDT",
        strategy_signals={"BTC_Trend": "LONG", "BTC_MeanRev": "SHORT"},
        current_regime=MarketState.TRENDING_BULL_STRONG,
    )
    assert conflict.resolved_action == "LONG"
    assert conflict.confidence >= 0.80


# =========================================================================
# 6. External Analytics Integration Tests
# =========================================================================

def test_external_analytics_provider_payloads():
    """Verify TradingView configuration payloads and report generation."""
    provider = ExternalAnalyticsProvider()

    tv_payload = provider.generate_tradingview_payload(symbol="BTCUSDT", timeframe="1h")
    assert tv_payload["symbol"] == "BTCUSDT"
    assert tv_payload["exchange"] == "BINANCE_FUTURES"
    assert "active_indicators" in tv_payload

    chart_payload = provider.generate_portfolio_chart_payload()
    assert chart_payload["chart_type"] == "PORTFOLIO_ANALYTICS_OVERVIEW"
    assert chart_payload["sharpe_ratio"] > 0

    report_md = provider.generate_custom_report(format="markdown")
    assert "# 📊 Institutional Portfolio Analytics & Quantitative Risk Report" in report_md


# =========================================================================
# 7. Voice Trading Skill Tests
# =========================================================================

def test_voice_trading_skill_commands():
    """Verify VoiceTradingSkill parses and responds to all quantitative voice commands."""
    skill = VoiceTradingSkill()

    # 1. "How is my portfolio performing?"
    res1 = skill.execute("How is my portfolio performing?")
    assert res1.success is True
    assert "Sharpe Ratio" in res1.output

    # 2. "What's my current risk exposure?"
    res2 = skill.execute("What's my current risk exposure?")
    assert res2.success is True
    assert "Portfolio Risk Management Dashboard" in res2.output

    # 3. "What's the current market regime?"
    res3 = skill.execute("What's the current market regime?")
    assert res3.success is True
    assert "Current Market Regime is" in res3.output

    # 4. "How do you expect the ML strategy to perform?"
    res4 = skill.execute("How do you expect the ML strategy to perform?")
    assert res4.success is True
    assert "Performance forecast for" in res4.output

    # 5. "Should I rebalance my portfolio?"
    res5 = skill.execute("Should I rebalance my portfolio?")
    assert res5.success is True
    assert "rebalancing recommendations" in res5.output

    # 6. "How is the BTC_Trend strategy doing?"
    res6 = skill.execute("How is the BTC_Trend strategy doing?")
    assert res6.success is True
    assert "Performance for" in res6.output


def test_voice_trading_registered_in_registry():
    """Verify VoiceTradingSkill is registered by default in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("voice_trading")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
