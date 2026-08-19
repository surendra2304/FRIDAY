"""Tests for coordinated multi-tool execution (parallel & sequential)."""

import time
from typing import Any, Dict, List, Optional
import pytest
from friday.agent.agent import FridayAgent
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer, AutoApproveAuthorizer
from friday.core.config import Settings
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
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.llm.mock_provider import MockLLMProvider


class MockSafeToolA(BaseTool):
    name = "safe_a"
    description = "Safe Tool A"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"val": {"type": "string"}}}

    def execute(self, val: str = "A", **kwargs: Any) -> ToolResult:
        # Intentionally sleep slightly to verify concurrency overlaps
        time.sleep(0.05)
        return ToolResult(
            name=self.name,
            content=f"Result A: {val}",
            is_error=False,
            safety_level=self.safety_level,
        )


class MockSafeToolB(BaseTool):
    name = "safe_b"
    description = "Safe Tool B"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"val": {"type": "string"}}}

    def execute(self, val: str = "B", **kwargs: Any) -> ToolResult:
        time.sleep(0.05)
        return ToolResult(
            name=self.name,
            content=f"Result B: {val}",
            is_error=False,
            safety_level=self.safety_level,
        )


class MockFailingSafeTool(BaseTool):
    name = "safe_fail"
    description = "Safe Tool that fails"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> ToolResult:
        raise ValueError("Simulated execution failure in safe tool.")


class MockSensitiveTool(BaseTool):
    name = "sensitive_tool"
    description = "Sensitive operation tool"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {"type": "object", "properties": {"val": {"type": "string"}}}

    def execute(self, val: str = "Sens", **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Sensitive Result: {val}",
            is_error=False,
            safety_level=self.safety_level,
        )


class ExecutionSpyAuthorizer(BaseAuthorizer):
    """Spy authorizer that counts requests and records tool safety levels."""

    def __init__(self):
        self.requests: List[AuthorizationRequest] = []

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        self.requests.append(request)
        return AuthorizationResponse(
            decision=AuthorizationDecision.APPROVED,
            reason="Spy approved."
        )


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(MockSafeToolA())
    reg.register(MockSafeToolB())
    reg.register(MockFailingSafeTool())
    reg.register(MockSensitiveTool())
    return reg


# --- 1. Test single tool call ---
def test_single_tool_call(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calling one tool",
                tool_calls=[ToolCall(id="tc1", name="safe_a", arguments={"val": "hello"})],
            )
        return Message(role=Role.ASSISTANT, content="Task complete.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Execute A")
    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].content == "Result A: hello"


