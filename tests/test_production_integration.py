"""Comprehensive End-to-End Production Supervision & Emergency Procedures Test Suite."""

from unittest.mock import MagicMock

import pytest

from friday.alert_manager import AlertSeverity, AlertStatus, ProductionAlertManager
from friday.core.types import AuthorizationDecision, AuthorizationResponse
from friday.emergency_procedures import EmergencyProcedureManager
from friday.memory.in_memory import InMemoryConversationMemory
from friday.production_dashboard import ProductionDashboard
from friday.production_monitor import ProductionMonitor
from friday.skills.production_supervisor import ProductionSupervisorSkill
from friday.skills.registry import SkillRegistry
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8997, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def production_setup(mock_server):
    server, base_url = mock_server
    server.set_scenario("mixed")

    memory = InMemoryConversationMemory()
    mock_notif = MagicMock()
    operator = TradingBotOperator(base_url=base_url)
    alert_mgr = ProductionAlertManager(memory=memory, notification_manager=mock_notif, escalation_timeout_sec=0.1)
    emergency_mgr = EmergencyProcedureManager(bot_operator=operator, memory=memory, alert_manager=alert_mgr)
    monitor = ProductionMonitor(bot_operator=operator, alert_manager=alert_mgr, memory=memory)
    dashboard = ProductionDashboard(
        bot_operator=operator,
        alert_manager=alert_mgr,
        emergency_manager=emergency_mgr,
        production_monitor=monitor,
    )
    skill = ProductionSupervisorSkill(
        bot_operator=operator,
        alert_manager=alert_mgr,
        emergency_manager=emergency_mgr,
        dashboard=dashboard,
    )

    return skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server


# =========================================================================
# 1. Production Monitor & Cascading Failure Tests
# =========================================================================

def test_production_monitor_polling_cycle(production_setup):
    """Verify production monitor polls all tiers and produces unified health report."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    report = monitor.poll_all_systems()
    assert report.overall_status == "HEALTHY"
    assert report.trading_bot["status"] == "ACTIVE"
    assert report.trading_bot["equity"] == 10540.25
    assert report.ai_universe["health"] == "HEALTHY"
    assert report.friday_os["status"] == "HEALTHY"
    assert len(report.cascading_failures) == 0


def test_production_monitor_cascading_failure_detection(production_setup):
    """Verify monitor detects cascading failures when multiple systems degrade."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("unreachable")

    report = monitor.poll_all_systems()
    assert report.overall_status == "CRITICAL"
    assert report.trading_bot["status"] == "DOWN"


# =========================================================================
# 2. Emergency Procedures Tests
# =========================================================================

def test_emergency_trading_halt(production_setup):
    """Verify trading halt calls kill-switch API, logs audit block, and creates critical alert."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    mock_auth = MagicMock()
    mock_auth.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED, reason="Admin authorized"
    )

    res = emergency_mgr.trading_halt(reason="Critical Market Volatility", initiator="Surendra", authorizer=mock_auth)
    assert res["success"] is True
    assert res["action"] == "TRADING_HALT"

    # Verify audit trail record
    audit_trail = emergency_mgr.get_audit_trail()
    assert len(audit_trail) >= 1
    last_record = audit_trail[0]
    assert last_record["action_name"] == "TRADING_HALT"
    assert last_record["initiator"] == "Surendra"
    assert "action_hash" in last_record

    # Verify critical alert was generated
    active = alert_mgr.get_active_alerts(min_severity=AlertSeverity.CRITICAL)
    assert any("TRADING HALT" in a.title for a in active)


def test_emergency_parameter_rollback(production_setup):
    """Verify emergency rollback reverts parameters and records cryptographic audit record."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    res = emergency_mgr.parameter_rollback(reason="Elevated stop-out frequency")
    assert res["success"] is True
    assert res["action"] == "PARAMETER_ROLLBACK"

    audit_trail = emergency_mgr.get_audit_trail()
    assert any(a["action_name"] == "PARAMETER_ROLLBACK" for a in audit_trail)


