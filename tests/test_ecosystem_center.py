"""Comprehensive Test Suite for FRIDAY Unified Ecosystem Command Center."""

import pytest

from friday.ecosystem.command_router import EcosystemCommandRouter, SubsystemRoute
from friday.ecosystem.cross_orchestrator import (
    CrossBuildTemplate,
    CrossSystemOrchestrator,
)
from friday.ecosystem.registry import EcosystemRegistry
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.forge_manager import ForgeManagerSkill
from friday.ui.ecosystem_panel import EcosystemDashboardPanel
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow


@pytest.fixture
def ecosystem_center_setup():
    registry = EcosystemRegistry()
    forge_mgr = ForgeManagerSkill()
    status_skill = EcosystemStatusSkill(registry=registry)
    briefing_wf = MasterDailyBriefingWorkflow(registry=registry)
    panel = EcosystemDashboardPanel(registry=registry)
    cross_orch = CrossSystemOrchestrator(forge_manager=forge_mgr)
    router = EcosystemCommandRouter(
        cross_orchestrator=cross_orch,
        status_skill=status_skill,
        forge_manager=forge_mgr,
    )

    return registry, status_skill, briefing_wf, panel, cross_orch, router


# =========================================================================
# 1. Ecosystem Registry Aggregation & Health Tests
# =========================================================================

def test_ecosystem_registry_aggregation_and_health(ecosystem_center_setup):
    """Verify registry aggregation, health check execution, and last-known-good tracking."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    # List registered subsystems
    subs = registry.list_subsystems()
    assert len(subs) >= 3
    names = [s.name for s in subs]
    assert "trading_bot" in names
    assert "forge" in names
    assert "ai_universe" in names

    # Status aggregation
    status = registry.get_ecosystem_status()
    assert status["subsystems_count"] >= 3
    assert status["subsystems"]["trading_bot"]["status"] == "RUNNING"
    assert status["subsystems"]["forge"]["status"] == "IDLE"

    # Health checks
    health = registry.get_ecosystem_health()
    assert health["overall_health"] == "HEALTHY"
    assert health["all_healthy"] is True
    assert health["subsystems"]["trading_bot"]["status"] == "HEALTHY"

    # Last known good
    lkg = registry.get_last_known_good("trading_bot")
    assert lkg is not None
    assert lkg["equity_usdt"] == 10450.0


# =========================================================================
# 2. Unified Status Skill Tests
# =========================================================================

def test_unified_status_skill_commands(ecosystem_center_setup):
    """Verify voice commands for full ecosystem status, trading, forge, health, and briefing."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    # 1. Status of everything
    res_all = status_skill.execute("Status of everything")
    assert res_all.success is True
    assert "Unified Ecosystem Master Status Report" in res_all.output
    assert "Trading Bot:" in res_all.output
    assert "Forge:" in res_all.output
    assert "AI-Universe:" in res_all.output

    # 2. Trading status
    res_trade = status_skill.execute("Trading status")
    assert res_trade.success is True
    assert "Trading Bot Status: RUNNING" in res_trade.output
    assert "$10,450.00 USDT" in res_trade.output

    # 3. Forge status
    res_forge = status_skill.execute("Forge status")
    assert res_forge.success is True
    assert "FORGE Status: IDLE" in res_forge.output
    assert "portfolio website" in res_forge.output

    # 4. Health audit
    res_health = status_skill.execute("What's the health of my systems?")
    assert res_health.success is True
    assert "Ecosystem Health Audit:" in res_health.output

    # 5. Brief me
    res_brief = status_skill.execute("Brief me")
    assert res_brief.success is True
    assert "ecosystem briefing" in res_brief.output


# =========================================================================
# 3. Master Daily Briefing Workflow Tests
# =========================================================================

