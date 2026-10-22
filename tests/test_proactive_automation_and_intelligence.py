"""Comprehensive Test Suite for FRIDAY Advanced Proactive Automation & Scheduled Intelligence."""

from datetime import datetime, timedelta, timezone

import pytest

from friday.core.notification_router import SmartNotificationRouter, UrgencyTier
from friday.operators.anomaly_investigator import ProactiveAnomalyInvestigator
from friday.operators.scheduled_intelligence import ScheduledIntelligenceOperator
from friday.workflows.followup_workflow import AutomatedFollowUpWorkflow


@pytest.fixture
def proactive_setup():
    sched_op = ScheduledIntelligenceOperator(default_morning_hour=8, default_morning_minute=30)
    investigator = ProactiveAnomalyInvestigator()
    followup = AutomatedFollowUpWorkflow()
    notif_router = SmartNotificationRouter(quiet_hours_start=22, quiet_hours_end=7)

    return sched_op, investigator, followup, notif_router


# =========================================================================
# 1. Scheduled Intelligence Dynamic Routines & Context Guards Tests
# =========================================================================

def test_scheduled_intelligence_dynamic_routine_and_guards(proactive_setup):
    """Verify routine learning, calendar busy skip, weather deferrals, and market alignment."""
    sched_op, investigator, followup, notif_router = proactive_setup

    # 1. Record morning voice interactions at 07:45 UTC
    base_morning = datetime(2026, 8, 28, 7, 45, tzinfo=timezone.utc)
    for d in range(3):
        sched_op.record_voice_interaction(base_morning - timedelta(days=d))

    learned_time = sched_op.calculate_learned_briefing_time(base_morning)
    assert learned_time.hour == 7
    assert learned_time.minute == 45

    # 2. Calendar busy skip condition
    res_busy = sched_op.evaluate_briefing_eligibility(current_time=base_morning, calendar_busy=True)
    assert res_busy.should_run is False
    assert res_busy.is_meeting_in_progress is True
    assert "calendar meeting" in res_busy.reason

    # 3. Severe weather deferral
    res_weather = sched_op.evaluate_briefing_eligibility(current_time=base_morning, severe_weather_alert=True)
    assert res_weather.should_run is False
    assert res_weather.is_severe_weather is True

    # 4. Market closed deferral
    res_closed = sched_op.evaluate_briefing_eligibility(current_time=base_morning, market_open=False)
    assert res_closed.should_run is False
    assert res_closed.market_status == "CLOSED"

    # 5. Optimal window trigger (within 15m)
    res_ok = sched_op.evaluate_briefing_eligibility(current_time=base_morning)
    assert res_ok.should_run is True
    assert "Optimal briefing window reached" in res_ok.reason


# =========================================================================
# 2. Proactive Anomaly Investigator Tests
# =========================================================================

def test_proactive_anomaly_investigator(proactive_setup):
    """Verify autonomous pre-inquiry investigation across Trading, Nexus, and Cross-System."""
    sched_op, investigator, followup, notif_router = proactive_setup

    # 1. Trading Bot Drawdown Investigation
    res_trade = investigator.investigate_trading_anomaly(
        daily_loss_pct=3.2,
        underperforming_strategy="Supertrend",
        ai_advisory_involved=True,
    )
    assert res_trade.subsystem == "trading_bot"
    assert "Supertrend strategy was the driver" in res_trade.spoken_voice_prompt
    assert "AI-Universe advisory was active" in res_trade.root_cause

    # 2. Nexus Conversion Drop Correlated Deploy Investigation
    res_nexus = investigator.investigate_nexus_anomaly(
        conversion_drop_pct=38.5,
        recent_deployment_id="dep_prod_8829",
    )
    assert res_nexus.subsystem == "nexus"
    assert "dep_prod_8829" in res_nexus.spoken_voice_prompt
    assert "layout shift" in res_nexus.root_cause

    # 3. Cross-System Cascading Degraded Investigation
    res_cross = investigator.investigate_cross_system_anomaly(
        ai_universe_status="DEGRADED",
        forge_failures_count=5,
    )
    assert res_cross.subsystem == "cross_ecosystem"
    assert "AI-Universe upstream provider degradation" in res_cross.spoken_voice_prompt
    assert "not a FORGE engine bug" in res_cross.root_cause


