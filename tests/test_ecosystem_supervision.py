"""Comprehensive Test Suite for FRIDAY Ecosystem Command & Supervision Subsystem."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.ecosystem.command_center import (
    AutonomyLevel,
    EcosystemCommandCenter,
    EcosystemState,
)
from friday.ecosystem.executive_dashboard import ExecutiveDashboardRenderer
from friday.ecosystem.master_voice import MasterVoiceInterface
from friday.ecosystem.policy_interface import HumanPolicyInterface, PolicyCategory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.guardian_angel import GuardianAngelOperator
from friday.security.production_security import ProductionSecurityManager
from friday.skills.master_voice_skill import MasterVoiceSkill
from friday.skills.registry import SkillRegistry
from friday.trading.evolution_history import EvolutionHistoryTracker
from friday.trading.intelligence_engine import IntelligenceEngine
from friday.workflows.executive_briefing import DailyExecutiveBriefingWorkflow


@pytest.fixture
def ecosystem_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    sec_mgr = ProductionSecurityManager()
    command_center = EcosystemCommandCenter(security_manager=sec_mgr)
    # The centre reports only what an integration has told it, so the fixture
    # supplies a reading the way a real trading bridge would. Tests that want
    # the *unreported* behaviour assert on it explicitly (see
    # test_unreported_systems_are_reported_as_unknown below).
    command_center.record_system_status(
        "trading_bot",
        {
            "status": "HEALTHY",
            "connected_venues": ["Binance", "Bybit", "OKX"],
            "active_positions_count": 3,
            "daily_pnl_usdt": 420.50,
            "aggregate_leverage": 0.85,
            "daily_loss_limit_proximity_pct": 14.5,
            "single_asset_max_exposure_pct": 54.0,
        },
    )
    command_center.record_system_status(
        "ai_universe",
        {"status": "HEALTHY", "model_confidence": 0.84, "active_predictions_count": 3, "latency_ms": 118.0},
    )
    command_center.record_system_status(
        "friday_os",
        {"status": "HEALTHY", "guardian_vigilance": "10S_CONTINUOUS"},
    )
    policy_interface = HumanPolicyInterface()
    intel_engine = IntelligenceEngine()
    history_tracker = EvolutionHistoryTracker()

    master_voice = MasterVoiceInterface(
        command_center=command_center,
        intelligence_engine=intel_engine,
        history_tracker=history_tracker,
    )

    dashboard = ExecutiveDashboardRenderer(
        command_center=command_center,
        policy_interface=policy_interface,
        intelligence_engine=intel_engine,
    )

    operator = GuardianAngelOperator(
        command_center=command_center,
        alert_manager=alert_mgr,
        memory=memory,
    )

    skill = MasterVoiceSkill(
        command_center=command_center,
        policy_interface=policy_interface,
        master_voice=master_voice,
        dashboard_renderer=dashboard,
    )

    briefing_wf = DailyExecutiveBriefingWorkflow(
        command_center=command_center,
        policy_interface=policy_interface,
        intelligence_engine=intel_engine,
        history_tracker=history_tracker,
    )

    return skill, command_center, policy_interface, operator, briefing_wf, sec_mgr, alert_mgr


# =========================================================================
# 1. Human Policy Interface Tests
# =========================================================================

def test_human_policy_interface_rules(ecosystem_setup):
    """Verify human policy creation, storage, and conversational reviews."""
    skill, command_center, policy_iface, operator, briefing_wf, sec_mgr, alert_mgr = ecosystem_setup

    policies = policy_iface.get_active_policies()
    assert len(policies) >= 3

    # Add custom rule
    rule = policy_iface.parse_and_add_policy("Never trade more than 3.5% in a single position")
    assert rule.category == PolicyCategory.POSITION_SIZING
    assert rule.parameter_value == 3.5

    summary = policy_iface.get_spoken_policy_summary()
    assert "active governance policies enforced:" in summary


# =========================================================================
# 2. Ecosystem Command Center & Autonomy Adjustments
# =========================================================================

def test_ecosystem_command_center_and_autonomy_gating(ecosystem_setup):
    """Verify tri-system status, biometric gating on autonomy level adjustments, and signing."""
    skill, command_center, policy_iface, operator, briefing_wf, sec_mgr, alert_mgr = ecosystem_setup

    status = command_center.get_ecosystem_status()
    assert "systems" in status
    assert status["systems"]["trading_bot"]["status"] == "HEALTHY"
    assert status["systems"]["ai_universe"]["status"] == "HEALTHY"
    assert status["systems"]["friday_os"]["status"] == "HEALTHY"

    # Attempt level change without confirmation phrase -> Denied
    ok, msg, sig = command_center.set_autonomy_level(2, verbal_confirmation="")
    assert ok is False
    assert "AUTONOMY REJECTED" in msg

    # Valid change with voice embedding and phrase
    profile = sec_mgr._enrolled_voices["operator_surendra"]
    valid_emb = list(profile.embedding)

    ok2, msg2, sig2 = command_center.set_autonomy_level(
        2,
        speaker_id="operator_surendra",
        voice_embedding=valid_emb,
        verbal_confirmation="Confirm autonomy change",
    )
    assert ok2 is True
    assert sig2 is not None
    assert command_center._autonomy_level == AutonomyLevel.LEVEL_2_SUPERVISED


# =========================================================================
# 3. Guardian Angel Operator Tests
# =========================================================================

def test_guardian_angel_operator_vigilance(ecosystem_setup):
    """A vigilance loop can only flag what it can read.

    The fixture reports a risk posture, so the loop has something to assess;
    when nothing is reported the loop must say it could not assess rather than
    pass the tick (see the companion test).
    """
    """Verify Guardian Angel continuous 10s monitoring, escalation, and responsiveness checks."""
    skill, command_center, policy_iface, operator, briefing_wf, sec_mgr, alert_mgr = ecosystem_setup

    # Normal tick -> no emergency
    events = operator.tick()
    assert isinstance(events, list)

    # Simulate emergency halt state
    command_center._ecosystem_state = EcosystemState.EMERGENCY_HALT
    crit_events = operator.tick()
    assert any(e["type"] == "CRITICAL_STATE_TRANSITION" for e in crit_events)


# =========================================================================
# 4. Master Voice Skill Commands
# =========================================================================

def test_master_voice_commands(ecosystem_setup):
    """Verify natural conversational queries, dashboard rendering, and policy reviews."""
    skill, command_center, policy_iface, operator, briefing_wf, sec_mgr, alert_mgr = ecosystem_setup

    # 1. "How is everything doing?"
    res1 = skill.execute("How is everything doing?")
    assert res1.success is True
    # The reply no longer promises that everything is smooth; with a reported
    # reading it states the reading, and without one it says it cannot.
    assert "Ecosystem state is" in res1.output

    # 2. "Anything I should know about?"
    res2 = skill.execute("Anything I should know about?")
    assert res2.success is True

    # 3. "Should I be worried about anything?"
    res3 = skill.execute("Should I be worried about anything?")
    assert res3.success is True
    # The answer states the readings it has; it no longer promises that the
    # owner has "no immediate concerns" or describes a position nobody has.
    assert "14.5" in res3.output and "0.85" in res3.output
    assert "From what has been reported" in res3.output

    # 4. "What did you learn this week?"
    res4 = skill.execute("What did you learn this week?")
    assert res4.success is True
    assert "Here is what we have learned" in res4.output

    # 5. "Full ecosystem report"
    res5 = skill.execute("Full ecosystem report")
    assert res5.success is True
    assert "FRIDAY Trading Ecosystem — Executive Command" in res5.output

    # 6. "What decisions did the system make today?"
    res6 = skill.execute("What decisions did the system make today?")
    assert res6.success is True
    # Sample decisions are no longer seeded, so a fresh centre honestly has
    # none. Recording one must make it appear in the log.
    assert "Zero autonomous decisions" in res6.output
    from friday.ecosystem.command_center import EcosystemDecision

    centre = skill.master_voice.command_center
    centre.record_decision(
        EcosystemDecision(
            decision_id="dec_test",
            action_type="PARAMETER_OVERLAY",
            details={"strategy": "test", "atr_multiplier": 2.0},
            operator_id="OPERATOR_SURENDRA",
            signature="test-signature",
        )
    )
    res6b = skill.execute("What decisions did the system make today?")
    assert "autonomous decisions today:" in res6b.output
    assert "PARAMETER_OVERLAY" in res6b.output

    # 7. "What are my current policies?"
    res7 = skill.execute("What are my current policies?")
    assert res7.success is True
    assert "active governance policies" in res7.output


# =========================================================================
# 5. Daily Executive Briefing Workflow
# =========================================================================

def test_daily_executive_briefing_workflow(ecosystem_setup):
    """Verify Morning and Evening Executive Briefings."""
    skill, command_center, policy_iface, operator, briefing_wf, sec_mgr, alert_mgr = ecosystem_setup

    assert briefing_wf.can_handle("Give me the morning executive briefing") is True

    morning = briefing_wf.generate_morning_briefing()
    assert "Good morning Operator Surendra" in morning.spoken_briefing
    assert "# 🌅 FRIDAY Morning Executive Briefing" in morning.markdown_report

    evening = briefing_wf.generate_evening_wrapup()
    assert "Good evening Operator Surendra" in evening.spoken_briefing
    assert "# 🌙 FRIDAY Evening Performance Wrap-Up" in evening.markdown_report


def test_master_voice_registered_in_registry():
    """Verify MasterVoiceSkill is registered in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("master_voice")
    assert skill is not None
    assert "trading_bot_control" in skill.required_capabilities


