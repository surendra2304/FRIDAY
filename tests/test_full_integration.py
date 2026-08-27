# -*- coding: utf-8 -*-
"""Full End-to-End Integration Tests for FRIDAY Trading Supervision."""

import pytest
from unittest.mock import MagicMock

from friday.agent.agent import FridayAgent
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.types import Message, Role, TrustLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.skills.advisory_supervisor import AdvisorySupervisorSkill
from friday.skills.registry import SkillRegistry
from friday.skills.trading_bot_operator import TradingBotOperator
from tests.mock_trading_bot import MockTradingBotServer


@pytest.fixture(scope="module")
def mock_server():
    server = MockTradingBotServer(port=8994, scenario="mixed")
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.fixture
def integrated_agent(mock_server):
    server, base_url = mock_server
    server.set_scenario("mixed")

    memory = InMemoryConversationMemory()
    settings = Settings(
        env="testing",
        llm_provider="mock",
        llm_model="mock-gpt",
        llm_api_key="TEST_KEY",
    )

    # Initialize operator and supervisor connected to mock server
    operator = TradingBotOperator(base_url=base_url)
    supervisor = AdvisorySupervisorSkill(bot_operator=operator)

    # Register in custom registry
    registry = SkillRegistry()
    registry.register(operator)
    registry.register(supervisor)

    agent = FridayAgent(
        memory=memory,
        settings=settings,
        skill_registry=registry,
        authorizer=DefaultSecureAuthorizer(),
    )
    return agent, supervisor, operator, memory, server


# =========================================================================
# 1. End-to-End Cognitive & Supervisory Interaction
# =========================================================================

def test_full_integration_what_did_ai_universe_recommend(integrated_agent):
    """End-to-end: User asks 'What did AI-Universe recommend?' -> Agent routes to AdvisorySupervisorSkill."""
    agent, supervisor, operator, memory, server = integrated_agent
    server.set_scenario("mixed")

    response = agent.process_message("What did AI-Universe recommend?")

    assert response.is_done is True
    assert "Recent AI-Universe Advisory Decisions" in response.content
    assert "[APPLY - 85% Conf]" in response.content
    assert "Tighten BTC scalper stop-loss to 0.4%" in response.content
    assert "[REJECT - 91% Conf]" in response.content
    assert "Increase ETH max position size to 2.5x" in response.content

    # Verify conversation memory messages
    history = memory.get_messages()
    assert len(history) >= 2
    user_msg = history[-2]
    asst_msg = history[-1]
    assert user_msg.role == Role.USER
    assert asst_msg.role == Role.ASSISTANT
    assert "Recent AI-Universe Advisory Decisions" in asst_msg.content


def test_full_integration_trading_morning_briefing(integrated_agent):
    """End-to-end: User asks 'Trading morning briefing' -> Agent returns spoken briefing."""
    agent, supervisor, operator, memory, server = integrated_agent
    server.set_scenario("mixed")

    response = agent.process_message("Trading morning briefing")

    assert response.is_done is True
    assert "Trading Bot Morning Briefing" in response.content
    assert "$10,540.25 USDT" in response.content
    assert "BTCUSDT LONG" in response.content
    assert "AI-Universe Advisory is HEALTHY" in response.content


def test_full_integration_explain_advisory_decision(integrated_agent):
    """End-to-end: User asks 'explain advisory adv_mix_02' -> Agent details safety gate rejection."""
    agent, supervisor, operator, memory, server = integrated_agent
    server.set_scenario("mixed")

    response = agent.process_message("explain advisory adv_mix_02")

    assert response.is_done is True
    assert "REJECTED by Safety Gates" in response.content
    assert "Exceeds max account risk limit of 1.0x per asset" in response.content
    assert "AI-Universe Proposal" in response.content
    assert "91%" in response.content


def test_full_integration_untrusted_external_tagging_in_watchdog_memory(integrated_agent):
    """End-to-end: AdvisoryWatchdogOperator processes contested advisory and records untrusted memory."""
    agent, supervisor, operator, memory, server = integrated_agent
    server.set_scenario("mixed")

    from friday.operators.advisory_watchdog import AdvisoryWatchdogOperator
    watchdog = AdvisoryWatchdogOperator(bot_operator=operator, memory=memory)

    state = watchdog.check_state()
    assert state["status"] == "ALERT"
    assert state["alert_count"] == 1

    # Verify memory message was tagged TrustLevel.UNTRUSTED_EXTERNAL
    untrusted_msgs = [m for m in memory.get_messages() if m.trust_level == TrustLevel.UNTRUSTED_EXTERNAL]
    assert len(untrusted_msgs) >= 1
    assert "TRADING_SUPERVISOR_ALERT" in untrusted_msgs[0].content
    assert "adv_mix_02" in untrusted_msgs[0].content
