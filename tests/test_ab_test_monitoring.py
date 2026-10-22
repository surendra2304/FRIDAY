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
    # Honest wording: "reported as running" describes where the status came from.
    assert "A/B experiment 'AI_Universe_Volatility_Overlay' is reported as running" in status["spoken_summary"]
    assert "42.9% complete (72.0h of 168.0h planned)" in status["spoken_summary"]
    assert "38 Control trades vs 40 Treatment trades" in status["spoken_summary"]


def test_ab_skill_get_results(ab_setup):
    """Test get_ab_results computes metric deltas and statistical significance."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("ab_stat_sig_reached")

    results = skill.get_ab_results()
    assert results["active"] is True
    assert results["stat_sig_achieved"] is True
    assert results["p_value"] == 0.015
    # 98.5 as reported by the payload, not the old int()-truncated 98.
    assert results["confidence_pct"] == pytest.approx(98.5, 0.01)
    assert results["confidence_derived"] is False
    assert results["delta_return_pct"] == pytest.approx(6.30, 0.01)
    assert results["lead_arm"] == "Treatment"
    assert "Treatment arm is leading by 6.30% excess return" in results["spoken_summary"]
    assert "reported as achieved (p=0.015, 98.5% confidence reported)" in results["spoken_summary"]


def test_ab_skill_explain_ab_difference(ab_setup):
    """Test explain_ab_difference provides detailed outperformance driver analysis."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.set_scenario("mixed")

    exp = skill.explain_ab_difference()
    assert exp["active"] is True
    assert "A/B Performance Divergence Analysis" in exp["explanation"]
    assert "Treatment Arm" in exp["explanation"]
    # The old narrative named catalysts ("Adaptive Risk Parameters", "Drawdown
    # Protection", a hardcoded 2-blocked/5-applied rejection count) that no
    # endpoint sent. The analysis now shows the reported readings and the
    # reported overlay, and says what was not reported.
    assert "**Reported Treatment Overlays:**" in exp["explanation"]
    assert "`btc_sl_pct`: 0.4" in exp["explanation"]
    assert "No safety-gate rejection statistics were reported for this experiment." in exp["explanation"]
    assert "p-value = `0.082`" in exp["explanation"]


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


# =========================================================================
# Honesty pins: nothing is invented when the experiment reports nothing
# =========================================================================

def test_ab_skill_reports_no_metrics_when_the_arms_report_none(ab_setup):
    """An experiment running with empty arm payloads reports unknown, not $10,000 arms."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.state.ab_override = {
        "test_name": "Overlay_Evaluation",
        "status": "RUNNING",
        "control_arm": {},
        "treatment_arm": {},
    }
    try:
        results = skill.get_ab_results()
        assert results["active"] is True
        assert results["control"]["equity"] is None
        assert results["treatment"]["sharpe_ratio"] is None
        assert results["delta_return_pct"] is None
        assert results["control"]["trade_count"] is None
        assert results["lead_arm"] is None
        assert results["stat_sig_achieved"] is None
        assert results["p_value"] is None
        assert results["confidence_pct"] is None
        assert "Neither arm can be called ahead" in results["spoken_summary"]
        assert "No p-value was reported" in results["spoken_summary"]

        report = skill.generate_ab_report()["report_markdown"]
        assert report.count("unknown (no reading)") >= 6
        assert "❔ UNKNOWN (no p-value reported)" in report
        assert "NO RECOMMENDATION POSSIBLE" in report

        explanation = skill.explain_ab_difference()["explanation"]
        assert "Neither arm's total return was reported in full" in explanation
        assert "No parameter overlay was reported for the treatment arm." in explanation
    finally:
        server.state.ab_override = None


def test_ab_confidence_is_labelled_when_it_is_derived_from_the_p_value(ab_setup):
    """A confidence figure the experiment never sent is marked as derived."""
    skill, watchdog, operator, memory, mock_notif, server = ab_setup
    server.state.ab_override = {
        "test_name": "Overlay_Evaluation",
        "status": "RUNNING",
        "control_arm": {"total_return_pct": 1.0},
        "treatment_arm": {"total_return_pct": 2.25},
        "statistics": {"p_value": 0.02, "stat_sig_achieved": True},
    }
    try:
        results = skill.get_ab_results()
        assert results["confidence_pct"] == pytest.approx(98.0, 0.01)
        assert results["confidence_derived"] is True
        assert "98.0% confidence, derived from that p-value" in results["spoken_summary"]
        assert "derived from the p-value" in skill.generate_ab_report()["report_markdown"]
    finally:
        server.state.ab_override = None
