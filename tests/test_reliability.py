"""Unit and integration tests for FRIDAY agent reliability and observability."""

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import httpx
import pytest
from friday.agent.agent import FridayAgent
from friday.core.auth import AutoApproveAuthorizer
from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
    Role,
    Message,
    ToolCall,
)
from friday.llm.openai_provider import OpenAILLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class SlowSafeTool(BaseTool):
    name = "slow_tool"
    description = "A safe tool that sleeps to simulate execution delays"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"duration": {"type": "number"}}}

    def execute(self, duration: float = 1.0, **kwargs: Any) -> ToolResult:
        time.sleep(duration)
        return ToolResult(
            name=self.name,
            content="Slow tool finished.",
            is_error=False,
            safety_level=self.safety_level,
        )


@pytest.fixture
def slow_registry():
    reg = ToolRegistry()
    reg.register(SlowSafeTool())
    return reg


# --- 1. Test LLM retry on transient network errors ---
@patch("httpx.Client.post")
def test_retry_on_network_failure(mock_post):
    # Simulate: 2 failures (RequestError), followed by 1 successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Turn processed successfully after retries."
            }
        }]
    }

    mock_post.side_effect = [
        httpx.RequestError("Transient connect error A"),
        httpx.RequestError("Transient connect error B"),
        mock_response
    ]

    provider = OpenAILLMProvider(api_key="TEST_OPENAI_API_KEY", timeout=1.0)
    messages = [Message(role=Role.USER, content="Hello")]
    
    # We patch time.sleep inside generate to avoid sleeping during tests
    with patch("time.sleep") as mock_sleep:
        res = provider.generate(messages)
        assert res.content == "Turn processed successfully after retries."
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2


# --- 2. Test LLM retry on rate limits ---
@patch("httpx.Client.post")
def test_retry_on_rate_limit(mock_post):
    # Simulate: 1 rate limit (429) with Retry-After header, then success
    mock_rate_limit = MagicMock()
    mock_rate_limit.status_code = 429
    mock_rate_limit.headers = {"Retry-After": "0.1"}
    mock_rate_limit.json.return_value = {"error": {"message": "Rate limit exceeded"}}

    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Success after rate limit."}}]
    }

    mock_post.side_effect = [mock_rate_limit, mock_success]

    provider = OpenAILLMProvider(api_key="TEST_OPENAI_API_KEY", timeout=1.0)
    messages = [Message(role=Role.USER, content="Hello")]

    with patch("time.sleep") as mock_sleep:
        res = provider.generate(messages)
        assert res.content == "Success after rate limit."
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(0.1)


# --- 3. Test immediate failure (no retry) on auth errors ---
@patch("httpx.Client.post")
def test_no_retry_on_auth_error(mock_post):
    # Simulate: status code 401 (Unauthorized)
    mock_auth_error = MagicMock()
    mock_auth_error.status_code = 401
    mock_auth_error.json.return_value = {"error": {"message": "Invalid API Key"}}

    mock_post.return_value = mock_auth_error

    provider = OpenAILLMProvider(api_key="TEST_OPENAI_API_KEY", timeout=1.0)
    messages = [Message(role=Role.USER, content="Hello")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(messages)
    
    assert "status 401" in str(exc_info.value)
    # Authentication errors must not trigger retries
    assert mock_post.call_count == 1


# --- 4. Test tool timeout enforcement ---
def test_tool_timeout_enforcement(slow_registry):
    # Instantiate agent with 0.1s timeout limit
    agent = FridayAgent(
        settings=Settings(env="testing"),
        tool_registry=slow_registry,
        tool_timeout=0.1,
        authorizer=AutoApproveAuthorizer.create_for_testing()
    )

    tc = ToolCall(id="c1", name="slow_tool", arguments={"duration": 1.0})
    
    # Executing the slow tool with 0.1s limit should trigger a timeout
    result = agent._execute_single_tool_call_with_timeout(tc, timeout=0.1)
    
    assert result.is_error
    assert "timed out after 0.1 seconds" in result.content


# --- 5. Test agent translates LLM connection errors to friendly user messages ---
def test_agent_user_friendly_exceptions():
    class FailingProvider(OpenAILLMProvider):
        def generate(self, messages, tools=None):
            raise httpx.ConnectTimeout("Connection timed out.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=FailingProvider(api_key="TEST_OPENAI_API_KEY"),
    )

    # When LLM connection fails, agent must catch and translate it
    response = agent.process_message("Hello")
    assert response.is_done
    assert "I'm having trouble connecting to my intelligence core" in response.content
    assert response.metadata["success"] is False


# --- 6. Test observability diagnostic metadata in AgentResponse ---
def test_observability_metadata():
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Checking time...",
                tool_calls=[ToolCall(id="t1", name="get_time_date", arguments={})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        authorizer=AutoApproveAuthorizer.create_for_testing()
    )

    response = agent.process_message("What time is it?")
    
    assert response.is_done
    assert response.metadata is not None
    assert response.metadata["iterations"] == 2
    assert response.metadata["success"] is True
    assert "get_time_date" in response.metadata["tools_used"]
    assert "duration_seconds" in response.metadata
    assert response.metadata["provider"] == "mock"
