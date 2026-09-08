"""Tests for the FRIDAY-style communications persona layer.

The persona layer is strictly additive: it must not remove or weaken any of
the existing identity, safety, or provider-agnostic rules that the main suite
guarantees. These tests verify both that the persona is applied when
settings.persona == 'friday' and that the classic persona still yields the
original behaviour.
"""

from unittest import mock

from friday.agent.prompts import get_default_system_prompt
from friday.core.config import Settings
from friday.persona.friday import (
    CLASSIC_GREETING_RESPONSES,
    FRIDAY_GREETING_RESPONSES,
    FRIDAY_TEXT_BLOCK,
    FRIDAY_VOICE_BLOCK,
    greeting_responses_for,
    proactive_style,
)


# ---------------------------------------------------------------------------
# Persona block selection
# ---------------------------------------------------------------------------


def test_friday_greeting_pool_selected():
    assert greeting_responses_for("friday") == FRIDAY_GREETING_RESPONSES
    assert greeting_responses_for("classic") == CLASSIC_GREETING_RESPONSES


def test_friday_greetings_are_styled():
    for line in FRIDAY_GREETING_RESPONSES:
        assert "{user_name}" in line
    assert FRIDAY_GREETING_RESPONSES != CLASSIC_GREETING_RESPONSES


# ---------------------------------------------------------------------------
# System prompt carries the persona (and keeps all existing guarantees)
# ---------------------------------------------------------------------------


def test_friday_text_persona_appended_to_system_prompt():
    prompt = get_default_system_prompt(Settings(env="testing", persona="friday", user_name="Surendra"))
    assert "FRIDAY SIGNATURE COMMUNICATIONS PERSONA" in prompt
    assert "dry" in prompt.lower()
    # Existing guarantees must remain untouched.
    assert "Fully Responsive Intelligent Digital Assistant" in prompt
    assert "multi-provider architecture" in prompt
    assert "Do not treat greetings as commands or tool targets" in prompt


def test_classic_persona_keeps_original_prompt():
    prompt = get_default_system_prompt(Settings(env="testing", persona="classic", user_name="Surendra"))
    assert "FRIDAY SIGNATURE COMMUNICATIONS PERSONA" not in prompt
    assert "You are FRIDAY" in prompt


def test_voice_persona_block_present():
    assert "FRIDAY SIGNATURE" in FRIDAY_VOICE_BLOCK
    assert "calm, measured confidence" in FRIDAY_VOICE_BLOCK.lower()


def test_text_block_contains_user_placeholder():
    assert "{user_name}" in FRIDAY_TEXT_BLOCK


# ---------------------------------------------------------------------------
# Proactive style
# ---------------------------------------------------------------------------


def test_proactive_style_wraps_friday_summary():
    styled = proactive_style("friday", "Your 3 PM meeting is in 10 minutes.", "Surendra")
    assert styled != "Your 3 PM meeting is in 10 minutes."
    assert "Your 3 PM meeting is in 10 minutes." in styled


def test_proactive_style_passthrough_for_other_personas():
    summary = "A reminder is pending."
    assert proactive_style("classic", summary, "Surendra") == summary
    assert proactive_style("friday", "", "Surendra") == ""


# ---------------------------------------------------------------------------
# Greeting fast-path uses persona-aware responses
# ---------------------------------------------------------------------------


def test_greeting_fast_path_uses_friday_pool():
    """The greeting fast-path should return a FRIDAY-styled greeting by default."""
    from friday.agent.agent import FridayAgent
    from friday.agent.mixins.fast_paths import FastPathMixin
    from friday.memory.in_memory import InMemoryConversationMemory

    settings = Settings(env="testing", llm_provider="mock", ui_automation_enabled=False, persona="friday")
    agent = FridayAgent.__new__(FridayAgent)
    agent.settings = settings
    agent.memory = InMemoryConversationMemory()
    agent.state_machine = mock.MagicMock()

    response = FastPathMixin._greeting_fast_path(agent, "hello")
    assert response is not None
    assert response.metadata.get("greeting_fast_path") is True
    # FRIDAY pools never contain the classic lines
    assert "how can I help you today" not in response.content.lower()
    assert "Surendra" in response.content


def test_agent_greeting_falls_back_to_classic_for_other_personas():
    """Non-FRIDAY personas should keep the original greeting pool."""
    from friday.agent.agent import FridayAgent
    from friday.agent.mixins.fast_paths import FastPathMixin
    from friday.memory.in_memory import InMemoryConversationMemory

    settings = Settings(env="testing", llm_provider="mock", ui_automation_enabled=False, persona="classic")
    agent = FridayAgent.__new__(FridayAgent)
    agent.settings = settings
    agent.memory = InMemoryConversationMemory()
    agent.state_machine = mock.Mock()

    response = FastPathMixin._greeting_fast_path(agent, "hey there")
    assert response is not None
    assert response.metadata.get("greeting_fast_path") is True
    # Response must come from the classic (non-FRIDAY) greeting pool
    assert response.content in [g.format(user_name="Surendra") for g in CLASSIC_GREETING_RESPONSES]