"""Tests for Gemini LLM Provider integration with FRIDAY tool calling and safety policies."""

from unittest import mock
import pytest
from google.genai import types as genai_types
from friday.agent.agent import FridayAgent
from friday.core.auth import BaseAuthorizer
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    Message,
    Role,
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class SensitiveTestTool(BaseTool):
    """Test tool that modifies state and requires authorization."""

    name = "modify_system_setting"
    description = "Modify a sensitive system setting."
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "setting_key": {"type": "string", "description": "Key of setting"},
            "setting_value": {"type": "string", "description": "New value"},
        },
        "required": ["setting_key", "setting_value"],
    }

    def execute(self, setting_key: str, setting_value: str) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Setting '{setting_key}' updated to '{setting_value}'.",
            is_error=False,
            safety_level=self.safety_level,
        )


class DangerousTestTool(BaseTool):
    """Test tool that performs destructive action."""

    name = "delete_database"
    description = "Permanently delete database."
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target database"},
        },
        "required": ["target"],
    }

    def execute(self, target: str) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Database '{target}' deleted.",
            is_error=False,
            safety_level=self.safety_level,
        )


class AutoApproveAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(decision=AuthorizationDecision.APPROVED, reason="Test auto-approved")


class AutoDenyAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(decision=AuthorizationDecision.DENIED, reason="Denied by test policy")


def _make_text_response(text: str) -> genai_types.GenerateContentResponse:
    return genai_types.GenerateContentResponse(
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part.from_text(text=text)],
                ),
                finish_reason=genai_types.FinishReason.STOP,
            )
        ]
    )


def _make_tool_response(calls: list[tuple[str, dict]], text: str = "") -> genai_types.GenerateContentResponse:
    parts = []
    if text:
        parts.append(genai_types.Part.from_text(text=text))
    for name, args in calls:
        parts.append(genai_types.Part.from_function_call(name=name, args=args))
    return genai_types.GenerateContentResponse(
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(role="model", parts=parts),
                finish_reason=genai_types.FinishReason.STOP,
            )
        ]
    )


def test_gemini_schema_declaration_fidelity():
    """Verify that BaseTool parameters with complex schemas convert accurately without data loss."""
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-2.5-flash")

    complex_tool = {
        "type": "function",
        "function": {
            "name": "complex_query",
            "description": "Execute complex query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "filters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tags",
                    },
                    "options": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max count"},
                        },
                        "required": ["limit"],
                    },
                },
                "required": ["query", "options"],
            },
        },
    }

    decl = provider._convert_schema_to_gemini(complex_tool)
    assert decl["name"] == "complex_query"
    assert decl["description"] == "Execute complex query"
    assert decl["parameters"]["type"] == "object"
    assert "query" in decl["parameters"]["properties"]
    assert decl["parameters"]["properties"]["filters"]["type"] == "array"
    assert decl["parameters"]["properties"]["options"]["required"] == ["limit"]
    assert decl["parameters"]["required"] == ["query", "options"]


def test_gemini_direct_response_no_tools():
    """Verify Gemini answers ordinary conversational queries directly without invoking tools."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    mock_resp = _make_text_response("Python was created by Guido van Rossum.")
    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = mock_resp

    response = agent.process_message("Who created Python?")

    assert response.is_done is True
    assert "Guido van Rossum" in response.content
    assert response.tool_calls is None or len(response.tool_calls) == 0


def test_gemini_single_tool_call_round_trip():
    """Verify User -> Gemini function call -> FRIDAY validation & execution -> Gemini -> Final answer."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    step1_resp = _make_tool_response([("calculator", {"expression": "128 * 4"})])
    step2_resp = _make_text_response("128 multiplied by 4 is 512.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [step1_resp, step2_resp]

    response = agent.process_message("What is 128 * 4?")

    assert provider._client.models.generate_content.call_count == 2
    assert response.is_done is True
    assert "512" in response.content
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].name == "calculator"
    assert "512" in response.tool_results[0].content


