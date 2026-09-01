"""Unit tests for Trading Supervision & AI-Universe Advisory Architecture."""

from unittest import mock

import pytest

from friday.core.types import TrustLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.advisory_watchdog import AdvisoryWatchdogOperator
from friday.skills.advisory_supervisor import AdvisorySupervisorSkill
from friday.skills.registry import SkillRegistry
from friday.skills.trading_bot_operator import BotStatus, TradingBotOperator
from friday.skills.trading_precedence import (
    PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS,
    PRECEDENCE_FRIDAY_COMMANDS,
    PRECEDENCE_SAFETY_GATES,
    CommandPrecedence,
    tag_trading_command,
    validate_precedence_invariants,
)


@pytest.fixture
def mock_bot_status_data():
    return {
        "status": "ACTIVE",
        "trading_mode": "TESTNET",
        "equity": 10540.25,
        "cash": 8200.00,
        "unrealized_pnl": 140.25,
        "realized_pnl": 400.00,
        "today_pnl": 540.25,
        "profit_factor": 1.85,
        "win_rate_pct": 68.5,
        "positions": [
            {"symbol": "BTCUSDT", "side": "LONG", "size": 0.05, "unrealized_pnl": 95.50},
            {"symbol": "ETHUSDT", "side": "SHORT", "size": 0.50, "unrealized_pnl": 44.75},
        ]
    }


@pytest.fixture
def mock_advisory_recent_data():
    return {
        "advisories": [
            {
                "decision_id": "adv_001",
                "timestamp": "2026-08-27T10:00:00Z",
                "verdict": "APPLY",
                "confidence": 0.85,
                "recommendation": "Tighten BTC scalper stop-loss to 0.4%",
                "parameter_adjustments": {"btc_sl_pct": 0.4},
                "key_evidence": ["High ATR spike detected"],
            },
            {
                "decision_id": "adv_002",
                "timestamp": "2026-08-27T10:15:00Z",
                "verdict": "REJECT",
                "confidence": 0.90,
                "recommendation": "Increase ETH max position size to 2.5x",
                "rejection_reason": "Exceeds max account risk limit of 1.0x per asset",
                "parameter_adjustments": {"eth_max_size": 2.5},
                "key_evidence": ["Bullish momentum breakout"],
            },
            {
                "decision_id": "adv_003",
                "timestamp": "2026-08-27T10:30:00Z",
                "verdict": "HOLD",
                "confidence": 0.50,
                "recommendation": "Maintain current parameters",
                "key_evidence": ["Neutral market regime"],
            },
        ]
    }


@pytest.fixture
def mock_advisory_state_data():
    return {
        "ai_universe_enabled": True,
        "ai_universe_health": "HEALTHY",
        "active_overlay": {
            "btc_sl_pct": 0.4
        },
        "last_consult_time": "2026-08-27T10:30:00Z",
    }


# =========================================================================
# 1. Trading Command Precedence Tests
# =========================================================================

def test_command_precedence_hierarchy():
    """Verify that command precedence values maintain the immutable hierarchy."""
    assert PRECEDENCE_SAFETY_GATES > PRECEDENCE_FRIDAY_COMMANDS
    assert PRECEDENCE_FRIDAY_COMMANDS > PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS
    assert PRECEDENCE_SAFETY_GATES == 100
    assert PRECEDENCE_FRIDAY_COMMANDS == 50
    assert PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS == 10


def test_tag_trading_command():
    """Verify command tagging produces correct metadata and can_bypass flags."""
    tag = tag_trading_command("trigger_panic", CommandPrecedence.FRIDAY_COMMANDS, {"asset": "BTC"})
    assert tag["command"] == "trigger_panic"
    assert tag["precedence_level"] == 50
    assert tag["precedence_name"] == "FRIDAY_COMMANDS"
    assert tag["can_override_ai_advisory"] is True
    assert tag["can_bypass_bot_safety_gates"] is False
    assert tag["metadata"]["asset"] == "BTC"