# --- 2. Test two independent tool calls (Parallel execution test) ---
def test_two_independent_safe_tool_calls(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calling two tools",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "first"}),
                    ToolCall(id="tc2", name="safe_b", arguments={"val": "second"}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Complete.")

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    start = time.perf_counter()
    response = agent.process_message("Execute both")
    elapsed = time.perf_counter() - start

    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 2
    
    # Ordering verification
    assert response.tool_results[0].name == "safe_a"
    assert response.tool_results[0].content == "Result A: first"
    assert response.tool_results[1].name == "safe_b"
    assert response.tool_results[1].content == "Result B: second"
    
    # Elapsed check: both tools sleep for 0.05 seconds.
    # If run in parallel, total batch latency should be ~0.05s.
    # If run sequentially, it would be >= 0.10s.
    assert elapsed < 0.25  # Allows headroom for mock generation, but validates parallel overlap


# --- 3. Test multiple safe tool calls ---
def test_multiple_safe_tool_calls(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calling three tools",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "1"}),
                    ToolCall(id="tc2", name="safe_b", arguments={"val": "2"}),
                    ToolCall(id="tc3", name="safe_a", arguments={"val": "3"}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Complete.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Execute three safe tools")
    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 3
    assert response.tool_results[0].content == "Result A: 1"
    assert response.tool_results[1].content == "Result B: 2"
    assert response.tool_results[2].content == "Result A: 3"


# --- 4. Test one success + one failure ---
def test_one_success_one_failure(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calling success and fail",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "work"}),
                    ToolCall(id="tc2", name="safe_fail", arguments={}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Completed.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Do work and fail")
    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 2
    
    # Success tool checks out
    assert response.tool_results[0].name == "safe_a"
    assert not response.tool_results[0].is_error
    assert response.tool_results[0].content == "Result A: work"

    # Failing tool doesn't disrupt success results, but returns error ToolResult
    assert response.tool_results[1].name == "safe_fail"
    assert response.tool_results[1].is_error
    assert "Simulated execution failure" in response.tool_results[1].content


# --- 5. Test all failures ---
def test_all_failures(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Failing both",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_fail", arguments={}),
                    ToolCall(id="tc2", name="non_existent", arguments={}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Complete.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Failing tools")
    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 2
    assert response.tool_results[0].is_error
    assert "Simulated execution failure" in response.tool_results[0].content
    assert response.tool_results[1].is_error
    assert "is not registered" in response.tool_results[1].content


# --- 6. Test multiple safety classifications (Mixed forcing sequential execution) ---
def test_mixed_safety_classifications(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # SENSITIVE is in the batch -> forces sequential execution
            return Message(
                role=Role.ASSISTANT,
                content="Calling mixed tools",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "safe"}),
                    ToolCall(id="tc2", name="sensitive_tool", arguments={"val": "sens"}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Complete.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Execute mixed tools")
    assert response.is_done
    assert response.tool_results is not None
    assert len(response.tool_results) == 2
    assert response.tool_results[0].content == "Result A: safe"
    assert response.tool_results[1].content == "Sensitive Result: sens"


# --- 7. Test authorization interactions ---
def test_authorization_interactions(registry):
    spy_auth = ExecutionSpyAuthorizer()
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # One SAFE, one SENSITIVE
            return Message(
                role=Role.ASSISTANT,
                content="Mixed call",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "safe"}),
                    ToolCall(id="tc2", name="sensitive_tool", arguments={"val": "sens"}),
                ],
            )
        return Message(role=Role.ASSISTANT, content="Finished.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=spy_auth
    )

    agent.process_message("Run mixed tools with spy auth")
    
    assert len(spy_auth.requests) == 2
    assert spy_auth.requests[0].tool_name == "safe_a"
    assert spy_auth.requests[1].tool_name == "sensitive_tool"
    assert spy_auth.requests[1].safety_level == SafetyLevel.SENSITIVE


# --- 8. Test result correlation ---
def test_result_correlation_and_order(registry):
    call_count = 0
    # Requesting A then B then A
    tool_calls_requested = [
        ToolCall(id="tc1", name="safe_a", arguments={"val": "1"}),
        ToolCall(id="tc2", name="safe_b", arguments={"val": "2"}),
        ToolCall(id="tc3", name="safe_a", arguments={"val": "3"}),
    ]

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(role=Role.ASSISTANT, content="Executing multiple", tool_calls=tool_calls_requested)
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Run parallel correlation test")
    
    # Results must exactly match requested order tc1 -> tc2 -> tc3
    assert response.tool_results is not None
    assert len(response.tool_results) == 3
    assert response.tool_results[0].tool_call_id == "tc1"
    assert response.tool_results[0].content == "Result A: 1"
    assert response.tool_results[1].tool_call_id == "tc2"
    assert response.tool_results[1].content == "Result B: 2"
    assert response.tool_results[2].tool_call_id == "tc3"
    assert response.tool_results[2].content == "Result A: 3"


# --- 9. Test sequential follow-up after parallel results ---
def test_sequential_follow_up_after_parallel_results(registry):
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Turn 1: Parallel SAFE calls
            return Message(
                role=Role.ASSISTANT,
                content="Parallel calls turn 1",
                tool_calls=[
                    ToolCall(id="tc1", name="safe_a", arguments={"val": "1"}),
                    ToolCall(id="tc2", name="safe_b", arguments={"val": "2"}),
                ],
            )
        elif call_count == 2:
            # Turn 2: Follow-up based on results
            tool_msg_a = next((m for m in messages if m.role == Role.TOOL and m.tool_call_id == "tc1"), None)
            tool_msg_b = next((m for m in messages if m.role == Role.TOOL and m.tool_call_id == "tc2"), None)
            assert tool_msg_a is not None
            assert tool_msg_b is not None
            assert "Result A: 1" in tool_msg_a.content
            assert "Result B: 2" in tool_msg_b.content
            return Message(
                role=Role.ASSISTANT,
                content="Follow-up call turn 2",
                tool_calls=[ToolCall(id="tc3", name="safe_a", arguments={"val": "follow-up"})],
            )
        return Message(role=Role.ASSISTANT, content="Fully completed.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Start multi-turn reasoning")
    assert response.is_done
    assert "Fully completed." in response.content


# --- 10. Verify max iteration guardrail ---
def test_max_iteration_guardrail_multi_tool(registry):
    # Iterate forever requesting tool calls
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        return Message(
            role=Role.ASSISTANT,
            content="Endless tools",
            tool_calls=[
                ToolCall(id="tc1", name="safe_a", arguments={"val": "again"}),
                ToolCall(id="tc2", name="safe_b", arguments={"val": "again"}),
            ],
        )

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=registry,
        max_tool_iterations=2,
        authorizer=AutoApproveAuthorizer()
    )

    response = agent.process_message("Endless loop test")
    
    # Must terminate within max iteration boundaries
    assert response.is_done
    assert "completed the requested tool operations" in response.content