def test_unreported_systems_are_reported_as_unknown():
    """A fresh centre in production must not report health it never measured."""
    centre = EcosystemCommandCenter()
    status = centre.get_ecosystem_status()

    for name in ("trading_bot", "ai_universe", "friday_os"):
        reading = status["systems"][name]
        assert reading["available"] is False
        assert reading["status"] == "UNKNOWN"
    assert status["risk_posture"]["aggregate_leverage"] is None
    assert status["demo_data"] is False
    assert "UNKNOWN" in status["data_provenance"] or "reported" in status["data_provenance"]


def test_a_reported_reading_is_echoed_verbatim():
    centre = EcosystemCommandCenter()
    centre.record_system_status("trading_bot", {"status": "DEGRADED", "daily_pnl_usdt": -12.25})

    reading = centre.get_ecosystem_status()["systems"]["trading_bot"]
    assert reading["available"] is True
    assert reading["status"] == "DEGRADED"
    assert reading["daily_pnl_usdt"] == -12.25
    assert reading["reported_at"]


def test_an_unassessable_tick_says_so_instead_of_passing():
    """The vigilance loop used to crash here; it must report, not guess."""
    operator = GuardianAngelOperator(command_center=EcosystemCommandCenter())
    events = operator.tick()
    assert events == []
    assert operator.last_unassessable, "the loop must record that it could not assess"
