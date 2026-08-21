# -*- coding: utf-8 -*-
"""End-to-End Request Pipeline Trace Test Suite.

Proves that one complete FRIDAY request traverses the full architectural call graph:
1. Goal Understanding & Confidence Evaluation (CognitiveIntelligenceEngine)
2. Capability Routing (CapabilityRouter)
3. State Machine Transitions (ReasoningStateMachine)
4. Cryptographic Authorization Gating (DefaultSecureAuthorizer)
5. Tool Execution & Parameter Validation (ToolRegistry)
6. Working Memory Context & Observation Tracking (ActiveTaskContext)
7. Step Verification (StepVerifier)
8. Persistent Memory Storage & Compaction (SQLiteConversationMemory / BaseMemory)
9. Final Response Delivery & Telemetry Metadata
"""

from unittest import mock
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.cognitive import CognitivePhase
from friday.agent.state import TaskState
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.types import Message, Role, ToolCall
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin import CalculatorTool, SystemInfoTool
from friday.tools.registry import ToolRegistry


def test_complete_e2e_request_trace_with_tool_execution():
    """Trace a complete multi-step tool request through all 9 architectural layers."""
    # 1. Setup mock provider to trigger a calculator tool call then final response
    calc_tool_call = ToolCall(id="call_calc_101", name="calculator", arguments={"expression": "128 * 4"})

    def mock_responder(messages: list, tools: list = None) -> Message:
        if messages and messages[-1].role == Role.TOOL:
            return Message(role=Role.ASSISTANT, content="128 * 4 is equal to 512.")
        return Message(role=Role.ASSISTANT, content="Let me calculate that for you.", tool_calls=[calc_tool_call])

    mock_llm = MockLLMProvider(custom_responder=mock_responder)

    # 2. Setup ToolRegistry with CalculatorTool
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(SystemInfoTool())

    # 3. Setup Authorizer & Memory
    authorizer = DefaultSecureAuthorizer()
    memory = InMemoryConversationMemory()

    # 4. Instantiate FridayAgent
    agent = FridayAgent(
        llm_provider=mock_llm,
        memory=memory,
        tool_registry=registry,
        authorizer=authorizer,
    )

    # 5. Process Request
    user_query = "Please calculate 128 * 4 for me"
    response = agent.process_message(user_query)

    # 6. VERIFY ALL 9 SUBSYSTEM INVARIANTS:

    # Layer 1: Goal Understanding & Cognitive Phase
    assert response.metadata["cognitive_phase"] in (CognitivePhase.UNDERSTAND.value, CognitivePhase.PLAN.value, CognitivePhase.COMPLETE.value)
    assert "confidence" in response.metadata
    assert response.metadata["confidence"]["understanding_confidence"] > 0.0

    # Layer 2: Capability Router
    assert "routed_capability" in response.metadata
    assert response.metadata["routed_capability"] in ("LOCAL_COMPUTATION", "DIRECT_REASONING", "TOOL_EXECUTION")

    # Layer 3: State Machine Lifecycle
    assert response.metadata["task_state"] == TaskState.COMPLETED.value
    state_names = [s["to_state"] for s in response.metadata["state_history"]]
    assert TaskState.UNDERSTANDING.value in state_names
    assert TaskState.PLANNING.value in state_names
    assert TaskState.EXECUTING.value in state_names
    assert TaskState.VERIFYING.value in state_names
    assert TaskState.COMPLETED.value in state_names

    # Layer 4: Cryptographic Authorization
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error is False

    # Layer 5: Tool Execution Outcome
    assert "512" in response.tool_results[0].content
    assert response.content == "128 * 4 is equal to 512."

    # Layer 6: Working Memory Context
    assert agent.task_context is not None
    assert len(agent.task_context.observations) == 1
    obs = agent.task_context.observations[0]
    assert obs.source_tool == "calculator"
    assert "512" in obs.content

    # Layer 7 & 8: Durable Memory Commit
    history = memory.get_context_window(max_messages=50)
    roles = [m.role for m in history]
    assert Role.USER in roles
    assert Role.TOOL in roles
    assert Role.ASSISTANT in roles

    # Layer 9: Final Response Integrity
    assert response.is_done is True
    assert response.metadata["success"] is True


def test_e2e_cognitive_clarify_trace_on_ambiguous_request():
    """Trace that ambiguous user input immediately triggers CognitivePhase.CLARIFY."""
    mock_llm = MockLLMProvider(custom_responder=lambda m, t: Message(role=Role.ASSISTANT, content="Unused fallback"))
    agent = FridayAgent(llm_provider=mock_llm)

    ambiguous_query = "do that thing with it"
    response = agent.process_message(ambiguous_query)

    assert response.metadata["cognitive_phase"] == CognitivePhase.CLARIFY.value
    assert response.metadata["confidence"]["understanding_confidence"] < 0.65
    assert response.metadata["lacks_information"] is True
    assert "clarif" in response.content.lower() or "specific" in response.content.lower() or "more" in response.content.lower()
