"""Advisory Command Validation Tests for FRIDAY Trading Supervision."""

import pytest

from friday.skills.advisory_supervisor import AdvisorySupervisorSkill
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8991, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def supervisor_and_operator(mock_server):
    server, base_url = mock_server
    server.set_scenario("mixed")
    operator = TradingBotOperator(base_url=base_url)
    supervisor = AdvisorySupervisorSkill(bot_operator=operator)
    return supervisor, operator, server


# =========================================================================
# 1. Voice & Text Command Tests (Mixed Scenario)
# =========================================================================

def test_command_how_is_the_trading_bot_doing(supervisor_and_operator):
    """Test 'How is the trading bot doing?' returns live metrics and advisory summary."""
    supervisor, operator, server = supervisor_and_operator
    res = operator.execute("How is the trading bot doing?")
    
    assert res.success is True
    assert "active on Binance Futures TESTNET" in res.output
    assert "$10,540.25 USDT" in res.output
    assert "AI-Universe Advisory is HEALTHY" in res.output
    assert "3 recommendations evaluated" in res.output
    assert "1 applied, 1 rejected" in res.output
    assert "btc_sl_pct=0.4" in res.output


def test_command_what_did_ai_universe_recommend(supervisor_and_operator):
    """Test 'What did AI-Universe recommend?' reads recent recommendations with verdicts and confidence."""
    supervisor, operator, server = supervisor_and_operator
    res = supervisor.execute("What did AI-Universe recommend?")

    assert res.success is True
    assert "Recent AI-Universe Advisory Decisions" in res.output
    assert "[APPLY - 85% Conf]" in res.output
    assert "Tighten BTC scalper stop-loss to 0.4%" in res.output
    assert "[REJECT - 91% Conf]" in res.output
    assert "Increase ETH max position size to 2.5x" in res.output


def test_command_show_me_rejected_advisories(supervisor_and_operator):
    """Test 'Show me rejected advisories' filters log for REJECT verdicts and shows safety gate reasons."""
    supervisor, operator, server = supervisor_and_operator
    res = supervisor.execute("Show me rejected advisories")

    assert res.success is True
    assert "Rejected AI-Universe Advisories (Filtered by Bot Safety Gates)" in res.output
    assert "adv_mix_02" in res.output
    assert "91% Conf" in res.output
    assert "Exceeds max account risk limit of 1.0x per asset" in res.output


def test_command_what_parameters_has_the_ai_changed(supervisor_and_operator):
    """Test 'What parameters has the AI changed?' reads active parameter overlay."""
    supervisor, operator, server = supervisor_and_operator
    res = supervisor.execute("What parameters has the AI changed?")

    assert res.success is True
    assert "Active AI-Universe Parameter Overlay" in res.output
    assert "btc_sl_pct" in res.output
    assert "0.4" in res.output


def test_command_trading_morning_briefing(supervisor_and_operator):
    """Test 'Trading morning briefing' composes full morning summary."""
    supervisor, operator, server = supervisor_and_operator
    res = supervisor.execute("Trading morning briefing")

    assert res.success is True
    assert "Trading Bot Morning Briefing" in res.output
    assert "$10,540.25 USDT" in res.output
    assert "BTCUSDT LONG" in res.output
    assert "ETHUSDT SHORT" in res.output
    assert "AI-Universe Advisory is HEALTHY" in res.output


# =========================================================================
# 2. Scenario Variations (All Rejected / All Applied / AI-Universe Down)
# =========================================================================

def test_scenario_all_rejected_advisories(supervisor_and_operator):
    """Test behavior when all advisories are rejected by bot safety gates."""
    supervisor, operator, server = supervisor_and_operator
    server.set_scenario("all_rejected")

    # 1. Check advisory summary
    summary = operator.get_advisory_summary()
    assert "2 recommendations evaluated (0 applied, 2 rejected" in summary
    assert "No active parameter modifications" in summary

    # 2. Check rejected query
    res = supervisor.execute("show me rejected advisories")
    assert res.success is True
    assert "adv_rej_01" in res.output
    assert "Exceeds testnet safety gate maximum leverage limit (5x)" in res.output
    assert "adv_rej_02" in res.output


def test_scenario_all_applied_advisories(supervisor_and_operator):
    """Test behavior when all advisories are applied within safety bounds."""
    supervisor, operator, server = supervisor_and_operator
    server.set_scenario("all_applied")

    # 1. Check advisory overlay state
    res_overlay = supervisor.execute("What parameters has the AI changed?")
    assert "**btc_sl_pct**: 0.4" in res_overlay.output
    assert "**btc_tp_pct**: 1.8" in res_overlay.output

    # 2. Check rejected query when none exist
    res_rej = supervisor.execute("show me rejected advisories")
    assert "No rejected AI-Universe advisories found" in res_rej.output


def test_scenario_ai_universe_down(supervisor_and_operator):
    """Test behavior when AI-Universe advisory service is down."""
    supervisor, operator, server = supervisor_and_operator
    server.set_scenario("ai_universe_down")

    summary = operator.get_advisory_summary()
    assert "AI-Universe Advisory is DOWN" in summary

    briefing = supervisor.morning_trading_briefing()
    assert "AI-Universe Advisory is DOWN" in briefing["spoken_text"]
