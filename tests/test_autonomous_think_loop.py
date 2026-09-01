"""Unit tests for FRIDAY's Autonomous Think Loop, Inner Monologue Scratchpad, and Self-Correction Loop."""

from typing import Any

from friday.agent.agent import FridayAgent, strip_thought_tags
from friday.agent.prompts import get_default_system_prompt
from friday.agent.state import TaskState
from friday.core.config import Settings
from friday.core.types import Message, Role, SafetyLevel, ToolCall, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class FailingTool(BaseTool):
    """Tool that fails with a specific error message."""
    name = "flaky_tool"
    description = "A tool that fails on first attempts."
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}

    def __init__(self, fail_count: int = 1, error_msg: str = "FileNotFound: target not found"):
        super().__init__()
        self.fail_count = fail_count
        self.error_msg = error_msg
        self.attempts = 0

    def execute(self, target: str = "", **kwargs: Any) -> ToolResult:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            return ToolResult(
                name=self.name,
                content=self.error_msg,
                is_error=True,
                safety_level=self.safety_level,
            )
        return ToolResult(
            name=self.name,
            content=f"Successfully processed '{target}' on attempt {self.attempts}.",
            is_error=False,
            safety_level=self.safety_level,
        )


class AlternativeTool(BaseTool):
    """Backup / fallback tool for recovery."""
    name = "backup_search_tool"
    description = "Backup search tool."
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Found backup item for '{query}' at '/path/to/backup.txt'",
            is_error=False,
            safety_level=self.safety_level,
        )


class OpenFileTool(BaseTool):
    """Safe tool to open a file."""
    name = "open_file"
    description = "Open a file."
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Opened file '{path}' successfully.",
            is_error=False,
            safety_level=self.safety_level,
        )


def test_system_prompt_includes_inner_monologue_and_autonomous_thinking():
    """Verify system prompt contains instructions for inner monologue and autonomous goal completion."""
    settings = Settings(env="testing", agent_name="FRIDAY")
    prompt = get_default_system_prompt(settings)

    assert "INNER MONOLOGUE & AUTONOMOUS THINKING" in prompt
    assert "<thought>" in prompt
    assert "What is my goal?" in prompt
    assert "What tool do I need?" in prompt
    assert "What do I expect to happen?" in prompt
    assert "AUTONOMOUS GOAL COMPLETION & TOOL CHAINING" in prompt
    assert "chain the necessary tools together autonomously" in prompt


def test_strip_thought_tags():
    """Test helper that strips thought tags while preserving user-facing response."""
    # Thought followed by response
    t1 = "<thought>Goal: find file. Tool: search.</thought>I found your resume at /docs/resume.pdf."
    assert strip_thought_tags(t1) == "I found your resume at /docs/resume.pdf."

    # Multiline thought
    t2 = """<thought>
    What is my goal? Open settings.
    What tool do I need? open_settings.
    What do I expect to happen? Settings app will open.
    </thought>
    Settings app opened successfully."""
    assert strip_thought_tags(t2) == "Settings app opened successfully."

    # Only thought text present
    t3 = "<thought>Completed everything smoothly.</thought>"
    assert strip_thought_tags(t3) == "Completed everything smoothly."

    # Normal text without thought
    t4 = "Done."
    assert strip_thought_tags(t4) == "Done."


def test_agent_inner_monologue_scratchpad_logged_and_stripped():
    """Agent records <thought> in scratchpad and presents clean output to user."""
    call_count = 0

    def mock_responder(messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="<thought>Goal: Find user resume. Tool: backup_search_tool.</thought>",
                tool_calls=[ToolCall(id="tc_1", name="backup_search_tool", arguments={"query": "resume"})],
            )
        return Message(
            role=Role.ASSISTANT,
            content="<thought>Goal achieved. Now formulating response.</thought>I located your resume and it is ready.",
        )

    reg = ToolRegistry()
    reg.register(AlternativeTool())
    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider, tool_registry=reg)

    response = agent.process_message("Find my resume")
    assert response.is_done
    assert response.content == "I located your resume and it is ready."
    assert "<thought>" not in response.content


