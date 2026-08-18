"""Tests for core FridayAgent loop and orchestration."""

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role, ToolCall
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


def test_agent_basic_chat():
    settings = Settings(env="testing", llm_provider="mock", agent_name="FRIDAY", user_name="Boss")
    agent = FridayAgent(settings=settings)

    response = agent.process_message("Status report please")
    assert response.is_done
    assert "Status report please" in response.content

    history = agent.get_history()
    assert len(history) == 2
    assert history[0].role == Role.USER
    assert history[1].role == Role.ASSISTANT


def test_agent_empty_message():
    settings = Settings(env="testing", llm_provider="mock")
    agent = FridayAgent(settings=settings)

    response = agent.process_message("   ")
    assert response.is_done
    assert "listening" in response.content.lower()


def test_agent_with_tool_execution():
    # Setup custom mock provider that triggers system info tool on first call,
    # and synthesizes final answer on second call
    call_count = 0

    def custom_responder(messages, tools):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Checking system info.",
                tool_calls=[
                    ToolCall(id="call_1", name="get_system_info", arguments={})
                ],
            )
        else:
            return Message(
                role=Role.ASSISTANT,
                content="All systems report normal operating conditions.",
            )

    provider = MockLLMProvider(custom_responder=custom_responder)
    registry = ToolRegistry()
    registry.register(SystemInfoTool())
    memory = InMemoryConversationMemory(max_messages=10)

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        memory=memory,
        tool_registry=registry,
    )

    response = agent.process_message("Check system status")
    assert response.is_done
    assert "All systems report normal operating conditions." in response.content
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].name == "get_system_info"
    assert not response.tool_results[0].is_error


def test_agent_status_and_clear():
    agent = FridayAgent(settings=Settings(env="testing"))
    agent.process_message("Remember this")

    status = agent.get_status()
    assert status["agent_name"] == "FRIDAY"
    assert status["memory_messages"] == 2
    assert "get_system_info (SAFE)" in status["tools_registered"]

    agent.clear_memory()
    assert len(agent.get_history()) == 0