def test_master_daily_briefing_workflow(ecosystem_center_setup):
    """Verify Morning Strategic Briefing and Evening Performance Wrap-up generation."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    # Morning briefing
    morning = briefing_wf.generate_morning_briefing()
    assert morning.briefing_type == "MORNING"
    assert "Good morning, Operator." in morning.spoken_summary
    assert "# 🌅 FRIDAY Master Morning Executive Briefing" in morning.markdown_report
    assert "Quantitative Trading Overview" in morning.markdown_report
    assert "FORGE Software Engineering Status" in morning.markdown_report

    # Evening briefing
    evening = briefing_wf.generate_evening_briefing()
    assert evening.briefing_type == "EVENING"
    assert "Good evening, Operator." in evening.spoken_summary
    assert "# 🌃 FRIDAY Master Evening Performance Wrap-Up" in evening.markdown_report


# =========================================================================
# 4. Ecosystem Dashboard Panel Tests
# =========================================================================

def test_ecosystem_dashboard_panel_assembly(ecosystem_center_setup):
    """Verify multi-subsystem cards, alert feed, and markdown assembly."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    data = panel.render_panel_data()
    assert data["title"] == "FRIDAY Unified Ecosystem Command Panel"
    assert "trading_bot" in data["cards"]
    assert "forge" in data["cards"]
    assert "ai_universe" in data["cards"]
    assert len(data["alerts_feed"]) >= 2
    assert len(data["one_click_actions"]) >= 2

    md = panel.render_markdown()
    assert "# 🌐 FRIDAY Unified Ecosystem Command Panel" in md
    assert "Trading Bot Card" in md
    assert "FORGE Engine Card" in md


# =========================================================================
# 5. Cross-System Orchestrator Tests
# =========================================================================

def test_cross_system_orchestrator_builds(ecosystem_center_setup):
    """Verify multi-system workflow preparation, template matching, and execution."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    # Prepare trading dashboard build
    plan = cross_orch.prepare_cross_system_build("TRADING_DASHBOARD")
    assert plan.template == CrossBuildTemplate.TRADING_DASHBOARD
    assert plan.status == "PENDING_CONFIRMATION"
    assert "GET /api/status" in plan.generated_spec

    # Confirm and execute
    exec_res = cross_orch.confirm_and_execute_build(plan.plan_id, confirmation=True)
    assert exec_res["success"] is True
    assert "forge_task_" in exec_res["task_id"]

    # Rejection flow
    plan2 = cross_orch.prepare_cross_system_build("PERFORMANCE_REPORTER")
    reject_res = cross_orch.confirm_and_execute_build(plan2.plan_id, confirmation=False)
    assert reject_res["success"] is False
    assert "rejected by operator" in reject_res["message"]


# =========================================================================
# 6. Ecosystem Command Router Tests
# =========================================================================

def test_ecosystem_command_router_intents(ecosystem_center_setup):
    """Verify routing of voice commands to respective subsystems."""
    registry, status_skill, briefing_wf, panel, cross_orch, router = ecosystem_center_setup

    # Cross build
    route, ctx = router.route_command("Forge, build a trading dashboard for my bot")
    assert route == SubsystemRoute.CROSS_SYSTEM_ORCHESTRATOR
    assert ctx["template"] == "TRADING_DASHBOARD"

    # Status
    route, _ = router.route_command("Status of everything")
    assert route == SubsystemRoute.ECOSYSTEM_STATUS

    # FORGE
    route, _ = router.route_command("Forge, build a portfolio website")
    assert route == SubsystemRoute.FORGE

    # Trading Bot
    route, _ = router.route_command("How are my trades doing today?")
    assert route == SubsystemRoute.TRADING_BOT

    # AI-Universe
    route, _ = router.route_command("What does AI Universe predict for BTC?")
    assert route == SubsystemRoute.AI_UNIVERSE

    # Ambiguous
    route, _ = router.route_command("xyz 123 gibberish query")
    assert route == SubsystemRoute.AMBIGUOUS
