"""Comprehensive End-to-End Ecosystem Test Suite for FRIDAY Operating System.

Verifies deep integration across all 4 managed subsystems and emergency orchestration:
1. test_friday_nexus_integration (voice command -> API call -> parsed response)
2. test_friday_trading_integration (status & panic execution)
3. test_friday_forge_integration (build submission & verification)
4. test_unified_briefing (all 4 subsystems aggregated)
5. test_emergency_halt (full 5-system sequential freeze verified)
6. test_cross_system_orchestration (trading dashboard build flow)
7. test_cascade_failure (AI-Universe down -> auto-isolation -> recovery)
8. test_onboarding_and_personalization (wizard state & dynamic preferences)
9. test_help_system_skill (capabilities roster & domain guides)
"""

import os
import shutil
import tempfile

import pytest

from friday.core.personalization import PersonalizationEngine
from friday.ecosystem.command_router import EcosystemCommandRouter
from friday.ecosystem.cross_orchestrator import (
    CrossBuildTemplate,
    CrossSystemOrchestrator,
)
from friday.ecosystem.emergency_controller import MasterEmergencyController
from friday.ecosystem.registry import EcosystemRegistry
from friday.onboarding.wizard import OnboardingStep, OnboardingWizard
from friday.operators.cascade_detector import CascadeFailureDetector
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.forge_manager import ForgeManagerSkill
from friday.skills.help_system import HelpSystemSkill
from friday.skills.nexus_manager import NexusManagerSkill
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow


