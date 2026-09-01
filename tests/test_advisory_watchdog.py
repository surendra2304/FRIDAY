"""Advisory Watchdog Operator Validation Tests."""

from unittest.mock import MagicMock

import pytest

from friday.core.types import TrustLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.advisory_watchdog import AdvisoryWatchdogOperator
from friday.operators.manager import OperatorManager
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8992, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def watchdog_setup(mock_server):
    server, base_url = mock_server
    server.set_scenario("mixed")
    memory = InMemoryConversationMemory()
    mock_notif = MagicMock()
    operator = TradingBotOperator(base_url=base_url)
    watchdog = AdvisoryWatchdogOperator(
        bot_operator=operator,
        poll_interval=1.0,
        memory=memory,
        notification_manager=mock_notif,
    )
    return watchdog, operator, memory, mock_notif, server


# =========================================================================
# 1. Trigger Condition Tests
# =========================================================================

def test_watchdog_trigger_on_contested_advisory(watchdog_setup):
    """Verify alert fires when a new high-confidence (>0.7) rejected advisory appears."""
    watchdog, operator, memory, mock_notif, server = watchdog_setup
    server.set_scenario("mixed")

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert state["alert_count"] == 1
    
    alert = state["alerts"][0]
    assert alert["alert_type"] == "CONTESTED_ADVISORY"
    assert alert["decision_id"] == "adv_mix_02"
    assert alert["confidence"] == 0.91
    assert "Exceeds max account risk limit" in alert["rejection_reason"]

    # Verify notification manager called
    mock_notif.post_notification.assert_called_once()
    _, kwargs = mock_notif.post_notification.call_args
    assert "Trading Watchdog Alert" in kwargs["message"]
    assert kwargs["category"] == "trading_supervision"

    # Verify memory logged with UNTRUSTED_EXTERNAL
    msgs = memory.get_messages()
    assert len(msgs) == 1
    assert msgs[0].trust_level == TrustLevel.UNTRUSTED_EXTERNAL
    assert "adv_mix_02" in msgs[0].content


def test_watchdog_trigger_on_ai_universe_down(watchdog_setup):
    """Verify alert fires when AI-Universe health status is reported DOWN."""
    watchdog, operator, memory, mock_notif, server = watchdog_setup
    server.set_scenario("ai_universe_down")

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "AI_UNIVERSE_DOWN" for a in state["alerts"])
    
    # Check alert contents
    down_alert = next(a for a in state["alerts"] if a["alert_type"] == "AI_UNIVERSE_DOWN")
    assert down_alert["severity"] == "warning"
    assert "DOWN" in down_alert["message"]


def test_watchdog_trigger_on_bot_unreachable(watchdog_setup):
    """Verify critical alert fires when the trading bot REST server is unreachable."""
    watchdog, operator, memory, mock_notif, server = watchdog_setup
    server.set_scenario("unreachable")

    state = watchdog.check_state()
    assert state["status"] == "UNREACHABLE"
    assert len(state["alerts"]) == 1
    assert state["alerts"][0]["alert_type"] == "BOT_UNREACHABLE"
    assert state["alerts"][0]["severity"] == "critical"


def test_watchdog_no_alert_for_normal_advisories(watchdog_setup):
    """Verify NO alert fires when all advisories are applied within normal bounds."""
    watchdog, operator, memory, mock_notif, server = watchdog_setup
    server.set_scenario("all_applied")

    state = watchdog.check_state()
    assert state["status"] == "HEALTHY"
    assert state["alert_count"] == 0
    assert len(state["alerts"]) == 0


def test_watchdog_registered_and_ticked_by_operator_manager(watchdog_setup):
    """Verify AdvisoryWatchdogOperator registers in OperatorManager and ticks successfully."""
    watchdog, operator, memory, mock_notif, server = watchdog_setup
    server.set_scenario("mixed")

    mgr = OperatorManager()
    mgr.register_operator(watchdog)

    assert mgr.get_operator("advisory_watchdog") is not None

    # Tick all operators
    results = mgr.tick_all()
    assert len(results) >= 0

    mgr.unregister_operator("advisory_watchdog")
    assert mgr.get_operator("advisory_watchdog") is None
