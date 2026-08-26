# -*- coding: utf-8 -*-
"""Unit tests for FRIDAY TradingBotOperator Skill and AI Universe Integration."""

import json
from unittest.mock import MagicMock, patch
import pytest

from friday.core.types import AuthorizationDecision, AuthorizationResponse, SafetyLevel
from friday.skills.trading_bot_operator import BotStatus, TradingBotOperator
from friday.skills.registry import SkillRegistry
from friday.integrations.ai_universe_provider import AIUniverseTradingConsultant, TradingConsultationResult
from friday.tools.ai_universe_client import AIUniverseResponse


MOCK_STATUS_PAYLOAD = {
    "status": "ACTIVE",
    "trading_mode": "TESTNET",
    "equity": 5035.98,
    "cash": 4387.57,
    "unrealized_pnl": 168.64,
    "realized_pnl": 479.77,
    "today_pnl": 648.41,
    "profit_factor": 1.72,
    "win_rate": 68.5,
    "positions": [
        {"symbol": "DOGEUSDT", "action": "SELL", "size": 1000, "entry": 0.12, "pnl": 50.0},
        {"symbol": "SOLUSDT", "action": "SELL", "size": 10, "entry": 140.0, "pnl": 80.0},
        {"symbol": "DOTUSDT", "action": "SELL", "size": 50, "entry": 4.5, "pnl": 38.64},
    ]
}

MOCK_RECENT_ACTIONS_PAYLOAD = {
    "status": "OK",
    "count": 3,
    "actions": [
        "16:20 UTC | DOGEUSDT | Scalper Gate | PASSED",
        "16:15 UTC | BTCUSDT | Profitability Gate | FAILED/BLOCKED (EV < 5bps)",
        "16:10 UTC | SOLUSDT | Scalper Gate | PASSED"
    ]
}


def test_trading_bot_operator_get_status_parsing():
    """Verify FRIDAY TradingBotOperator parses status and PnL fields accurately."""
    operator = TradingBotOperator()
    
    with patch.object(operator, "_http_get", return_value=MOCK_STATUS_PAYLOAD):
        status = operator.get_bot_status()
        assert isinstance(status, BotStatus)
        assert status.status == "ACTIVE"
        assert status.mode == "TESTNET"
        assert status.equity == 5035.98
        assert status.cash == 4387.57
        assert status.unrealized_pnl == 168.64
        assert status.today_pnl == 648.41
        assert status.profit_factor == 1.72
        assert status.win_rate_pct == 68.5
        assert len(status.open_positions) == 3


def test_trading_bot_operator_sends_api_key_header():
    """Verify X-BOT-API-KEY header is sent when api_key is configured."""
    operator = TradingBotOperator(api_key="secret_test_key_999")
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "PANIC_ACTIVATED"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        
        operator.trigger_panic()
        
        # Verify request had X-BOT-API-KEY header
        assert mock_urlopen.called
        req_sent = mock_urlopen.call_args[0][0]
        assert req_sent.get_header("X-bot-api-key") == "secret_test_key_999"


def test_trading_bot_operator_execute_spoken_status():
    """Verify FRIDAY spoken summary when user asks 'Friday, how is the trading bot doing?'"""
    operator = TradingBotOperator()
    
    with patch.object(operator, "_http_get", return_value=MOCK_STATUS_PAYLOAD):
        res = operator.execute("Friday, how is the trading bot doing?")
        assert res.success is True
        assert "Binance Futures TESTNET" in res.output
        assert "$5,035.98" in res.output
        assert "+$168.64" in res.output
        assert "3 active positions" in res.output
        assert "$648.41" in res.output


def test_trading_bot_operator_panic_authorization_denied():
    """Verify emergency panic kill-switch is blocked if authorization is denied."""
    operator = TradingBotOperator()
    
    mock_authorizer = MagicMock()
    mock_authorizer.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.DENIED,
        reason="Manual user confirmation required for dangerous operations"
    )
    
    res = operator.execute("trigger panic on trading bot", authorizer=mock_authorizer)
    assert res.success is False
    assert "Authorization Denied" in res.error
    assert "blocked" in res.output.lower()


def test_trading_bot_operator_panic_authorized():
    """Verify emergency panic kill-switch calls POST /api/panic when authorized."""
    operator = TradingBotOperator()
    
    mock_authorizer = MagicMock()
    mock_authorizer.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED,
        reason="Authorized by test operator"
    )
    
    with patch.object(operator, "_http_post", return_value={"status": "PANIC_ACTIVATED", "cancelled": 0}):
        res = operator.execute("trigger panic", authorizer=mock_authorizer)
        assert res.success is True
        assert "Emergency Panic Kill-Switch Activated" in res.output


def test_trading_bot_operator_release_panic():
    """Verify panic release calls POST /api/panic with release=True."""
    operator = TradingBotOperator()
    
    mock_authorizer = MagicMock()
    mock_authorizer.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED,
        reason="Authorized"
    )
    
    with patch.object(operator, "_http_post", return_value={"status": "PANIC_RELEASED"}):
        res = operator.execute("release panic", authorizer=mock_authorizer)
        assert res.success is True
        assert "released" in res.output.lower()


def test_skill_registry_includes_trading_bot_operator():
    """Verify SkillRegistry loads and matches TradingBotOperator."""
    registry = SkillRegistry()
    registry.load_builtins()
    
    skill = registry.get("trading_bot_operator")
    assert skill is not None
    assert skill.name == "trading_bot_operator"
    
    matched, score = registry.find_matching_skill("Friday, how is the trading bot doing?")
    assert matched.name == "trading_bot_operator"
    assert score >= 0.90


@pytest.mark.asyncio
async def test_ai_universe_trading_consultation_flow():
    """Verify FRIDAY gets status, delegates to AI Universe, and does NOT auto-apply advice."""
    mock_operator = MagicMock(spec=TradingBotOperator)
    mock_operator.get_bot_status.return_value = BotStatus(
        status="ACTIVE",
        mode="TESTNET",
        equity=5000.0,
        cash=4500.0,
        unrealized_pnl=-50.0,
        realized_pnl=100.0,
        today_pnl=50.0,
        profit_factor=1.05,
        win_rate_pct=42.0,
        open_positions=[]
    )
    
    from unittest.mock import AsyncMock
    mock_universe_client = MagicMock()
    mock_universe_client.ask = AsyncMock(return_value=AIUniverseResponse(
        answer="Tighten Stop Loss to 0.4% and expand Take Profit to 0.6%",
        confidence=0.88,
        key_evidence=["Profit Factor: 1.05", "Win Rate: 42.0%"],
        agents_used=["trading_analyst", "critic"],
        models_used=["deepseek-v4-flash"]
    ))
    
    consultant = AIUniverseTradingConsultant(
        bot_operator=mock_operator,
        universe_client=mock_universe_client
    )
    
    result = await consultant.consult_on_bot_performance(mode="ask")
    assert isinstance(result, TradingConsultationResult)
    assert "Tighten Stop Loss" in result.recommendation
    assert result.confidence == 0.88
    assert result.applied_to_bot is False  # Strict non-auto-execution safety invariant
    assert result.requires_user_authorization is True
    
    summary = result.format_summary()
    assert "AI Universe Strategy Consultation Summary" in summary
    assert "Tighten Stop Loss" in summary
    assert "NOT auto-applied" in summary
