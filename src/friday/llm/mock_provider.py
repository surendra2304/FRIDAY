"""Deterministic Mock LLM Provider for offline testing and development."""

from typing import Any, Callable, Dict, List, Optional
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM Provider that generates deterministic responses without network calls."""

    def __init__(
        self,
        model: str = "mock-model",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        custom_responder: Optional[Callable[[List[Message], Optional[List[Dict[str, Any]]]], Message]] = None,
    ):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.custom_responder = custom_responder
        self.call_history: List[List[Message]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        self.call_history.append(messages)

        if self.custom_responder:
            return self.custom_responder(messages, tools)

        # Get latest user message content
        last_user_msg = next((m.content for m in reversed(messages) if m.role == Role.USER), "")
        last_user_lower = last_user_msg.lower().strip()

        # Check for tool trigger keywords in mock mode for testing
        if "system info" in last_user_lower or "check system" in last_user_lower:
            if tools and any(t.get("function", {}).get("name") == "get_system_info" for t in tools):
                return Message(
                    role=Role.ASSISTANT,
                    content="I'll inspect the current system information for you.",
                    tool_calls=[
                        ToolCall(id="call_mock_sysinfo_1", name="get_system_info", arguments={})
                    ],
                )

        if not last_user_msg:
            return Message(
                role=Role.ASSISTANT,
                content="Online and ready to assist you. What can I do for you today?",
            )

        return Message(
            role=Role.ASSISTANT,
            content=f"[FRIDAY Mock Mode]: I have received your request: '{last_user_msg}'. All core systems are operational.",
        )