def test_validate_precedence_invariants():
    """Verify that forbidden bypass actions are detected and blocked."""
    assert validate_precedence_invariants("trigger_panic") is True
    assert validate_precedence_invariants("query_status") is True
    assert validate_precedence_invariants("bypass_safety_gates") is False
    assert validate_precedence_invariants("disable_safety_gates") is False
    assert validate_precedence_invariants("override_risk_limits") is False


# =========================================================================
# 2. TradingBotOperator Advisory Methods Tests
# =========================================================================

def test_trading_bot_operator_advisory_methods(mock_bot_status_data, mock_advisory_recent_data, mock_advisory_state_data):
    """Test get_advisory_recent, get_advisory_state, and get_advisory_summary on TradingBotOperator."""
    op = TradingBotOperator()

    with mock.patch.object(op, "_http_get") as mock_get:
        def side_effect(endpoint):
            if "/api/status" in endpoint:
                return mock_bot_status_data
            if "/api/advisory/recent" in endpoint:
                return mock_advisory_recent_data
            if "/api/advisory/state" in endpoint:
                return mock_advisory_state_data
            return {}

        mock_get.side_effect = side_effect

        # 1. get_advisory_recent
        recent = op.get_advisory_recent(limit=5)
        assert len(recent["advisories"]) == 3
        assert recent["advisories"][0]["verdict"] == "APPLY"

        # 2. get_advisory_state
        state = op.get_advisory_state()
        assert state["ai_universe_health"] == "HEALTHY"
        assert state["active_overlay"]["btc_sl_pct"] == 0.4

        # 3. get_advisory_summary
        summary = op.get_advisory_summary()
        assert "AI-Universe Advisory is HEALTHY" in summary
        assert "3 recommendations evaluated" in summary
        assert "1 applied, 1 rejected" in summary
        assert "btc_sl_pct=0.4" in summary
        assert "Exceeds max account risk limit" in summary


def test_trading_bot_operator_panic_routes_to_bot_api():
    """Verify panic() calls POST /api/panic with precedence metadata."""
    op = TradingBotOperator()

    with mock.patch.object(op, "_http_post") as mock_post:
        mock_post.return_value = {"status": "PANIC_ACTIVATED", "release": False}
        res = op.trigger_panic()
        assert res["status"] == "PANIC_ACTIVATED"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "/api/panic"
        payload = args[1]
        assert payload["release"] is False
        assert payload["_precedence"]["command"] == "trigger_panic"
        assert payload["_precedence"]["can_bypass_bot_safety_gates"] is False


# =========================================================================
# 3. AdvisorySupervisorSkill Tests
# =========================================================================

def test_advisory_supervisor_skill_contested_detection(mock_advisory_recent_data):
    """Test contested advisory detection (REJECT with confidence > 0.70)."""
    op = TradingBotOperator()
    with mock.patch.object(op, "get_advisory_recent", return_value=mock_advisory_recent_data):
        skill = AdvisorySupervisorSkill(bot_operator=op)
        res = skill.monitor_advisories()

        assert res["has_contested"] is True
        assert res["contested_count"] == 1
        contested = res["contested_advisories"][0]
        assert contested["decision_id"] == "adv_002"
        assert contested["confidence"] == 0.90
        assert "Exceeds max account risk limit" in contested["rejection_reason"]


