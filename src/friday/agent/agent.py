"""Core Agent orchestration loop for FRIDAY."""

import time
from typing import Any, Dict, List, Optional
from friday.agent.prompts import build_system_message
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from friday.core.types import AgentResponse, Message, Role, ToolResult
from friday.llm.base import BaseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.memory.base import BaseMemory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.core")


class FridayAgent:
    """The central FRIDAY agent orchestrating reasoning, memory, tools, and output."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        memory: Optional[BaseMemory] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm_provider or create_llm_provider(self.settings)
        self.memory = memory or InMemoryConversationMemory(max_messages=self.settings.memory_max_messages)
        self.tools = tool_registry or self._create_default_registry()
        self.system_message = build_system_message(self.settings)

        logger.info(
            f"Initialized {self.settings.agent_name} with provider '{self.llm.provider_name}' "
            f"(model: '{self.llm.model}') and {len(self.tools.list_tools())} loaded tools."
        )

    def _create_default_registry(self) -> ToolRegistry:
        """Instantiate default tool registry with built-in safe tools."""
        registry = ToolRegistry()
        registry.register(SystemInfoTool())
        return registry

    def process_message(
        self,
        user_input: str,
        allow_sensitive: bool = False,
    ) -> AgentResponse:
        """Process a single turn of user input through memory, reasoning, and tools."""
        start_time = time.perf_counter()
        clean_input = user_input.strip()

        if not clean_input:
            return AgentResponse(
                content="I'm listening. How can I help you, Boss?",
                is_done=True,
            )

        logger.info(f"Processing user turn: '{clean_input[:60]}...'")

        # 1. Store user message in memory
        user_msg = Message(role=Role.USER, content=clean_input)
        self.memory.add_message(user_msg)

        # 2. Build conversation context (System Message + Stored Memory History)
        context_messages = [self.system_message] + self.memory.get_context_window(self.settings.memory_max_messages)

        # 3. Retrieve tool schemas
        tool_schemas = self.tools.get_schemas() if self.tools.list_tools() else None

        # 4. Invoke LLM provider
        try:
            assistant_msg = self.llm.generate(messages=context_messages, tools=tool_schemas)
        except Exception as e:
            logger.exception(f"LLM generation failed: {e}")
            error_response = f"I encountered an issue processing your request: {str(e)}"
            self.memory.add_message(Message(role=Role.ASSISTANT, content=error_response))
            return AgentResponse(
                content=error_response,
                is_done=True,
                metadata={"error": str(e)},
            )

        executed_tool_results: List[ToolResult] = []

        # 5. Handle Tool Calling if requested
        if assistant_msg.tool_calls:
            logger.info(f"Agent requested {len(assistant_msg.tool_calls)} tool call(s)")
            # Add the assistant message with tool calls to context
            context_messages.append(assistant_msg)

            for tc in assistant_msg.tool_calls:
                result = self.tools.execute(
                    name=tc.name,
                    arguments=tc.arguments,
                    tool_call_id=tc.id,
                    allow_sensitive=allow_sensitive,
                )
                executed_tool_results.append(result)

                # Add tool execution result message
                context_messages.append(
                    Message(
                        role=Role.TOOL,
                        name=tc.name,
                        content=result.content,
                        tool_call_id=tc.id,
                    )
                )

            # Re-invoke LLM with tool outputs to synthesize the final response
            try:
                final_assistant_msg = self.llm.generate(messages=context_messages)
                final_content = final_assistant_msg.content or "Tool execution completed."
            except Exception as e:
                logger.exception(f"LLM tool synthesis failed: {e}")
                # Fallback to formatting tool results directly
                summaries = "\n\n".join(r.content for r in executed_tool_results)
                final_content = f"Tools executed:\n\n{summaries}"
        else:
            final_content = assistant_msg.content

        # 6. Save final assistant response to memory
        final_msg = Message(role=Role.ASSISTANT, content=final_content)
        self.memory.add_message(final_msg)

        duration = time.perf_counter() - start_time
        logger.info(f"Turn processed successfully in {duration:.2f}s")

        return AgentResponse(
            content=final_content,
            tool_calls=assistant_msg.tool_calls,
            tool_results=executed_tool_results if executed_tool_results else None,
            is_done=True,
            metadata={
                "duration_seconds": duration,
                "provider": self.llm.provider_name,
                "model": self.llm.model,
            },
        )

    def get_history(self) -> List[Message]:
        """Retrieve stored conversation messages."""
        return self.memory.get_messages()

    def clear_memory(self) -> None:
        """Reset conversation memory."""
        self.memory.clear()

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status information about the agent."""
        return {
            "agent_name": self.settings.agent_name,
            "user_name": self.settings.user_name,
            "provider": self.llm.provider_name,
            "model": self.llm.model,
            "memory_messages": len(self.memory.get_messages()),
            "memory_capacity": self.settings.memory_max_messages,
            "tools_registered": [f"{t.name} ({t.safety_level.value})" for t in self.tools.list_tools()],
        }