# =========================================================================
# 3. Automated Recommendation Follow-Up Workflow Tests
# =========================================================================

def test_automated_followup_workflow(proactive_setup):
    """Verify recommendation tracking, 24h unacted reminders, and outcome retrospectives."""
    sched_op, investigator, followup, notif_router = proactive_setup

    # 1. Record Recommendation
    rec = followup.record_recommendation(
        rec_id="rec_pause_supertrend",
        subsystem="trading_bot",
        proposed_action="Pause Supertrend strategy",
        rationale="Elevated market volatility causing consecutive stop losses",
        baseline_metric=-180.0,
        confidence=0.80,
    )
    assert rec.status == "PROPOSED"

    # 2. Acknowledge Recommendation
    followup.acknowledge_recommendation("rec_pause_supertrend")
    assert rec.status == "ACKNOWLEDGED"

    # 3. 24h Unacted Reminder Check
    future_25h = rec.created_at + timedelta(hours=25)
    reminders = followup.check_unacted_reminders(current_time=future_25h)
    assert len(reminders) == 1
    assert "Gentle reminder" in reminders[0].spoken_prompt

    # 4. Retrospective Outcome Evaluation (2 days later with +350 USDT improvement)
    future_2d = rec.created_at + timedelta(days=2)
    outcome = followup.evaluate_outcome("rec_pause_supertrend", current_metric=170.0, current_time=future_2d)
    assert outcome is not None
    assert "I suggested pausing Supertrend 2 days ago" in outcome.spoken_prompt
    assert outcome.delta_metric == 350.0
    assert outcome.is_positive_outcome is True
    assert rec.confidence > 0.80  # Calibrated upwards


# =========================================================================
# 4. Smart Notification Router & Quiet Hours Tests
# =========================================================================

def test_smart_notification_router_and_quiet_hours(proactive_setup):
    """Verify 4 urgency tiers, quiet hours muting, and weekend ignore learning."""
    sched_op, investigator, followup, notif_router = proactive_setup

    # 1. Normal Daytime Routing (14:00 UTC)
    daytime = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    notif_high = notif_router.route_notification(
        tier=UrgencyTier.HIGH,
        title="High Intent Lead Detected",
        message="Enterprise lead from acme.com",
        current_time=daytime,
    )
    assert "voice" in notif_high.target_channels
    assert notif_high.is_quiet_hours_muted is False

    # 2. Quiet Hours (23:30 UTC): HIGH is muted to push/dashboard
    quiet_night = datetime(2026, 8, 28, 23, 30, tzinfo=timezone.utc)
    notif_quiet_high = notif_router.route_notification(
        tier=UrgencyTier.HIGH,
        title="Advisory Suggestion",
        message="Suggested parameter update",
        current_time=quiet_night,
    )
    assert "voice" not in notif_quiet_high.target_channels
    assert notif_quiet_high.is_quiet_hours_muted is True

    # 3. Quiet Hours (23:30 UTC): CRITICAL bypasses quiet hours with voice
    notif_crit = notif_router.route_notification(
        tier=UrgencyTier.CRITICAL,
        title="EMERGENCY TRADING HALT",
        message="Exchange connectivity drop",
        current_time=quiet_night,
    )
    assert "voice" in notif_crit.target_channels
    assert notif_crit.is_quiet_hours_muted is False

    # 4. Weekend Ignore Learning
    weekend_sat = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)  # Saturday
    notif_router.record_user_feedback(was_ignored_on_weekend=True)
    notif_router.record_user_feedback(was_ignored_on_weekend=True)

    notif_med = notif_router.route_notification(
        tier=UrgencyTier.MEDIUM,
        title="Weekly Summary Digest",
        message="Summary of completed builds",
        current_time=weekend_sat,
    )
    assert "briefing_queue" in notif_med.target_channels
    queued = notif_router.drain_briefing_queue()
    assert len(queued) >= 1