def test_advisory_supervisor_morning_briefing(mock_bot_status_data, mock_advisory_recent_data, mock_advisory_state_data):
    """Test morning trading briefing synthesis."""
    op = TradingBotOperator()
    with mock.patch.object(op, "get_bot_status") as mock_status, \
         mock.patch.object(op, "get_advisory_recent", return_value=mock_advisory_recent_data), \
         mock.patch.object(op, "get_advisory_state", return_value=mock_advisory_state_data):
        
        mock_status.return_value = BotStatus(
            status="ACTIVE",
            mode="TESTNET",
            equity=10540.25,
            cash=8200.0,
            unrealized_pnl=140.25,
            realized_pnl=400.0,
            today_pnl=540.25,
            profit_factor=1.85,
            win_rate_pct=68.5,
            open_positions=mock_bot_status_data["positions"],
        )

        skill = AdvisorySupervisorSkill(bot_operator=op)
        briefing = skill.morning_trading_briefing()

        assert "Trading Bot Morning Briefing" in briefing["spoken_text"]
        assert "$10,540.25 USDT" in briefing["spoken_text"]
        assert "+$540.25 USDT" in briefing["spoken_text"]
        assert "BTCUSDT LONG" in briefing["spoken_text"]
        assert "ETHUSDT SHORT" in briefing["spoken_text"]
        assert "AI-Universe Advisory is HEALTHY" in briefing["spoken_text"]


def test_advisory_supervisor_explain_advisory(mock_advisory_recent_data):
    """Test explain_advisory plain language rationale output."""
    op = TradingBotOperator()
    with mock.patch.object(op, "get_advisory_recent", return_value=mock_advisory_recent_data):
        skill = AdvisorySupervisorSkill(bot_operator=op)
        
        # Test explaining rejected advisory
        res_rej = skill.explain_advisory("adv_002")
        assert res_rej["found"] is True
        assert res_rej["verdict"] == "REJECT"
        assert "REJECTED by Safety Gates" in res_rej["explanation"]
        assert "Exceeds max account risk limit" in res_rej["explanation"]

        # Test explaining applied advisory
        res_app = skill.explain_advisory("adv_001")
        assert res_app["found"] is True
        assert res_app["verdict"] == "APPLY"
        assert "APPLIED" in res_app["explanation"]


def test_advisory_supervisor_execute_commands(mock_bot_status_data, mock_advisory_recent_data, mock_advisory_state_data):
    """Test skill execute() natural language commands."""
    op = TradingBotOperator()
    with mock.patch.object(op, "get_bot_status") as mock_status, \
         mock.patch.object(op, "get_advisory_recent", return_value=mock_advisory_recent_data), \
         mock.patch.object(op, "get_advisory_state", return_value=mock_advisory_state_data):
        
        mock_status.return_value = BotStatus(
            status="ACTIVE",
            mode="TESTNET",
            equity=10540.25,
            cash=8200.0,
            unrealized_pnl=140.25,
            realized_pnl=400.0,
            today_pnl=540.25,
            profit_factor=1.85,
            win_rate_pct=68.5,
            open_positions=[],
        )
        skill = AdvisorySupervisorSkill(bot_operator=op)

        # 1. "what did ai-universe recommend"
        exec1 = skill.execute("What did AI-Universe recommend?")
        assert exec1.success is True
        assert "Recent AI-Universe Advisory Decisions" in exec1.output

        # 2. "show me rejected advisories"
        exec2 = skill.execute("Show me rejected advisories")
        assert exec2.success is True
        assert "Rejected AI-Universe Advisories" in exec2.output
        assert "adv_002" in str(exec2.metadata)

        # 3. "what parameters has the ai changed"
        exec3 = skill.execute("What parameters has the AI changed?")
        assert exec3.success is True
        assert "Active AI-Universe Parameter Overlay" in exec3.output

        # 4. "trading morning briefing"
        exec4 = skill.execute("Trading morning briefing")
        assert exec4.success is True
        assert "Trading Bot Morning Briefing" in exec4.output


# =========================================================================
# 4. AdvisoryWatchdogOperator Alerting & Memory Tagging Tests
# =========================================================================

