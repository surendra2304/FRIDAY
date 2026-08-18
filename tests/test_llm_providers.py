"""Tests for LLM provider abstractions."""

import pytest
from friday.core.config import Settings
from friday.core.exceptions import ConfigError, LLMProviderError
from friday.core.types import Message, Role
from friday.llm.factory import create_llm_provider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider


def test_mock_provider_generation():
    provider = MockLLMProvider(model="test-mock")
    messages = [Message(role=Role.USER, content="Hello FRIDAY")]
    response = provider.generate(messages)

    assert response.role == Role.ASSISTANT
    assert "Hello FRIDAY" in response.content
    assert provider.provider_name == "mock"


def test_mock_provider_tool_trigger():
    provider = MockLLMProvider()
    messages = [Message(role=Role.USER, content="Please check system info")]
    tools = [
        {
            "type": "function",
            "function": {"name": "get_system_info", "description": "Get system info", "parameters": {}},
        }
    ]
    response = provider.generate(messages, tools=tools)
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_system_info"


def test_factory_creation():
    mock_settings = Settings(llm_provider="mock")
    provider = create_llm_provider(mock_settings)
    assert isinstance(provider, MockLLMProvider)

    openai_settings = Settings(llm_provider="openai", llm_api_key="sk-test")
    openai_provider = create_llm_provider(openai_settings)
    assert isinstance(openai_provider, OpenAILLMProvider)


def test_factory_invalid_provider():
    bad_settings = Settings(llm_provider="unsupported_ai")
    with pytest.raises(ConfigError):
        create_llm_provider(bad_settings)
