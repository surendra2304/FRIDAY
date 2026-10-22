"""Comprehensive Test Suite for FRIDAY Multi-Exchange Portfolio Supervision."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.portfolio_supervisor import PortfolioSupervisorOperator
from friday.skills.registry import SkillRegistry
from friday.skills.voice_multi_exchange import VoiceMultiExchangeSkill
from friday.trading.exchange_incidents import ExchangeIncidentManager
from friday.workflows.portfolio_review import WeeklyPortfolioReviewWorkflow


@pytest.fixture
def multi_exchange_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    exc_mgr = ExchangeIncidentManager()
    supervisor_op = PortfolioSupervisorOperator(
        exchange_incident_manager=exc_mgr,
        alert_manager=alert_mgr,
        memory=memory,
    )
    skill = VoiceMultiExchangeSkill(exchange_manager=exc_mgr)
    review_wf = WeeklyPortfolioReviewWorkflow(exchange_manager=exc_mgr)

    return skill, exc_mgr, supervisor_op, review_wf, alert_mgr


# =========================================================================
# 1. Exchange Incident Manager Tests
# =========================================================================

def test_exchange_incident_manager_health_and_liquidity(multi_exchange_setup):
    """Verify exchange health monitoring, liquidity comparisons, and arbitrage scanning."""
    skill, exc_mgr, supervisor_op, review_wf, alert_mgr = multi_exchange_setup

    health = exc_mgr.get_exchange_health()
    assert "BINANCE" in health
    assert "BYBIT" in health
    assert "OKX" in health
    assert health["BINANCE"].status == "HEALTHY"

    # Liquidity comparison
    liq_eth = exc_mgr.compare_liquidity("ETHUSDT")
    assert liq_eth.best_venue == "BINANCE"
    assert liq_eth.depth_1pct_usdt["BINANCE"] >= 400000.0

    liq_sol = exc_mgr.compare_liquidity("SOLUSDT")
    assert liq_sol.best_venue == "BYBIT"

    # Arbitrage scanner
    arbs = exc_mgr.scan_arbitrage_opportunities()
    assert len(arbs) >= 1
    assert any(a.actionable and a.net_profit_pct >= 1.0 for a in arbs)

    # Incident recording
    inc = exc_mgr.record_incident("BYBIT", "API_LATENCY_SPIKE", 3, "Latency spiked to 650ms")
    assert inc.exchange_name == "BYBIT"
    assert inc.status == "OPEN"

    report = exc_mgr.get_comparative_reliability_report()
    assert "# 🌐 Exchange Comparative Reliability Report" in report


# =========================================================================
# 2. Portfolio Supervisor Operator Tests
# =========================================================================

def test_portfolio_supervisor_operator_triggers(multi_exchange_setup):
    """Verify operator detects concentration, drift, and arbitrage opportunities."""
    skill, exc_mgr, supervisor_op, review_wf, alert_mgr = multi_exchange_setup

    events = supervisor_op.tick()
    assert isinstance(events, list)

    event_types = [e["type"] for e in events]
    assert "CONCENTRATION_THRESHOLD_EXCEEDED" in event_types
    assert "ALLOCATION_DRIFT_WARNING" in event_types
    assert "ARBITRAGE_OPPORTUNITY_DETECTED" in event_types


# =========================================================================
# 3. Voice Multi-Exchange Commands
# =========================================================================

def test_voice_multi_exchange_commands(multi_exchange_setup):
    """Verify all 8 multi-exchange voice queries."""
    skill, exc_mgr, supervisor_op, review_wf, alert_mgr = multi_exchange_setup

    # 1. "Portfolio overview"
    res1 = skill.execute("Portfolio overview")
    assert res1.success is True
    assert "Total equity across all venues is $25,000.00 USDT" in res1.output

    # 2. "How is Binance doing?"
    res2 = skill.execute("How is Binance doing?")
    assert res2.success is True
    assert "Binance is operating" in res2.output

    # 3. "What's my exposure to BTC?"
    res3 = skill.execute("What's my exposure to BTC?")
    assert res3.success is True
    assert "Aggregated BTC exposure" in res3.output

    # 4. "Any arbitrage opportunities?"
    res4 = skill.execute("Any arbitrage opportunities?")
    assert res4.success is True
    assert "arbitrage scanner detected" in res4.output

    # 5. "Exchange health status"
    res5 = skill.execute("Exchange health status")
    assert res5.success is True
    assert "Exchange health status:" in res5.output

    # 6. "Which exchange has the best liquidity for ETH?"
    res6 = skill.execute("Which exchange has the best liquidity for ETH?")
    assert res6.success is True
    assert "Liquidity comparison for ETH" in res6.output

    # 7. "Show my cross-exchange risk"
    res7 = skill.execute("Show my cross-exchange risk")
    assert res7.success is True
    assert "Cross-exchange risk assessment" in res7.output

    # 8. "Rebalance recommendations"
    res8 = skill.execute("Rebalance recommendations")
    assert res8.success is True
    assert "Rebalance recommendations:" in res8.output


# =========================================================================
# 4. Weekly Portfolio Review Workflow Tests
# =========================================================================

def test_weekly_portfolio_review_workflow(multi_exchange_setup):
    """Verify WeeklyPortfolioReviewWorkflow generates spoken text and Markdown report."""
    skill, exc_mgr, supervisor_op, review_wf, alert_mgr = multi_exchange_setup

    assert review_wf.can_handle("Weekly portfolio review") is True

    review = review_wf.generate_review()
    assert "Good evening Operator Surendra" in review.spoken_briefing
    assert "# 📊 FRIDAY Weekly Multi-Exchange Portfolio Review" in review.markdown_report
    assert review.total_portfolio_equity == 25000.0
    assert "BINANCE" in review.venue_breakdown
    assert "BTCUSDT" in review.correlation_matrix


def test_voice_multi_exchange_registered_in_registry():
    """Verify VoiceMultiExchangeSkill is registered in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("voice_multi_exchange")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