def test_gemini_multiple_parallel_safe_tool_calls():
    """Verify Gemini can request multiple independent SAFE tools that FRIDAY coordinates concurrently."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    step1_resp = _make_tool_response([("get_time_date", {}), ("calculator", {"expression": "99 + 1"})])
    step2_resp = _make_text_response("The current time is retrieved and 99 + 1 is 100.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [step1_resp, step2_resp]

    response = agent.process_message("Give me the time and compute 99 + 1")

    assert response.is_done is True
    assert "100" in response.content
    assert len(response.tool_results) == 2
    tool_names = [tr.name for tr in response.tool_results]
    assert "get_time_date" in tool_names
    assert "calculator" in tool_names


def test_gemini_sequential_multi_step_tool_calls():
    """Verify Step 1 Tool -> Result -> Step 2 Tool -> Result -> Final Answer."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    resp1 = _make_tool_response([("calculator", {"expression": "50 * 2"})])
    resp2 = _make_tool_response([("calculator", {"expression": "100 + 25"})])
    resp3 = _make_text_response("The sequential calculation result is 125.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [resp1, resp2, resp3]

    response = agent.process_message("Calculate 50 * 2 then add 25 to it.")

    assert provider._client.models.generate_content.call_count == 3
    assert response.is_done is True
    assert "125" in response.content
    assert len(response.tool_results) == 2


def test_gemini_sensitive_tool_authorization_denied():
    """Verify that Gemini cannot execute SENSITIVE tools without approval and receives structured denial."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    registry = ToolRegistry()
    registry.register(SensitiveTestTool())
    authorizer = AutoDenyAuthorizer()

    agent = FridayAgent(
        settings=settings,
        llm_provider=provider,
        memory=memory,
        tool_registry=registry,
        authorizer=authorizer,
    )

    resp1 = _make_tool_response([("modify_system_setting", {"setting_key": "theme", "setting_value": "dark"})])
    resp2 = _make_text_response("I was not authorized to modify the theme setting.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [resp1, resp2]

    response = agent.process_message("Change theme to dark")

    assert response.is_done is True
    assert "not authorized" in response.content.lower()
    assert response.tool_results[0].is_error is True
    assert "denied by test policy" in response.tool_results[0].content.lower()


def test_gemini_dangerous_tool_authorization_approved():
    """Verify that DANGEROUS tools execute ONLY when explicitly authorized."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    registry = ToolRegistry()
    registry.register(DangerousTestTool())
    authorizer = AutoApproveAuthorizer()

    agent = FridayAgent(
        settings=settings,
        llm_provider=provider,
        memory=memory,
        tool_registry=registry,
        authorizer=authorizer,
    )

    resp1 = _make_tool_response([("delete_database", {"target": "temp.db"})])
    resp2 = _make_text_response("The database temp.db has been deleted.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [resp1, resp2]

    response = agent.process_message("Delete temp.db")

    assert response.is_done is True
    assert "deleted" in response.content.lower()
    assert response.tool_results[0].is_error is False
    assert "temp.db" in response.tool_results[0].content


def test_gemini_malformed_arguments_recovery():
    """Verify that FRIDAY validates schema before execution and Gemini recovers from argument errors."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    resp1 = _make_tool_response([("calculator", {})])  # missing required expression
    resp2 = _make_tool_response([("calculator", {"expression": "10 * 10"})])
    resp3 = _make_text_response("10 * 10 is 100.")

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = [resp1, resp2, resp3]

    response = agent.process_message("Calculate 10 times 10")

    assert response.is_done is True
    assert "100" in response.content
    assert len(response.tool_results) == 2
    assert response.tool_results[0].is_error is True
    assert "Invalid arguments" in response.tool_results[0].content
    assert response.tool_results[1].is_error is False
    assert "100" in response.tool_results[1].content


def test_gemini_max_iteration_guardrail():
    """Verify FRIDAY halts execution if Gemini enters an infinite tool call loop."""
    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", model="gemini-2.5-flash")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory, max_tool_iterations=3)

    loop_resp = _make_tool_response([("calculator", {"expression": "1 + 1"})])

    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = loop_resp

    response = agent.process_message("Loop forever")

    assert provider._client.models.generate_content.call_count == 3
    assert response.is_done is True
    assert response.metadata["iterations"] == 3
    assert "completed the requested tool operations" in response.content.lower()
    assert len(response.tool_results) == 3
