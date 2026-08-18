"""Tests for core FridayAgent loop, reasoning, and multi-step tool execution."""

from typing import Any, Dict, List, Optional
from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role, SafetyLevel, ToolCall, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


class StepOneTool(BaseTool):
    name = "step_one_tool"
    description = "First step tool"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Step 1 output for '{query}'",
            is_error=False,
            safety_level=self.safety_level,
        )


class StepTwoTool(BaseTool):
    name = "step_two_tool"
    description = "Second step tool"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"step1_result": {"type": "string"}}, "required": ["step1_result"]}

    def execute(self, step1_result: str, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Step 2 processed: {step1_result}",
            is_error=False,
            safety_level=self.safety_level,
        )


class CrashingTool(BaseTool):
    name = "crashing_tool"
    description = "Throws an exception"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> ToolResult:
        raise ValueError("Critical sensor failure")


class DangerousActionTool(BaseTool):
    name = "wipe_disk"
    description = "Dangerous operation"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(name=self.name, content="Disk wiped", is_error=False, safety_level=self.safety_level)


def test_agent_direct_response():
    """Agent answers directly when no tool is needed."""
    settings = Settings(env="testing", llm_provider="mock", agent_name="FRIDAY")
    agent = FridayAgent(settings=settings)

    response = agent.process_message("What is your name?")
    assert response.is_done
    assert response.tool_calls is None
    assert "FRIDAY" in response.content or "received your request" in response.content

    history = agent.get_history()
    assert len(history) == 2
    assert history[0].role == Role.USER
    assert history[1].role == Role.ASSISTANT


def test_agent_empty_message():
    """Agent handles empty user input gracefully."""
    settings = Settings(env="testing", llm_provider="mock")
    agent = FridayAgent(settings=settings)

    response = agent.process_message("   ")
    assert response.is_done
    assert "listening" in response.content.lower()


def test_agent_valid_tool_execution():
    """Agent identifies intent, invokes tool, and synthesizes final answer."""
    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Checking system diagnostics.",
                tool_calls=[ToolCall(id="call_sysinfo", name="get_system_info", arguments={"category": "os"})],
            )
        return Message(
            role=Role.ASSISTANT,
            content="Your operating system is fully operational and healthy.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
    )

    response = agent.process_message("Please check my OS")
    assert response.is_done
    assert "Your operating system is fully operational" in response.content
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].name == "get_system_info"
    assert not response.tool_results[0].is_error


def test_agent_sequential_multi_step_tool_loop():
    """Agent performs sequential tool calling (Tool A -> Tool B -> Final response)."""
    call_count = 0

    def multi_step_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First turn: call Step 1
            return Message(
                role=Role.ASSISTANT,
                content="Running step 1...",
                tool_calls=[ToolCall(id="call_1", name="step_one_tool", arguments={"query": "data_alpha"})],
            )
        elif call_count == 2:
            # Second turn: verify step 1 output in context and call Step 2
            last_tool_msg = next((m for m in reversed(messages) if m.role == Role.TOOL), None)
            assert last_tool_msg is not None
            assert "Step 1 output for 'data_alpha'" in last_tool_msg.content

            return Message(
                role=Role.ASSISTANT,
                content="Running step 2...",
                tool_calls=[ToolCall(id="call_2", name="step_two_tool", arguments={"step1_result": last_tool_msg.content})],
            )
        else:
            # Third turn: finalize response
            return Message(
                role=Role.ASSISTANT,
                content="Sequential multi-step workflow complete with high precision.",
            )

    provider = MockLLMProvider(custom_responder=multi_step_responder)
    registry = ToolRegistry()
    registry.register(StepOneTool())
    registry.register(StepTwoTool())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=registry,
        max_tool_iterations=5,
    )

    response = agent.process_message("Execute two-stage pipeline")
    assert response.is_done
    assert "Sequential multi-step workflow complete" in response.content
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].name == "step_one_tool"
    assert response.tool_calls[1].name == "step_two_tool"
    assert response.metadata["iterations"] == 3