def test_advisory_watchdog_operator_contested_alert(mock_bot_status_data, mock_advisory_recent_data, mock_advisory_state_data):
    """Test that AdvisoryWatchdogOperator detects contested advisories and tags memory with UNTRUSTED_EXTERNAL."""
    memory = InMemoryConversationMemory()
    mock_notif_mgr = mock.MagicMock()
    op = TradingBotOperator()

    with mock.patch.object(op, "get_bot_status") as mock_status, \
         mock.patch.object(op, "get_advisory_recent", return_value=mock_advisory_recent_data), \
         mock.patch.object(op, "get_advisory_state", return_value=mock_advisory_state_data):
        
        mock_status.return_value = BotStatus(
            status="ACTIVE",
            mode="TESTNET",
            equity=10540.25,
            cash=8200.0,
            unrealized_pnl=140.25,
            realized_pnl=400.0,
            today_pnl=540.25,
            profit_factor=1.85,
            win_rate_pct=68.5,
            open_positions=[],
        )

        watchdog = AdvisoryWatchdogOperator(
            bot_operator=op,
            poll_interval=60.0,
            memory=memory,
            notification_manager=mock_notif_mgr,
        )

        state = watchdog.check_state()
        assert state["status"] == "ALERT"
        assert state["alert_count"] == 1
        alert = state["alerts"][0]
        assert alert["alert_type"] == "CONTESTED_ADVISORY"
        assert alert["decision_id"] == "adv_002"

        # Check NotificationManager post
        mock_notif_mgr.post_notification.assert_called_once()
        n_args, n_kwargs = mock_notif_mgr.post_notification.call_args
        assert "Trading Watchdog Alert" in n_kwargs["message"]
        assert n_kwargs["category"] == "trading_supervision"

        # Check Memory Logging with TrustLevel.UNTRUSTED_EXTERNAL
        messages = memory.get_messages()
        assert len(messages) == 1
        assert messages[0].trust_level == TrustLevel.UNTRUSTED_EXTERNAL
        assert "TRADING_SUPERVISOR_ALERT" in messages[0].content


def test_advisory_watchdog_operator_ai_universe_down(mock_bot_status_data):
    """Test alert when AI-Universe health is DOWN."""
    memory = InMemoryConversationMemory()
    op = TradingBotOperator()

    down_state = {
        "ai_universe_enabled": True,
        "ai_universe_health": "DOWN",
    }

    with mock.patch.object(op, "get_bot_status") as mock_status, \
         mock.patch.object(op, "get_advisory_recent", return_value={"advisories": []}), \
         mock.patch.object(op, "get_advisory_state", return_value=down_state):
        
        mock_status.return_value = BotStatus(
            status="ACTIVE", mode="TESTNET", equity=10000.0, cash=10000.0,
            unrealized_pnl=0.0, realized_pnl=0.0, today_pnl=0.0,
            profit_factor=0.0, win_rate_pct=0.0, open_positions=[]
        )

        watchdog = AdvisoryWatchdogOperator(bot_operator=op, memory=memory)
        state = watchdog.check_state()
        assert state["status"] == "ALERT"
        assert any(a["alert_type"] == "AI_UNIVERSE_DOWN" for a in state["alerts"])


def test_advisory_watchdog_operator_bot_unreachable():
    """Test alert when Trading Bot is unreachable."""
    memory = InMemoryConversationMemory()
    op = TradingBotOperator()

    with mock.patch.object(op, "get_bot_status", side_effect=RuntimeError("Connection refused")):
        watchdog = AdvisoryWatchdogOperator(bot_operator=op, memory=memory)
        state = watchdog.check_state()
        assert state["status"] == "UNREACHABLE"
        assert len(state["alerts"]) == 1
        assert state["alerts"][0]["alert_type"] == "BOT_UNREACHABLE"


# =========================================================================
# 5. Skill Registry Integration & Capability Gating
# =========================================================================

def test_skill_registry_loads_advisory_supervisor():
    """Verify AdvisorySupervisorSkill is loaded by default in SkillRegistry."""
    registry = SkillRegistry()
    registry.load_builtins()

    skill = registry.get("advisory_supervisor")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
    assert "trading_bot_control" in skill.required_capabilities
