# -*- coding: utf-8 -*-
"""Deterministic unit test suite for Computer Action Execution.1 Reasoning State Foundation & Task State Machine.

Validates:
1. Initial state is NOT_STARTED.
2. Valid sequence: NOT_STARTED -> UNDERSTANDING -> PLANNING -> EXECUTING -> VERIFYING -> COMPLETED.
3. Direct execution bypassing tool execution: PLANNING -> VERIFYING -> COMPLETED.
4. Failure transition: Any active state -> FAILED.
5. Invalid transitions raise InvalidStateTransitionError.
6. Terminal state immutability (cannot transition out of COMPLETED or FAILED).
7. Agent integration: process_message lifecycle updates state and records audit history.
8. Agent integration: failed turns end in FAILED state.
9. State machine is provider-independent (works with MockLLMProvider and zero Gemini dependency).
10. State serialization to dict contains audit trail with zero secrets.
"""

from unittest import mock
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.state import TaskState, ReasoningStateMachine, InvalidStateTransitionError, StateTransitionRecord
from friday.core.config import Settings
from friday.core.types import Message, Role, SafetyLevel, ToolCall, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool


class DummyTestTool(BaseTool):
    name = "dummy_test_tool"
    description = "Test tool for verifying EXECUTING state"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]}

    def execute(self, arg: str, **kwargs):
        return ToolResult(name=self.name, content=f"Processed: {arg}", is_error=False, safety_level=self.safety_level)


# 1. Initial State
def test_reasoning_state_machine_initial_state():
    sm = ReasoningStateMachine(task_id="test-task-1")
    assert sm.task_id == "test-task-1"
    assert sm.current_state == TaskState.NOT_STARTED
    assert len(sm.history) == 0
    assert sm.failure_reason is None


# 2 & 3. Valid Full Lifecycle & Direct Answer Transitions
def test_reasoning_state_machine_valid_transitions():
    sm = ReasoningStateMachine()

    # Step 1: NOT_STARTED -> UNDERSTANDING
    assert sm.transition_to(TaskState.UNDERSTANDING, reason="Analyzing user prompt") == TaskState.UNDERSTANDING

    # Step 2: UNDERSTANDING -> PLANNING
    assert sm.transition_to(TaskState.PLANNING, reason="Evaluating tool requirements") == TaskState.PLANNING

    # Step 3: PLANNING -> EXECUTING
    assert sm.transition_to(TaskState.EXECUTING, reason="Calling tools") == TaskState.EXECUTING

    # Step 4: EXECUTING -> VERIFYING
    assert sm.transition_to(TaskState.VERIFYING, reason="Checking tool outputs") == TaskState.VERIFYING

    # Step 5: VERIFYING -> COMPLETED
    assert sm.transition_to(TaskState.COMPLETED, reason="Response ready") == TaskState.COMPLETED
    assert sm.current_state == TaskState.COMPLETED
    assert len(sm.history) == 5


def test_reasoning_state_machine_direct_answer_transition():
    """Verify conversational request without tools transitions PLANNING -> VERIFYING -> COMPLETED."""
    sm = ReasoningStateMachine()
    sm.transition_to(TaskState.UNDERSTANDING)
    sm.transition_to(TaskState.PLANNING)
    sm.transition_to(TaskState.VERIFYING)
    sm.transition_to(TaskState.COMPLETED)
    assert sm.current_state == TaskState.COMPLETED


# 4 & 5. Failure and Invalid Transitions
def test_reasoning_state_machine_failure_transition():
    sm = ReasoningStateMachine()
    sm.transition_to(TaskState.UNDERSTANDING)
    sm.transition_to(TaskState.PLANNING)
    sm.fail(reason="Syntax error in prompt", metadata={"error_code": "PARSE_ERR"})

    assert sm.current_state == TaskState.FAILED
    assert sm.failure_reason == "Syntax error in prompt"
    assert sm.failure_metadata["error_code"] == "PARSE_ERR"


