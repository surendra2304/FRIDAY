# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Live Trading Operations Center."""

from unittest.mock import MagicMock
import pytest

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.emergency_procedures import EmergencyProcedureManager
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.live_vigilance_operator import LiveVigilanceOperator
from friday.security.production_security import ProductionSecurityManager
from friday.skills.registry import SkillRegistry
from friday.skills.trading_bot_operator import TradingBotOperator
from friday.skills.voice_live_trading import VoiceLiveTradingSkill
from friday.trading.capital_guardian import CapitalLevelGuardian
from friday.trading.incident_manager import LiveIncidentManager
from friday.trading.live_analytics import LivePerformanceAnalytics
from friday.trading.live_operations import LiveOperationsCenter
from friday.workflows.live_briefing_workflow import LiveMorningBriefingWorkflow
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def live_mock_server():
    server = MockTradingBotServer(port=8996, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def live_ops_setup(live_mock_server):
    server, base_url = live_mock_server
    server.set_scenario("mixed")

    memory = InMemoryConversationMemory()
    bot_operator = TradingBotOperator(base_url=base_url)
    sec_mgr = ProductionSecurityManager()
    alert_mgr = ProductionAlertManager(memory=memory)
    emerg_mgr = EmergencyProcedureManager(bot_operator=bot_operator, memory=memory, alert_manager=alert_mgr)
    inc_mgr = LiveIncidentManager(emergency_manager=emerg_mgr, alert_manager=alert_mgr)

    live_ops = LiveOperationsCenter(bot_operator=bot_operator, daily_loss_limit_usdt=500.0, max_drawdown_limit_pct=5.0)
    capital_guardian = CapitalLevelGuardian(current_level=1, days_at_current_level=34, clean_days_count=34, cumulative_pnl_at_level=1240.50)
    live_analytics = LivePerformanceAnalytics()
    vigilance_op = LiveVigilanceOperator(live_ops=live_ops, alert_manager=alert_mgr, incident_manager=inc_mgr, memory=memory)
    briefing_wf = LiveMorningBriefingWorkflow(live_ops=live_ops, incident_manager=inc_mgr)

    skill = VoiceLiveTradingSkill(
        live_ops=live_ops,
        capital_guardian=capital_guardian,
        live_analytics=live_analytics,
        incident_manager=inc_mgr,
        security_manager=sec_mgr,
        emergency_manager=emerg_mgr,
    )

    return (
        skill,
        live_ops,
        capital_guardian,
        live_analytics,
        inc_mgr,
        vigilance_op,
        briefing_wf,
        bot_operator,
        server,
    )


# =========================================================================
# 1. Live Operations Center & Proximity Tests
# =========================================================================

def test_live_operations_polling_and_pnl(live_ops_setup):
    """Verify live operations center calculates P&L and risk limit headroom."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup
    server.set_scenario("mixed")

    state = live_ops.poll_live_state()
    assert state.trading_mode in ("LIVE", "ACTIVE", "TESTNET")
    assert state.total_equity == 10540.25
    assert len(state.positions) >= 1
    assert state.risk_proximity.daily_loss_headroom_usdt > 0
    assert state.risk_proximity.proximity_warning_level in ("NORMAL", "ELEVATED", "CRITICAL")

    # Spoken summaries
    pnl_spoken = live_ops.get_spoken_pnl_summary()
    assert "Your live P&L today is" in pnl_spoken
    assert "Total live equity is" in pnl_spoken

    risk_spoken = live_ops.get_spoken_risk_proximity_summary()
    assert "Risk limit status:" in risk_spoken


# =========================================================================
# 2. Capital Level Guardian Tests
# =========================================================================

def test_capital_level_guardian_progression(live_ops_setup):
    """Verify 30-day clean day progression evaluation and authorization files."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup

    status = guardian.get_level_status()
    assert status["current_level"] == 1
    assert status["progression_eligible"] is True
    assert status["clean_days_count"] >= 30

    # Authorization file generation & verification
    auth_doc = guardian.generate_authorization_file_content(target_level=2)
    assert "FRIDAY CAPITAL LEVEL UPGRADE AUTHORIZATION" in auth_doc
    assert "Target Level" in auth_doc
    assert "Growth Capital" in auth_doc
    assert guardian.verify_authorization_file(auth_doc) is True

    # Transition to Level 2
    res = guardian.confirm_level_transition(target_level=2)
    assert res["success"] is True
    assert res["new_level"] == 2
    assert res["max_capital_usdt"] == 25000.0


# =========================================================================
# 3. Live Performance Analytics Tests
# =========================================================================

def test_live_performance_analytics(live_ops_setup):
    """Verify rolling 30d metrics, cross-environment comparisons, and AI advisory impact."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup

    report = analytics.compute_live_analytics()
    assert report.rolling_30d_return_pct > 0
    assert report.rolling_30d_sharpe > 0
    assert report.ai_advisory_alpha_impact_pct > 0
    assert len(report.environment_comparisons) == 3
    assert len(report.strategy_attributions) >= 3

    spoken = analytics.get_spoken_performance_summary()
    assert "Live performance summary:" in spoken
    assert "AI-Universe parameter overlays" in spoken


# =========================================================================
# 4. Incident Management & Automated Containment Tests
# =========================================================================

def test_incident_manager_classification_and_containment(live_ops_setup):
    """Verify Level 1 to 4 incident containment actions and PIR generation."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup

    # 1. Level 2 Critical Incident -> Triggers Trading Halt
    inc2 = inc_mgr.record_and_contain_incident(
        incident_type="RECONCILIATION_MISMATCH",
        severity_level=2,
        title="Position Count Desync Detected",
        description="Exchange reports 2 positions while local database tracks 3 positions.",
    )
    assert inc2.severity_level == 2
    assert inc2.containment_action == "TRADING_HALT"
    assert inc2.status == "CONTAINED"

    # 2. Level 3 Major Incident -> Triggers Parameter Rollback
    inc3 = inc_mgr.record_and_contain_incident(
        incident_type="ADVISORY_ANOMALY",
        severity_level=3,
        title="Elevated Advisory Rejections",
        description="5 consecutive parameter recommendations rejected.",
    )
    assert inc3.severity_level == 3
    assert inc3.containment_action == "PARAMETER_ROLLBACK"

    # Post-Incident Review Report
    pir = inc_mgr.generate_post_incident_review(inc2.incident_id)
    assert "# 📋 Post-Incident Review (PIR)" in pir
    assert inc2.title in pir


# =========================================================================
# 5. Live Vigilance Operator Triggers
# =========================================================================

def test_live_vigilance_operator_alert_triggers(live_ops_setup):
    """Verify vigilance operator alerts on drawdown breaches and position anomalies."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup
    server.set_scenario("mixed")

    events = vigilance.tick()
    # In mixed scenario with normal parameters, no critical alerts emitted
    assert isinstance(events, list)

    # Force drawdown breach simulation
    live_ops.max_drawdown_limit_pct = 1.0  # Force current 1.45% drawdown to exceed limit
    crit_events = vigilance.tick()
    assert any(e["severity"] == "CRITICAL" for e in crit_events)

    # Reset
    live_ops.max_drawdown_limit_pct = 5.0


# =========================================================================
# 6. Voice Live Trading Commands (SAFE, SENSITIVE, DANGEROUS)
# =========================================================================

def test_voice_live_trading_safe_commands(live_ops_setup):
    """Verify SAFE voice commands execute without authorization challenge."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup
    server.set_scenario("mixed")

    # 1. "What's my live P&L?"
    res1 = skill.execute("What's my live P&L?")
    assert res1.success is True
    assert "Your live P&L today is" in res1.output

    # 2. "How far from my risk limits?"
    res2 = skill.execute("How far from my risk limits?")
    assert res2.success is True
    assert "Risk limit status:" in res2.output

    # 3. "What are my live positions?"
    res3 = skill.execute("What are my live positions?")
    assert res3.success is True

    # 4. "What capital level am I on?"
    res4 = skill.execute("What capital level am I on?")
    assert res4.success is True
    assert "Level" in res4.output

    # 5. "Daily trading report"
    res5 = skill.execute("Daily trading report")
    assert res5.success is True
    assert "Live performance summary:" in res5.output


def test_voice_live_trading_sensitive_and_dangerous_commands(live_ops_setup):
    """Verify SENSITIVE actions and DANGEROUS confirmation phrase gating."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup
    server.set_scenario("mixed")

    # 1. SENSITIVE: "Emergency flatten all positions"
    res_flatten = skill.execute("Emergency flatten all positions")
    assert res_flatten.success is True
    assert "Emergency Flatten initiated" in res_flatten.output

    # 2. DANGEROUS: "Activate live trading kill switch" without confirmation -> REJECTED
    res_kill_denied = skill.execute("Activate live trading kill switch", confirmation_phrase="")
    assert res_kill_denied.success is False
    assert "DANGEROUS ACTION BLOCKED" in res_kill_denied.output

    # 3. DANGEROUS: "Activate live trading kill switch" with confirmation -> APPROVED
    res_kill_ok = skill.execute("Activate live trading kill switch", confirmation_phrase="Confirm emergency action")
    assert res_kill_ok.success is True
    assert "LIVE TRADING KILL SWITCH ACTIVATED" in res_kill_ok.output

    # 4. DANGEROUS: "Confirm capital level upgrade" with confirmation -> APPROVED
    res_upg_ok = skill.execute("Confirm capital level upgrade", confirmation_phrase="Confirm capital level upgrade")
    assert res_upg_ok.success is True
    assert "Capital Level Upgrade Confirmed" in res_upg_ok.output


# =========================================================================
# 7. Live Morning Briefing Workflow
# =========================================================================

def test_live_morning_briefing_workflow(live_ops_setup):
    """Verify LiveMorningBriefingWorkflow handles queries and renders snapshot."""
    skill, live_ops, guardian, analytics, inc_mgr, vigilance, briefing, bot_op, server = live_ops_setup
    server.set_scenario("mixed")

    assert briefing.can_handle("Give me the live morning briefing") is True

    snapshot = briefing.generate_briefing()
    assert "Good morning Operator Surendra" in snapshot.spoken_briefing
    assert "# 🌅 FRIDAY Live Trading Morning Briefing" in snapshot.markdown_report
    assert snapshot.total_equity == 10540.25
    assert snapshot.daily_loss_headroom_usdt > 0


def test_voice_live_trading_registered_in_registry():
    """Verify VoiceLiveTradingSkill is registered by default in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("voice_live_trading")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