def test_agent_self_correction_loop_recovers_after_tool_error():
    """When a tool returns an error, agent injects self-correction prompt and succeeds on retry."""
    call_count = 0
    received_system_feedback = []

    def mock_responder(messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: call flaky tool (which fails)
            return Message(
                role=Role.ASSISTANT,
                content="<thought>Goal: access file. Tool: flaky_tool.</thought>",
                tool_calls=[ToolCall(id="tc_flaky", name="flaky_tool", arguments={"target": "primary_file.txt"})],
            )
        elif call_count == 2:
            # Check that self-correction system message was injected
            sys_msgs = [m for m in messages if m.role == Role.SYSTEM and "Your previous tool call 'flaky_tool' failed with this error" in m.content]
            if sys_msgs:
                received_system_feedback.append(sys_msgs[-1].content)

            # Second attempt: switch to alternative backup tool
            return Message(
                role=Role.ASSISTANT,
                content="<thought>Previous tool failed with FileNotFound. Adjusting plan to use backup tool.</thought>",
                tool_calls=[ToolCall(id="tc_backup", name="backup_search_tool", arguments={"query": "primary_file"})],
            )
        else:
            return Message(
                role=Role.ASSISTANT,
                content="I recovered from the initial file error and located your file using the backup search tool.",
            )

    flaky = FailingTool(fail_count=1, error_msg="FileNotFound: primary_file.txt does not exist")
    backup = AlternativeTool()
    reg = ToolRegistry()
    reg.register(flaky)
    reg.register(backup)

    provider = MockLLMProvider(custom_responder=mock_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider, tool_registry=reg)

    response = agent.process_message("Get primary_file.txt")
    assert response.is_done
    assert "recovered from the initial file error" in response.content
    assert len(received_system_feedback) >= 1
    assert "Your previous tool call 'flaky_tool' failed with this error" in received_system_feedback[0]
    assert response.metadata["success"] is True
    assert agent.state_machine.current_state == TaskState.COMPLETED


def test_agent_self_correction_loop_respects_max_3_retries():
    """Agent limits autonomous error retries to 3 before terminating and explaining error."""
    # Tool that always fails
    always_failing_tool = FailingTool(fail_count=10, error_msg="401 Unauthorized: Invalid API token")
    reg = ToolRegistry()
    reg.register(always_failing_tool)

    # Responder that endlessly tries the failing tool
    def endless_failing_responder(messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        return Message(
            role=Role.ASSISTANT,
            content="<thought>Trying to access secured resource.</thought>",
            tool_calls=[ToolCall(id=f"tc_{len(messages)}", name="flaky_tool", arguments={"target": "secret"})],
        )

    provider = MockLLMProvider(custom_responder=endless_failing_responder)
    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=provider,
        tool_registry=reg,
        max_tool_iterations=10,
    )

    response = agent.process_message("Access secret data")
    assert response.is_done
    assert "encountered persistent errors" in response.content or "401 Unauthorized" in response.content
    assert always_failing_tool.attempts <= 4  # Initial attempt + at most 3 retries
    assert agent.state_machine.current_state == TaskState.FAILED


def test_agent_autonomous_multi_step_tool_chaining():
    """Agent chains multiple SAFE tools autonomously without asking for permission on each step."""
    call_count = 0

    def chaining_responder(messages: list[Message], tools: list[dict[str, Any]] | None) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="<thought>Goal: Find resume and open it. Step 1: Search for resume.</thought>",
                tool_calls=[ToolCall(id="tc_search", name="backup_search_tool", arguments={"query": "resume"})],
            )
        elif call_count == 2:
            return Message(
                role=Role.ASSISTANT,
                content="<thought>Found resume at /path/to/backup.txt. Step 2: Open file autonomously without stopping.</thought>",
                tool_calls=[ToolCall(id="tc_open", name="open_file", arguments={"path": "/path/to/backup.txt"})],
            )
        else:
            return Message(
                role=Role.ASSISTANT,
                content="I found your resume at /path/to/backup.txt and opened it for you.",
            )

    reg = ToolRegistry()
    reg.register(AlternativeTool())
    reg.register(OpenFileTool())

    provider = MockLLMProvider(custom_responder=chaining_responder)
    agent = FridayAgent(settings=Settings(env="testing"), llm_provider=provider, tool_registry=reg)

    response = agent.process_message("Find my resume and open it")
    assert response.is_done
    assert "opened it for you" in response.content
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].name == "backup_search_tool"
    assert response.tool_calls[1].name == "open_file"
    assert agent.state_machine.current_state == TaskState.COMPLETED