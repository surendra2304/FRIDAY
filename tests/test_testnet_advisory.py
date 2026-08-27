# -*- coding: utf-8 -*-
"""Validation Tests for Testnet Advisory Supervision."""

from unittest.mock import MagicMock
import pytest

from friday.core.types import AuthorizationDecision, AuthorizationResponse, TrustLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.testnet_advisory_operator import TestnetAdvisoryOperator
from friday.skills.registry import SkillRegistry
from friday.skills.testnet_advisory_monitor import TestnetAdvisoryMonitorSkill
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8996, scenario="testnet_shadow")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def testnet_setup(mock_server):
    server, base_url = mock_server
    server.set_scenario("testnet_shadow")
    memory = InMemoryConversationMemory()
    mock_notif = MagicMock()
    operator = TradingBotOperator(base_url=base_url)
    skill = TestnetAdvisoryMonitorSkill(bot_operator=operator)
    watchdog = TestnetAdvisoryOperator(
        bot_operator=operator,
        poll_interval=1.0,
        memory=memory,
        notification_manager=mock_notif,
    )
    return skill, watchdog, operator, memory, mock_notif, server


# =========================================================================
# 1. TestnetAdvisoryMonitorSkill Tests
# =========================================================================

def test_testnet_skill_get_status(testnet_setup):
    """Test get_testnet_advisory_status returns active mode, health, equity, and drawdown."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")

    status = skill.get_testnet_advisory_status()
    assert status["active"] is True
    assert status["mode"] == "SHADOW"
    assert status["health"] == "HEALTHY"
    assert status["equity"] == 10540.25
    assert status["drawdown_pct"] == 1.85
    assert "Testnet Advisory is currently ENABLED in SHADOW mode" in status["spoken_text"]


def test_testnet_skill_get_log(testnet_setup):
    """Test get_testnet_advisory_log retrieves recent testnet decisions."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")

    log_data = skill.get_testnet_advisory_log()
    assert log_data["active"] is True
    assert len(log_data["advisories"]) == 3
    assert "testnet_adv_01" in log_data["formatted_text"]
    assert "[SHADOW | APPLY - 88% Conf]" in log_data["formatted_text"]
    assert "testnet_adv_02" in log_data["formatted_text"]
    assert "Blocked by Safety Gate: Exceeds testnet safety limit" in log_data["formatted_text"]


def test_testnet_skill_explain_advisory(testnet_setup):
    """Test explain_testnet_advisory details specific decision rationale."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")

    exp = skill.explain_testnet_advisory("testnet_adv_02")
    assert exp["found"] is True
    assert exp["verdict"] == "REJECT"
    assert "REJECTED by Safety Gate" in exp["explanation"]
    assert "Exceeds testnet safety limit of 5x max leverage" in exp["explanation"]


def test_testnet_skill_compare_testnet_paper(testnet_setup):
    """Test compare_testnet_paper generates execution comparison against paper baseline."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")

    comp = skill.compare_testnet_paper()
    assert comp["active"] is True
    assert comp["delta_return_pct"] == pytest.approx(-0.35, 0.01)
    assert comp["slippage_diff_bps"] == pytest.approx(2.3, 0.1)
    assert "Testnet Live Execution vs. Paper Trading Comparison" in comp["comparison_text"]
    assert "Avg Slippage" in comp["comparison_text"]


def test_testnet_skill_toggle_and_rollback_actions(testnet_setup):
    """Test safety controls: toggle advisory mode and emergency parameter rollback."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")

    mock_auth = MagicMock()
    mock_auth.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED,
        reason="Admin approved",
    )

    # 1. Toggle mode to APPLY
    tog = skill.toggle_advisory_mode(enabled=True, mode="APPLY", authorizer=mock_auth)
    assert tog["success"] is True
    assert "Testnet advisory mode successfully updated to APPLY" in tog["message"]

    # 2. Rollback parameters
    roll = skill.rollback_parameters(authorizer=mock_auth)
    assert roll["success"] is True
    assert "Emergency rollback executed" in roll["message"]


def test_testnet_skill_execute_commands(testnet_setup):
    """Test natural language voice/text command routing for testnet supervision."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_apply")

    # 1. Status query
    res1 = skill.execute("How is the testnet advisory doing?")
    assert res1.success is True
    assert "in APPLY mode" in res1.output

    # 2. Recommendations query
    res2 = skill.execute("What are the testnet advisory recommendations?")
    assert res2.success is True
    assert "Recent Testnet AI-Universe Advisory Decisions" in res2.output

    # 3. Compare testnet vs paper
    res3 = skill.execute("Compare testnet and paper performance")
    assert res3.success is True
    assert "Testnet Live Execution vs. Paper Trading Comparison" in res3.output

    # 4. Explain specific advisory
    res4 = skill.execute("Explain testnet advisory testnet_adv_01")
    assert res4.success is True
    assert "Testnet Advisory Explanation: `testnet_adv_01`" in res4.output


# =========================================================================
# 2. TestnetAdvisoryOperator Alerting Tests
# =========================================================================

def test_testnet_operator_alert_on_mode_change_to_apply(testnet_setup):
    """Verify operator emits warning alert when advisory mode transitions to APPLY."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_shadow")
    watchdog.last_mode = "SHADOW"
    watchdog.alerted_events.clear()

    # Now switch mock server to APPLY
    server.set_scenario("testnet_apply")
    state = watchdog.check_state()

    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "MODE_CHANGED_APPLY" for a in state["alerts"])
    
    # Verify memory logged with UNTRUSTED_EXTERNAL
    untrusted = [m for m in memory.get_messages() if m.trust_level == TrustLevel.UNTRUSTED_EXTERNAL]
    assert len(untrusted) >= 1
    assert "TESTNET_ADVISORY_ALERT" in untrusted[0].content


def test_testnet_operator_alert_on_drawdown_breach(testnet_setup):
    """Verify critical alert fires when testnet drawdown exceeds maximum limit."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_drawdown_breach")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "DRAWDOWN_CRITICAL" for a in state["alerts"])

    dd_alert = next(a for a in state["alerts"] if a["alert_type"] == "DRAWDOWN_CRITICAL")
    assert dd_alert["severity"] == "critical"
    assert "drawdown critical: 6.40%" in dd_alert["message"]


def test_testnet_operator_alert_on_ai_universe_down(testnet_setup):
    """Verify warning alert fires when AI-Universe service goes down."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("testnet_ai_down")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "AI_HEALTH_DOWN" for a in state["alerts"])


def test_testnet_operator_alert_on_bot_unreachable(testnet_setup):
    """Verify critical alert fires when trading bot REST server is unreachable."""
    skill, watchdog, operator, memory, mock_notif, server = testnet_setup
    server.set_scenario("unreachable")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "UNREACHABLE"
    assert state["alerts"][0]["alert_type"] == "BOT_UNREACHABLE"
    assert state["alerts"][0]["severity"] == "critical"


def test_testnet_skill_registered_in_registry():
    """Verify TestnetAdvisoryMonitorSkill is loaded automatically in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("testnet_advisory_monitor")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