def test_agent_unknown_tool_handling():
    """Agent handles request for an unregistered tool gracefully without crashing."""
    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calling nonexistent tool.",
                tool_calls=[ToolCall(id="call_ghost", name="nonexistent_tool", arguments={})],
            )
        # Check that error was fed back into context
        tool_msg = next((m for m in reversed(messages) if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "not registered" in tool_msg.content
        return Message(
            role=Role.ASSISTANT,
            content="I was unable to find that tool in my registry.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)

    response = agent.process_message("Run mystery tool")
    assert response.is_done
    assert "unable to find that tool" in response.content
    assert response.tool_results is not None
    assert response.tool_results[0].is_error


def test_agent_invalid_arguments_handling():
    """Agent handles tool call with invalid schema arguments gracefully."""
    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Call step_one_tool with missing required 'query' parameter
            return Message(
                role=Role.ASSISTANT,
                content="Calling tool with bad params.",
                tool_calls=[ToolCall(id="call_bad_args", name="step_one_tool", arguments={"wrong_arg": 123})],
            )
        tool_msg = next((m for m in reversed(messages) if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "Missing required parameter 'query'" in tool_msg.content
        return Message(
            role=Role.ASSISTANT,
            content="Parameter validation failed for step_one_tool.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    registry = ToolRegistry()
    registry.register(StepOneTool())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=registry,
    )

    response = agent.process_message("Trigger bad args")
    assert response.is_done
    assert "Parameter validation failed" in response.content
    assert response.tool_results is not None
    assert response.tool_results[0].is_error


def test_agent_tool_exception_handling():
    """Agent catches tool runtime exceptions and reports safely."""
    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Triggering crashing tool.",
                tool_calls=[ToolCall(id="call_crash", name="crashing_tool", arguments={})],
            )
        tool_msg = next((m for m in reversed(messages) if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "Critical sensor failure" in tool_msg.content
        return Message(
            role=Role.ASSISTANT,
            content="The tool encountered an internal failure.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    registry = ToolRegistry()
    registry.register(CrashingTool())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=registry,
    )

    response = agent.process_message("Test tool crash")
    assert response.is_done
    assert "internal failure" in response.content


def test_agent_safety_blocking():
    """Agent prevents unauthorized execution of dangerous/sensitive tools."""
    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Attempting dangerous action.",
                tool_calls=[ToolCall(id="call_danger", name="wipe_disk", arguments={})],
            )
        tool_msg = next((m for m in reversed(messages) if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "Safety Block" in tool_msg.content
        return Message(
            role=Role.ASSISTANT,
            content="I cannot execute that action without explicit confirmation.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    registry = ToolRegistry()
    registry.register(DangerousActionTool())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=registry,
    )

    # 1. Unapproved -> Blocked
    response = agent.process_message("Wipe the disk", allow_sensitive=False)
    assert response.is_done
    assert "cannot execute that action without explicit confirmation" in response.content
    assert response.tool_results is not None
    assert response.tool_results[0].is_error
    assert response.tool_results[0].safety_level == SafetyLevel.DANGEROUS


def test_agent_max_iterations_guardrail():
    """Agent terminates gracefully if the model loops tool calls endlessly."""
    # Model that always requests a tool call on every single invocation
    def infinite_tool_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        return Message(
            role=Role.ASSISTANT,
            content="Looping...",
            tool_calls=[ToolCall(id="call_loop", name="step_one_tool", arguments={"query": "loop"})],
        )

    provider = MockLLMProvider(custom_responder=infinite_tool_responder)
    registry = ToolRegistry()
    registry.register(StepOneTool())

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=registry,
        max_tool_iterations=3,
    )

    response = agent.process_message("Run infinite loop")
    assert response.is_done
    assert response.metadata["iterations"] == 3
    assert len(response.tool_calls) == 3


def test_agent_tool_callback():
    """Agent calls registered tool_callback during tool execution."""
    events = []

    def callback(tc: ToolCall, tr: ToolResult) -> None:
        events.append((tc.name, tr.is_error))

    call_count = 0

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Running tool.",
                tool_calls=[ToolCall(id="c1", name="get_system_info", arguments={})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_callback=callback,
    )

    agent.process_message("System check")
    assert len(events) == 1
    assert events[0] == ("get_system_info", False)


def test_agent_multi_turn_context_retention():
    """Agent maintains context and memory across multiple conversation turns."""
    agent = FridayAgent(settings=Settings(env="testing"))

    res1 = agent.process_message("My favorite programming language is Python.")
    assert res1.is_done

    res2 = agent.process_message("What is my favorite programming language?")
    assert res2.is_done

    history = agent.get_history()
    assert len(history) == 4
    assert history[0].content == "My favorite programming language is Python."
    # Verify assistant response includes dynamic user name
    expected_content = f"Hello {agent.settings.user_name}, how can you help me?"
    assert history[3].content == expected_content


def test_agent_memory_persists_tool_calls():
    """Verify that intermediate tool call and tool result messages are persisted to memory."""
    call_count = 0
    settings = Settings(env="testing")

    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content=f"All systems nominal, {settings.user_name}.",
                tool_calls=[ToolCall(id="call_persist_info", name="get_system_info", arguments={})],
            )
        return Message(
            role=Role.ASSISTANT,
            content="Diagnostics report processed.",
        )

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)

    response = agent.process_message("Please fetch diagnostics")
    assert response.is_done

    history = agent.get_history()
    # The history should contain:
    # 0: User: "Please fetch diagnostics"
    # 1: Assistant: "Triggering system info" (with tool calls)
    # 2: Tool: (result of get_system_info)
    # 3: Assistant: "Diagnostics report processed"
    assert len(history) == 4
    assert history[0].role == Role.USER
    assert history[1].role == Role.ASSISTANT
    assert history[1].tool_calls is not None
    assert history[1].tool_calls[0].name == "get_system_info"
    assert history[2].role == Role.TOOL
    assert history[2].name == "get_system_info"
    assert history[3].role == Role.ASSISTANT
    assert history[3].content == "Diagnostics report processed."


def test_agent_time_query():
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
        tool_msg = next((m for m in messages if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "Current Local Date" in tool_msg.content
        return Message(role=Role.ASSISTANT, content="The time is 12:00 PM.")

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)
    response = agent.process_message("What time is it?")
    assert response.is_done
    assert "The time is 12:00 PM." in response.content


def test_agent_math_query():
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Calculating...",
                tool_calls=[ToolCall(id="calc1", name="calculator", arguments={"expression": "125 * 48"})],
            )
        tool_msg = next((m for m in messages if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert tool_msg.content == "6000"
        return Message(role=Role.ASSISTANT, content="125 * 48 is 6000.")

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)
    response = agent.process_message("What is 125 * 48?")
    assert response.is_done
    assert "6000" in response.content


def test_agent_list_dir_query():
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Listing directory...",
                tool_calls=[ToolCall(id="list1", name="list_dir", arguments={"path": "."})],
            )
        tool_msg = next((m for m in messages if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "README.md" in tool_msg.content
        return Message(role=Role.ASSISTANT, content="I listed the directory.")

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)
    response = agent.process_message("List the files in this directory.")
    assert response.is_done
    assert "I listed the directory." in response.content


def test_agent_read_file_query():
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Reading file...",
                tool_calls=[ToolCall(id="read1", name="read_file", arguments={"path": "README.md"})],
            )
        tool_msg = next((m for m in messages if m.role == Role.TOOL), None)
        assert tool_msg is not None
        assert "FRIDAY" in tool_msg.content
        return Message(role=Role.ASSISTANT, content="I read the file.")

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider)
    response = agent.process_message("Read this text file.")
    assert response.is_done
    assert "I read the file." in response.content


