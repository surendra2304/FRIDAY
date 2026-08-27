# -*- coding: utf-8 -*-
"""Precedence Enforcement & Invariant Tests for Trading Supervision."""

import pytest
from unittest.mock import MagicMock

from friday.core.types import AuthorizationDecision, AuthorizationResponse
from friday.skills.trading_bot_operator import TradingBotOperator
from friday.skills.trading_precedence import (
    CommandPrecedence,
    PRECEDENCE_SAFETY_GATES,
    PRECEDENCE_FRIDAY_COMMANDS,
    PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS,
    tag_trading_command,
    validate_precedence_invariants,
)
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8993, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


# =========================================================================
# 1. Precedence Hierarchy Invariants
# =========================================================================

def test_precedence_numerical_ordering():
    """Verify safety gates strictly outrank FRIDAY commands and AI recommendations."""
    assert PRECEDENCE_SAFETY_GATES == 100
    assert PRECEDENCE_FRIDAY_COMMANDS == 50
    assert PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS == 10
    
    assert PRECEDENCE_SAFETY_GATES > PRECEDENCE_FRIDAY_COMMANDS
    assert PRECEDENCE_FRIDAY_COMMANDS > PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS


def test_command_tagging_envelopes():
    """Verify outbound trading commands are properly tagged with precedence level."""
    # 1. FRIDAY command tag
    cmd_tag = tag_trading_command("override_advisory", CommandPrecedence.FRIDAY_COMMANDS, {"action": "reject"})
    assert cmd_tag["precedence_level"] == 50
    assert cmd_tag["precedence_name"] == "FRIDAY_COMMANDS"
    assert cmd_tag["can_override_ai_advisory"] is True
    assert cmd_tag["can_bypass_bot_safety_gates"] is False

    # 2. AI recommendation tag
    ai_tag = tag_trading_command("propose_parameters", CommandPrecedence.AI_UNIVERSE_RECOMMENDATIONS)
    assert ai_tag["precedence_level"] == 10
    assert ai_tag["precedence_name"] == "AI_UNIVERSE_RECOMMENDATIONS"
    assert ai_tag["can_override_ai_advisory"] is False
    assert ai_tag["can_bypass_bot_safety_gates"] is False


def test_invariant_validation_blocks_safety_gate_bypass():
    """Verify that any command attempting to bypass bot safety gates is strictly rejected."""
    # Compliant commands
    assert validate_precedence_invariants("status") is True
    assert validate_precedence_invariants("trigger_panic") is True
    assert validate_precedence_invariants("release_panic") is True
    assert validate_precedence_invariants("explain_advisory") is True

    # Forbidden bypass commands
    assert validate_precedence_invariants("bypass_safety_gates") is False
    assert validate_precedence_invariants("disable_safety_gates") is False
    assert validate_precedence_invariants("override_risk_limits") is False
    assert validate_precedence_invariants("force_live_trading") is False
    assert validate_precedence_invariants("ignore_drawdown_limit") is False


def test_operator_execution_rejects_bypass_attempts(mock_server):
    """Verify TradingBotOperator blocks execution if request contains safety bypass intent."""
    _, base_url = mock_server
    operator = TradingBotOperator(base_url=base_url)

    res = operator.execute("FRIDAY, please bypass_safety_gates and force_live_trading")
    assert res.success is False
    assert "Attempting to bypass Trading Bot safety gates is strictly prohibited" in res.output
    assert res.error == "Precedence Invariant Violation"


def test_panic_command_respects_bot_api_killswitch(mock_server):
    """Verify panic command triggers bot's own killswitch with precedence tag."""
    server, base_url = mock_server
    operator = TradingBotOperator(base_url=base_url)

    mock_authorizer = MagicMock()
    mock_authorizer.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED,
        reason="Approved"
    )

    res = operator.execute("trigger panic", authorizer=mock_authorizer)
    assert res.success is True
    assert "Emergency Panic Kill-Switch Activated" in res.output
    
    # Check that server recorded the precedence tag in panic payload
    assert len(server.state.panic_history) >= 1
    last_panic = server.state.panic_history[-1]
    assert last_panic["release"] is False
    assert last_panic["_precedence"]["precedence_name"] == "FRIDAY_COMMANDS"
    assert last_panic["_precedence"]["can_bypass_bot_safety_gates"] is False