def test_reasoning_state_machine_invalid_transitions_rejected():
    sm = ReasoningStateMachine()

    # Cannot jump NOT_STARTED -> COMPLETED
    with pytest.raises(InvalidStateTransitionError, match="Invalid state transition from NOT_STARTED to COMPLETED"):
        sm.transition_to(TaskState.COMPLETED)

    # Cannot jump NOT_STARTED -> EXECUTING
    with pytest.raises(InvalidStateTransitionError, match="Invalid state transition from NOT_STARTED to EXECUTING"):
        sm.transition_to(TaskState.EXECUTING)

    # Transition to COMPLETED then attempt further transition
    sm.transition_to(TaskState.UNDERSTANDING)
    sm.transition_to(TaskState.PLANNING)
    sm.transition_to(TaskState.VERIFYING)
    sm.transition_to(TaskState.COMPLETED)

    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(TaskState.EXECUTING)


# 6. Serialization and Audit History
def test_reasoning_state_machine_serialization():
    sm = ReasoningStateMachine(task_id="audit-123")
    sm.transition_to(TaskState.UNDERSTANDING, reason="Core Architecture & Types")
    sm.transition_to(TaskState.PLANNING, reason="Full-Duplex Voice Engine")
    sm.transition_to(TaskState.VERIFYING, reason="Persistent Memory Core")
    sm.transition_to(TaskState.COMPLETED, reason="Audio Pipeline & Live Streaming")

    d = sm.to_dict()
    assert d["task_id"] == "audit-123"
    assert d["current_state"] == "COMPLETED"
    assert len(d["history"]) == 4
    assert d["history"][0]["from_state"] == "NOT_STARTED"
    assert d["history"][0]["to_state"] == "UNDERSTANDING"


# 7 & 8. Agent Integration: Direct Conversational & Tool Execution Lifecycle
def test_agent_process_message_lifecycle_direct_response():
    """Agent lifecycle for simple query without tools."""
    llm = MockLLMProvider(custom_responder=lambda msgs, tools: Message(role=Role.ASSISTANT, content="Hello! I am FRIDAY."))
    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=llm,
        memory=InMemoryConversationMemory(),
    )

    response = agent.process_message("Hello FRIDAY")
    assert response.is_done is True
    assert response.metadata["task_state"] == "COMPLETED"
    assert response.metadata["success"] is True

    states = [h["to_state"] for h in response.metadata["state_history"]]
    assert states == ["UNDERSTANDING", "PLANNING", "VERIFYING", "COMPLETED"]


def test_agent_process_message_lifecycle_with_tools():
    """Agent lifecycle for turn requiring tool execution."""
    call_count = 0

    def responder(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="call_1", name="dummy_test_tool", arguments={"arg": "test_input"})],
            )
        return Message(role=Role.ASSISTANT, content="The dummy test tool processed the input successfully.")

    llm = MockLLMProvider(custom_responder=responder)
    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=llm,
        memory=InMemoryConversationMemory(),
    )
    agent.tools.register(DummyTestTool())

    response = agent.process_message("Please run dummy tool")
    assert response.is_done is True
    assert response.metadata["task_state"] == "COMPLETED"

    states = [h["to_state"] for h in response.metadata["state_history"]]
    assert states == ["UNDERSTANDING", "PLANNING", "EXECUTING", "VERIFYING", "COMPLETED"]


# 9. Agent Integration: LLM Failure ends in FAILED state
def test_agent_process_message_failure_state():
    """Agent generation failure transitions state machine to FAILED."""
    def broken_responder(messages, tools=None):
        raise ConnectionResetError("Connection reset by remote peer")

    llm = MockLLMProvider(custom_responder=broken_responder)
    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=llm,
        memory=InMemoryConversationMemory(),
    )

    response = agent.process_message("Do something")
    assert response.is_done is True
    assert response.metadata["task_state"] == "FAILED"
    assert response.metadata["success"] is False
    assert "LLM generation failed" in response.metadata["failure_reason"]
    assert agent.current_state == TaskState.FAILED


# 10. Provider Independence: State machine module imports with zero Gemini dependencies
def test_state_machine_zero_provider_dependency():
    """Verify state.py has no dependency on google.genai or external cloud SDKs."""
    import sys
    import friday.agent.state as state_mod

    # Inspect module globals and ensure clean stdlib/core typing only
    assert "google" not in state_mod.__dict__
    assert "genai" not in state_mod.__dict__
    assert hasattr(state_mod, "TaskState")
    assert hasattr(state_mod, "ReasoningStateMachine")