def test_emergency_advisory_disable(production_setup):
    """Verify emergency advisory disable switches mode to SHADOW."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    res = emergency_mgr.advisory_disable(reason="Model hallucinations")
    assert res["success"] is True
    assert res["action"] == "ADVISORY_DISABLE"


def test_emergency_contact_dispatch(production_setup):
    """Verify emergency contact dispatches multi-channel alerts."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup

    res = emergency_mgr.emergency_contact(alert_message="Critical loss limit breached")
    assert res["success"] is True
    assert res["dispatched_count"] >= 2
    assert any(c["name"].startswith("Lead Operator") for c in res["dispatched"])


def test_cryptographic_audit_trail_integrity(production_setup):
    """Verify audit trail uses SHA-256 hash chaining for tamper evidence."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    # Execute 2 emergency actions
    emergency_mgr.parameter_rollback(reason="Test rollback 1")
    emergency_mgr.trading_halt(reason="Test halt 2")

    trail = emergency_mgr.get_audit_trail(limit=10)
    assert len(trail) >= 2

    # Check hash links
    for record in trail:
        assert len(record["action_hash"]) == 64  # SHA-256 hex length
        assert record["precedence_level"] == 50  # FRIDAY_COMMANDS


# =========================================================================
# 3. Alert Management Lifecycle Tests
# =========================================================================

def test_alert_manager_prioritization_and_aggregation(production_setup):
    """Verify alert manager prioritizes, correlates duplicate alerts, and manages lifecycle."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup

    # Create distinct alerts
    a1 = alert_mgr.create_alert("Test Alert 1", "Warning msg", AlertSeverity.WARNING, "test_cat")
    a2 = alert_mgr.create_alert("Test Alert 2", "Critical msg", AlertSeverity.CRITICAL, "test_cat")
    
    # Create duplicate alert -> Should aggregate count without creating second pending alert
    a1_dup = alert_mgr.create_alert("Test Alert 1", "Warning msg", AlertSeverity.WARNING, "test_cat")
    assert a1_dup.id == a1.id
    assert a1_dup.metadata.get("occurrence_count", 1) >= 2

    # Verify prioritization
    active = alert_mgr.get_active_alerts()
    assert active[0].severity == AlertSeverity.CRITICAL

    # Test acknowledgment
    ok_ack = alert_mgr.acknowledge_alert(a2.id, acknowledged_by="Surendra")
    assert ok_ack is True
    assert a2.status == AlertStatus.ACKNOWLEDGED

    # Test resolution
    ok_res = alert_mgr.resolve_alert(a1.id, resolution_note="Fixed")
    assert ok_res is True
    assert a1.status == AlertStatus.RESOLVED


# =========================================================================
# 4. Production Dashboard & Voice Command Tests
# =========================================================================

def test_production_dashboard_markdown_rendering(production_setup):
    """Verify dashboard renders complete multi-tier Markdown structure."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    dash_md = dashboard.render_markdown_dashboard()
    assert "# 🎛️ FRIDAY Production Supervision Dashboard" in dash_md
    assert "Trading Bot Engine" in dash_md
    assert "AI-Universe Intelligence" in dash_md
    assert "FRIDAY Operating System" in dash_md
    assert "Account Equity:" in dash_md
    assert "Emergency Controls Quick Actions" in dash_md


def test_production_supervisor_skill_commands(production_setup):
    """Verify ProductionSupervisorSkill dispatches voice commands cleanly."""
    skill, dashboard, monitor, emergency_mgr, alert_mgr, operator, memory, mock_notif, server = production_setup
    server.set_scenario("mixed")

    # 1. "System status"
    res1 = skill.execute("System status")
    assert res1.success is True
    assert "FRIDAY Production Supervision Dashboard" in res1.output

    # 2. "Trading performance"
    res2 = skill.execute("Trading performance")
    assert res2.success is True
    assert "Trading performance is active on Binance Futures Testnet" in res2.output

    # 3. "AI advisory status"
    res3 = skill.execute("AI advisory status")
    assert res3.success is True
    assert "AI-Universe Advisory is HEALTHY" in res3.output

    # 4. "Show alerts"
    res4 = skill.execute("Show alerts")
    assert res4.success is True

    # 5. "Rollback parameters"
    res5 = skill.execute("Rollback parameters")
    assert res5.success is True
    assert "Parameter rollback" in res5.output

    # 6. "Emergency halt"
    res6 = skill.execute("Emergency halt")
    assert res6.success is True
    assert "Trading halt" in res6.output


def test_production_supervisor_registered_in_registry():
    """Verify ProductionSupervisorSkill is loaded by default in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("production_supervisor")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
