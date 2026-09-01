"""Comprehensive Test Suite for FRIDAY Multi-Modal Interface & Mobile Companion."""

from datetime import datetime, timedelta, timezone

import pytest

from friday.notifications.bridge import NotificationBridge
from friday.ui.mobile import MobileDashboardInterface
from friday.vision.screen_share import ScreenSharingSession
from friday.voice.conversation import ConversationalVoiceInterface


@pytest.fixture
def multimodal_setup():
    mobile = MobileDashboardInterface()
    bridge = NotificationBridge()
    voice = ConversationalVoiceInterface()
    vision = ScreenSharingSession(idle_timeout_minutes=5)

    return mobile, bridge, voice, vision


# =========================================================================
# 1. Mobile Dashboard Interface Tests
# =========================================================================

def test_mobile_dashboard_tabs_and_double_tap(multimodal_setup):
    """Verify tab navigation, double-tap emergency protection, and offline view."""
    mobile, bridge, voice, vision = multimodal_setup

    # 1. Tab Switching
    assert mobile.set_tab("trading") is True
    assert mobile.set_tab("invalid_tab") is False

    # 2. Double-Tap Emergency Protection (Single tap vs Second tap)
    now = datetime.now(timezone.utc)
    res_single = mobile.handle_emergency_tap("EMERGENCY_HALT", tap_time=now)
    assert res_single["is_confirmed"] is False
    assert res_single["status"] == "AWAITING_SECOND_TAP"

    # Second tap within 2 seconds confirms
    res_double = mobile.handle_emergency_tap("EMERGENCY_HALT", tap_time=now + timedelta(seconds=1.5))
    assert res_double["is_confirmed"] is True
    assert res_double["status"] == "EXECUTED"

    # 3. Render View Cards
    view = mobile.render_mobile_view(is_offline=True)
    assert view.active_tab == "trading"
    assert view.is_offline is True
    assert len(view.cards) >= 1


# =========================================================================
# 2. Notification Bridge Web & Mobile Push Tests
# =========================================================================

def test_notification_bridge_rich_actions(multimodal_setup):
    """Verify dual push formatting, interactive action buttons, and deep links."""
    mobile, bridge, voice, vision = multimodal_setup

    # 1. Trading Alert Push
    trade_push = bridge.create_trading_alert_push("Trading Loss Alert", "Supertrend drawdown breached 2.5%")
    assert trade_push.subsystem == "trading_bot"
    assert len(trade_push.actions) == 2
    assert any(a.action_id == "btn_pause_trading" for a in trade_push.actions)
    assert "friday://trading" in trade_push.deep_link

    # 2. Nexus Approval Push
    nexus_push = bridge.create_nexus_approval_push("wf_9921", "acme-corp.com")
    assert nexus_push.subsystem == "nexus"
    assert len(nexus_push.actions) == 2
    assert any(a.action_id == "btn_approve" for a in nexus_push.actions)
    assert any(a.action_id == "btn_reject" for a in nexus_push.actions)
    assert "acme-corp.com" in nexus_push.title


# =========================================================================
# 3. Conversational Voice Interface & Repair Tests
# =========================================================================

def test_conversational_voice_repair_and_emotion(multimodal_setup):
    """Verify multi-tier repair, interruption handling, and stress tone adaptation."""
    mobile, bridge, voice, vision = multimodal_setup

    # 1. Low confidence (< 0.70) triggers REPEAT
    turn_low = voice.process_voice_turn("muffled phrase", confidence=0.55)
    assert turn_low.repair_decision == "REPEAT"
    assert "didn't catch that" in turn_low.response_text

    # 2. Medium confidence (0.70 - 0.85) triggers CONFIRM
    turn_med = voice.process_voice_turn("show positions", confidence=0.78)
    assert turn_med.repair_decision == "CONFIRM"
    assert "Did you mean" in turn_med.response_text

    # 3. High confidence (>= 0.85) triggers EXECUTE
    turn_high = voice.process_voice_turn("what about yesterday?", confidence=0.95)
    assert turn_high.repair_decision == "EXECUTE"

    # 4. Stress Tone Adaptation (> 0.70) triggers CONCISE_BULLETS
    turn_stress = voice.process_voice_turn("status now", confidence=0.92, detected_stress_level=0.85)
    assert turn_stress.detected_emotion == "STRESSED"
    assert turn_stress.response_style == "CONCISE_BULLETS"
    assert "•" in turn_stress.response_text

    # 5. Interruption Handling
    voice.set_speaking_state(True)
    voice.interrupt_speech()
    assert voice._is_speaking is False


# =========================================================================
# 4. Screen Sharing Vision Diagnostic Tests
# =========================================================================

def test_screen_sharing_vision_and_auto_timeout(multimodal_setup):
    """Verify chart/error vision diagnostics and 5-minute idle auto-termination."""
    mobile, bridge, voice, vision = multimodal_setup

    # 1. Chart Vision Analysis
    diag_chart = vision.analyze_screen("Bitcoin 1-hour candle chart with RSI", "What's wrong with this chart?")
    assert diag_chart is not None
    assert "RSI divergence" in diag_chart.diagnosis
    assert vision.is_active is True

    # 2. Error Vision Analysis
    diag_err = vision.analyze_screen("Python stacktrace traceback", "What is this error?")
    assert diag_err is not None
    assert "ConnectionResetError" in diag_err.diagnosis

    # 3. 5-Minute Idle Auto-Termination
    now = datetime.now(timezone.utc)
    future_6m = now + timedelta(minutes=6)
    is_timed_out = vision.check_idle_timeout(current_time=future_6m)
    assert is_timed_out is True
    assert vision.is_active is False
