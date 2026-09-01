"""Validation Tests for A/B Test Monitoring and Control."""

from unittest.mock import MagicMock

import pytest

from friday.core.types import TrustLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.ab_test_operator import ABTestOperator
from friday.skills.ab_test_monitor import ABTestMonitorSkill
from friday.skills.registry import SkillRegistry
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8995, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def ab_setup(mock_server):
    server, base_url = mock_server
    server.set_scenario("mixed")
    memory = InMemoryConversationMemory()
    mock_notif = MagicMock()
    operator = TradingBotOperator(base_url=base_url)
    skill = ABTestMonitorSkill(bot_operator=operator)
    watchdog = ABTestOperator(
        bot_operator=operator,
        poll_interval=1.0,
        memory=memory,
        notification_manager=mock_notif,
    )
    return skill, watchdog, operator, memory, mock_notif, server


# =========================================================================
# 1. ABTestMonitorSkill Tests
# =========================================================================

def test_ab_skill_get_status(ab_setup):
    """Test get_ab_status retrieves duration, progress, and trade volumes."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("mixed")

    status = skill.get_ab_status()
    assert status["active"] is True
    assert status["test_name"] == "AI_Universe_Volatility_Overlay"
    assert status["status"] == "RUNNING"
    assert status["elapsed_hours"] == 72.0
    assert status["progress_pct"] == pytest.approx(42.9, 0.1)
    assert status["control_trades"] == 38
    assert status["treatment_trades"] == 40
    assert "A/B Experiment 'AI_Universe_Volatility_Overlay' is currently running" in status["spoken_summary"]


def test_ab_skill_get_results(ab_setup):
    """Test get_ab_results computes metric deltas and statistical significance."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_stat_sig_reached")

    results = skill.get_ab_results()
    assert results["active"] is True
    assert results["stat_sig_achieved"] is True
    assert results["p_value"] == 0.015
    assert results["confidence_pct"] == 98
    assert results["delta_return_pct"] == pytest.approx(6.30, 0.01)
    assert results["lead_arm"] == "Treatment"
    assert "Treatment arm is leading by 6.30% excess return" in results["spoken_summary"]
    assert "ACHIEVED (p=0.015)" in results["spoken_summary"]


def test_ab_skill_explain_ab_difference(ab_setup):
    """Test explain_ab_difference provides detailed outperformance driver analysis."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("mixed")

    exp = skill.explain_ab_difference()
    assert exp["active"] is True
    assert "A/B Performance Divergence Analysis" in exp["explanation"]
    assert "Treatment Arm" in exp["explanation"]
    assert "Adaptive Risk Parameters" in exp["explanation"]
    assert "Drawdown Protection" in exp["explanation"]


def test_ab_skill_generate_ab_report(ab_setup):
    """Test generate_ab_report produces complete visual Markdown comparison report."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_completed")

    rep = skill.generate_ab_report()
    assert rep["active"] is True
    report_md = rep["report_markdown"]

    assert "# 🧪 A/B Test Experiment Report" in report_md
    assert "STATISTICALLY SIGNIFICANT" in report_md
    assert "Comparative Equity & Return Visualization" in report_md
    assert "Metrics Comparison Table" in report_md
    assert "Control (Baseline)" in report_md
    assert "Treatment (AI Overlays)" in report_md
    assert "PROMOTION RECOMMENDED" in report_md


def test_ab_skill_execute_commands(ab_setup):
    """Test skill execute() routes voice and text commands cleanly."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_stat_sig_reached")

    # 1. "How is the A/B test going?"
    exec1 = skill.execute("How is the A/B test going?")
    assert exec1.success is True
    assert "AI_Universe_Volatility_Overlay" in exec1.output

    # 2. "What are the A/B results?"
    exec2 = skill.execute("What are the A/B results?")
    assert exec2.success is True
    assert "Treatment arm is leading" in exec2.output

    # 3. "Explain the A/B difference"
    exec3 = skill.execute("Explain the A/B difference")
    assert exec3.success is True
    assert "A/B Performance Divergence Analysis" in exec3.output

    # 4. "Generate A/B report"
    exec4 = skill.execute("Generate A/B report")
    assert exec4.success is True
    assert "# 🧪 A/B Test Experiment Report" in exec4.output


# =========================================================================
# 2. ABTestOperator Alerting & State Machine Tests
# =========================================================================

def test_ab_operator_alert_on_stat_sig(ab_setup):
    """Verify operator fires alert when statistical significance is achieved."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_stat_sig_reached")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "STAT_SIG_ACHIEVED" for a in state["alerts"])
    assert any(a["alert_type"] == "TREATMENT_OUTPERFORMING" for a in state["alerts"])

    # Verify notification posted
    mock_notif.post_notification.assert_called()
    _, kwargs = mock_notif.post_notification.call_args
    assert "[A/B Test Alert]" in kwargs["message"]

    # Verify memory logged with UNTRUSTED_EXTERNAL
    untrusted = [m for m in memory.get_messages() if m.trust_level == TrustLevel.UNTRUSTED_EXTERNAL]
    assert len(untrusted) >= 1
    assert "AB_TEST_SUPERVISOR_ALERT" in untrusted[0].content


def test_ab_operator_alert_on_drawdown_termination(ab_setup):
    """Verify operator fires critical alert when experiment is terminated due to max drawdown breach."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_drawdown_terminated")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "DRAWDOWN_TERMINATED" for a in state["alerts"])

    dd_alert = next(a for a in state["alerts"] if a["alert_type"] == "DRAWDOWN_TERMINATED")
    assert dd_alert["severity"] == "critical"
    assert "terminated early due to drawdown" in dd_alert["message"]


def test_ab_operator_alert_on_experiment_completed(ab_setup):
    """Verify operator fires completion alert when 100% duration is reached."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_completed")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert any(a["alert_type"] == "EXPERIMENT_COMPLETED" for a in state["alerts"])


def test_ab_operator_inactive_when_no_test(ab_setup):
    """Verify operator stays inactive and healthy when no test is running."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_no_test")
    watchdog.alerted_events.clear()

    state = watchdog.check_state()
    assert state["status"] == "INACTIVE"
    assert len(state["alerts"]) == 0


def test_ab_skill_registered_in_registry():
    """Verify ABTestMonitorSkill is automatically loaded by default in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("ab_test_monitor")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
