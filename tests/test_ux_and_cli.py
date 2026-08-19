"""Tests for Persona, CLI, Error UX, and User Experience formatting."""

import pytest
from unittest import mock

from friday.agent.prompts import get_default_system_prompt
from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.cli.main import BANNER, print_status, print_history, print_conversations
from friday.core.types import Message, Role


@pytest.mark.unit
def test_banner_content():
    """Verify CLI banner clearly contains 'FRIDAY' and assistant title."""
    assert "FRIDAY" in BANNER
    assert "Fully Responsive Intelligent Digital Assistant for You" in BANNER


@pytest.mark.unit
def test_persona_prompt_guidelines(mock_settings):
    """Verify system prompt enforces calm, concise, non-robotic tone and bans filler phrases."""
    prompt = get_default_system_prompt(mock_settings)
    assert "Calm, confident, intelligent, concise, natural" in prompt
    assert "Certainly!" in prompt or "generic customer-service fillers" in prompt
    assert "Boss" in prompt  # Instructed to never use 'Boss'
    assert "markdown hash headers, tool call IDs" in prompt


@pytest.mark.integration
def test_error_ux_sanitization(mock_settings):
    """Verify internal LLM provider errors are translated into clean, user-friendly explanations."""
    agent = FridayAgent(settings=mock_settings)
    
    # Simulate a network/quota error during LLM generation
    with mock.patch.object(agent.llm, "generate", side_effect=Exception("HTTP 429 Resource Exhausted / Rate limit exceeded")):
        response = agent.process_message("Execute complex operation.")
        assert response.is_done is True
        assert "experiencing high demand" in response.content.lower() or "moment" in response.content.lower()
        # Internal raw trace must not be exposed in user content
        assert "Traceback" not in response.content


@pytest.mark.integration
def test_cli_status_and_history_formatting(mock_settings, capsys):
    """Verify CLI status and history printers produce clean, human-readable terminal output."""
    agent = FridayAgent(settings=mock_settings)
    agent.memory.add_message(Message(role=Role.USER, content="Hello FRIDAY"))
    agent.memory.add_message(Message(role=Role.ASSISTANT, content="Online and ready."))

    print_status(agent)
    captured = capsys.readouterr().out
    assert "Agent Status" in captured
    assert "FRIDAY-TEST" in captured

    print_history(agent)
    captured_hist = capsys.readouterr().out
    assert "Conversation History" in captured_hist
    assert "Online and ready." in captured_hist