@pytest.fixture
def ecosystem_fixture():
    temp_dir = tempfile.mkdtemp()
    state_file = os.path.join(temp_dir, "onboarding_test.json")
    profile_file = os.path.join(temp_dir, "profile_test.json")

    registry = EcosystemRegistry()
    forge_mgr = ForgeManagerSkill()
    nexus_mgr = NexusManagerSkill()
    status_skill = EcosystemStatusSkill(registry=registry)
    briefing_wf = MasterDailyBriefingWorkflow(registry=registry)
    cross_orch = CrossSystemOrchestrator(forge_manager=forge_mgr)
    emergency_ctrl = MasterEmergencyController()
    cascade_det = CascadeFailureDetector()
    router = EcosystemCommandRouter(cross_orchestrator=cross_orch, status_skill=status_skill, forge_manager=forge_mgr)
    wizard = OnboardingWizard(state_file_path=state_file)
    personalization = PersonalizationEngine(profile_file_path=profile_file)
    help_skill = HelpSystemSkill()

    yield {
        "registry": registry,
        "forge_mgr": forge_mgr,
        "nexus_mgr": nexus_mgr,
        "status_skill": status_skill,
        "briefing_wf": briefing_wf,
        "cross_orch": cross_orch,
        "emergency_ctrl": emergency_ctrl,
        "cascade_det": cascade_det,
        "router": router,
        "wizard": wizard,
        "personalization": personalization,
        "help_skill": help_skill,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


# =========================================================================
# 1. Nexus Integration Test
# =========================================================================
def test_friday_nexus_integration(ecosystem_fixture):
    """Verify voice command -> Nexus API client -> parsed response."""
    nexus_mgr = ecosystem_fixture["nexus_mgr"]

    # Voice command: Who's on my website?
    res_visitors = nexus_mgr.execute("Who's on my website?")
    assert res_visitors.success is True
    assert "active visitors on your site" in res_visitors.output
    assert "pricing" in res_visitors.output

    # Voice command: Any new leads?
    res_leads = nexus_mgr.execute("Any new leads?")
    assert res_leads.success is True
    assert "prospective leads" in res_leads.output


# =========================================================================
# 2. Trading Integration Test
# =========================================================================
def test_friday_trading_integration(ecosystem_fixture):
    """Verify Trading Bot status query and panic execution."""
    registry = ecosystem_fixture["registry"]
    status_skill = ecosystem_fixture["status_skill"]

    res_trade = status_skill.execute("Trading status")
    assert res_trade.success is True
    assert "Trading Bot Status: RUNNING" in res_trade.output
    assert "$10,450.00 USDT" in res_trade.output


# =========================================================================
# 3. Forge Integration Test
# =========================================================================
def test_friday_forge_integration(ecosystem_fixture):
    """Verify Forge build request submission, task tracking, and artifact inspection."""
    forge_mgr = ecosystem_fixture["forge_mgr"]

    # Submit build
    submit_res = forge_mgr.submit_build_request("Build a responsive portfolio website")
    assert "forge_task_" in submit_res["task_id"]
    assert submit_res["status"] in ("SUBMITTED", "READY", "RUNNING")

    # Inspect status
    task_id = submit_res["task_id"]
    stat = forge_mgr.get_task_status(task_id)
    assert stat["task_id"] == task_id
    assert "eta_seconds" in stat


# =========================================================================
# 4. Unified Briefing Aggregation Test
# =========================================================================
def test_unified_briefing_all_subsystems(ecosystem_fixture):
    """Verify morning and evening briefings aggregate all 4 subsystems."""
    briefing_wf = ecosystem_fixture["briefing_wf"]

    # Morning
    morning = briefing_wf.generate_morning_briefing()
    assert morning.briefing_type == "MORNING"
    assert "Quantitative Trading Overview" in morning.markdown_report
    assert "FORGE Software Engineering Status" in morning.markdown_report
    assert "Nexus Website & Growth Intelligence" in morning.markdown_report
    assert "AI-Universe Intelligence & Advisory" in morning.markdown_report

    # Evening
    evening = briefing_wf.generate_evening_briefing()
    assert evening.briefing_type == "EVENING"
    assert "Daily Performance Summary" in evening.markdown_report
    assert "Website Traffic & Leads" in evening.markdown_report


# =========================================================================
# 5. Master Emergency Halt Sequence Test
# =========================================================================
def test_emergency_halt_sequence(ecosystem_fixture):
    """Verify 5-system sequential freeze, banner broadcast, and safe resumption."""
    ctrl = ecosystem_fixture["emergency_ctrl"]

    # Failed biometric
    fail_bio = ctrl.execute_master_emergency_halt("Confirm emergency halt", biometric_confidence=0.85)
    assert fail_bio["is_halted"] is False

    # Successful biometric + confirmation phrase
    succ_halt = ctrl.execute_master_emergency_halt("Please confirm emergency halt now", biometric_confidence=0.98)
    assert succ_halt["is_halted"] is True
    assert ctrl.is_emergency_active is True
    assert ctrl.halt_states["trading_bot"].is_halted is True
    assert ctrl.halt_states["nexus"].is_halted is True
    assert ctrl.halt_states["forge"].is_halted is True
    assert ctrl.halt_states["ai_universe"].is_halted is True
    assert ctrl.halt_states["friday_operators"].is_halted is True

    # Bulk resume prohibited
    bulk_deny = ctrl.resume_subsystem("bulk", "tok_valid_123")
    assert bulk_deny["is_resumed"] is False

    # Single subsystem resume
    res_trade = ctrl.resume_subsystem("trading_bot", "tok_valid_123")
    assert res_trade["is_resumed"] is True
    assert ctrl.halt_states["trading_bot"].is_halted is False


# =========================================================================
# 6. Cross-System Orchestration Test
# =========================================================================
def test_cross_system_orchestration_flow(ecosystem_fixture):
    """Verify 'Forge, build a trading dashboard' flow."""
    cross_orch = ecosystem_fixture["cross_orch"]

    plan = cross_orch.prepare_cross_system_build("TRADING_DASHBOARD")
    assert plan.template == CrossBuildTemplate.TRADING_DASHBOARD
    assert plan.status == "PENDING_CONFIRMATION"

    exec_res = cross_orch.confirm_and_execute_build(plan.plan_id, confirmation=True)
    assert exec_res["success"] is True
    assert "forge_task_" in exec_res["task_id"]


# =========================================================================
# 7. Cascade Failure Isolation & Recovery Test
# =========================================================================
def test_cascade_failure_isolation_and_recovery(ecosystem_fixture):
    """Verify automatic fault isolation and recovery detection."""
    cascade_det = ecosystem_fixture["cascade_det"]

    # AI-Universe degraded telemetry
    degraded_telemetry = {
        "ai_universe": {"status": "DOWN", "latency_ms": 6500},
        "trading_bot": {"status": "HEALTHY", "latency_ms": 50},
    }
    events = cascade_det.evaluate_dependency_health(degraded_telemetry)
    assert any(e["type"] == "SUBSYSTEM_ISOLATED" and e["subsystem"] == "ai_universe" for e in events)
    assert "ai_universe" in cascade_det.isolated_subsystems

    # Recovered telemetry
    healthy_telemetry = {
        "ai_universe": {"status": "HEALTHY", "latency_ms": 150, "data_age_sec": 2.0},
    }
    rec_events = cascade_det.evaluate_dependency_health(healthy_telemetry)
    assert any(e["type"] == "SUBSYSTEM_RECONNECTED" and e["subsystem"] == "ai_universe" for e in rec_events)
    assert "ai_universe" not in cascade_det.isolated_subsystems


# =========================================================================
# 8. Onboarding Wizard & Personalization Engine Tests
# =========================================================================
def test_onboarding_and_personalization(ecosystem_fixture):
    """Verify first-run onboarding state transitions and personalization learning."""
    wizard = ecosystem_fixture["wizard"]
    personalization = ecosystem_fixture["personalization"]

    # Onboarding flow
    p1 = wizard.get_current_prompt()
    assert p1["step"] == OnboardingStep.CHECK_ENV

    p2 = wizard.process_step_input({})
    assert p2["step"] == OnboardingStep.API_KEYS

    p3 = wizard.process_step_input({"keys": {"gemini": "key123"}})
    assert p3["step"] == OnboardingStep.SUBSYSTEM_URLS

    # Personalization adaptation
    personalization.record_interruption()
    personalization.record_interruption()
    personalization.record_interruption()
    assert personalization.profile.response_length == "brief"

    res_pref = personalization.update_preferences_explicitly("Change my preferences to detailed responses")
    assert res_pref["success"] is True
    assert personalization.profile.response_length == "detailed"


# =========================================================================
# 9. Help System Skill Test
# =========================================================================
def test_help_system_skill(ecosystem_fixture):
    """Verify capabilities roster and domain-specific guidance."""
    help_skill = ecosystem_fixture["help_skill"]

    # Global capabilities
    res_cap = help_skill.execute("What can you do?")
    assert res_cap.success is True
    assert "Trading Bot" in res_cap.output
    assert "Forge SWE Engine" in res_cap.output
    assert "Nexus Growth Engine" in res_cap.output

    # Trading guide
    res_trade = help_skill.execute("How do I check trades?")
    assert res_trade.success is True
    assert "Trading Bot Commands Guide" in res_trade.output

    # Website suggestions
    res_sug = help_skill.execute("What should I ask about my website?")
    assert res_sug.success is True
    assert "Suggested Questions for Nexus" in res_sug.output
