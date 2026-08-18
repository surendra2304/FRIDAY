"""Core Agent orchestration loop with multi-step sequential tool calling for FRIDAY."""

import time
from typing import Any, Callable, Dict, List, Optional
from friday.agent.prompts import build_system_message
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from friday.core.types import (
    AgentResponse,
    Message,
    Role,
    ToolCall,
    ToolResult,
    AuthorizationRequest,
    AuthorizationResponse,
    AuthorizationDecision,
    SafetyLevel,
)
from friday.llm.base import BaseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.memory.base import BaseMemory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin import (
    SystemInfoTool,
    TimeDateTool,
    CalculatorTool,
    FileReaderTool,
    FileListingTool,
)
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.core")


class FridayAgent:
    """The central FRIDAY agent orchestrating reasoning, memory, multi-step tool calling, and output."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        memory: Optional[BaseMemory] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_tool_iterations: int = 5,
        tool_callback: Optional[Callable[[ToolCall, ToolResult], None]] = None,
        authorizer: Optional[BaseAuthorizer] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm_provider or create_llm_provider(self.settings)
        self.memory = memory or InMemoryConversationMemory(max_messages=self.settings.memory_max_messages)
        self.tools = tool_registry or self._create_default_registry()
        self.max_tool_iterations = max(1, max_tool_iterations)
        self.tool_callback = tool_callback
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.system_message = build_system_message(self.settings)

        logger.info(
            f"Initialized {self.settings.agent_name} with provider '{self.llm.provider_name}' "
            f"(model: '{self.llm.model}') and {len(self.tools.list_tools())} loaded tools. "
            f"Max tool iterations: {self.max_tool_iterations}."
        )

    def _create_default_registry(self) -> ToolRegistry:
        """Instantiate default tool registry with built-in safe tools."""
        registry = ToolRegistry()
        registry.register(SystemInfoTool())
        registry.register(TimeDateTool())
        registry.register(CalculatorTool())
        registry.register(FileReaderTool())
        registry.register(FileListingTool())
        return registry

    def process_message(
        self,
        user_input: str,
        allow_sensitive: bool = False,
    ) -> AgentResponse:
        """Process a user message through reasoning, safety validation, and sequential tool execution."""
        start_time = time.perf_counter()
        clean_input = user_input.strip()

        if not clean_input:
            return AgentResponse(
                content="I'm listening. How can I assist you today, Boss?",
                is_done=True,
            )

        logger.info(f"Processing user turn: '{clean_input[:60]}...'")

        # 1. Append user message to long-term memory
        user_msg = Message(role=Role.USER, content=clean_input)
        self.memory.add_message(user_msg)

        # 2. Construct conversation context window (System Prompt + Memory Slice)
        working_context: List[Message] = [self.system_message] + self.memory.get_context_window(
            self.settings.memory_max_messages
        )

        # 3. Retrieve registered tool schemas
        tool_schemas = self.tools.get_schemas() if self.tools.list_tools() else None

        all_tool_calls: List[ToolCall] = []
        all_tool_results: List[ToolResult] = []
        final_content = ""
        iterations = 0

        # 4. Multi-step Reasoning & Tool-calling Loop
        while iterations < self.max_tool_iterations:
            iterations += 1
            logger.debug(f"Agent decision iteration {iterations}/{self.max_tool_iterations}")

            # Rebuild working context from memory dynamically to maintain precise dialogue history
            working_context = [self.system_message] + self.memory.get_context_window(
                self.settings.memory_max_messages
            )

            try:
                assistant_msg = self.llm.generate(messages=working_context, tools=tool_schemas)
            except Exception as e:
                logger.exception(f"LLM generation failed at iteration {iterations}: {e}")
                err_text = f"I encountered an error communicating with the intelligence core: {str(e)}"
                self.memory.add_message(Message(role=Role.ASSISTANT, content=err_text))
                return AgentResponse(
                    content=err_text,
                    is_done=True,
                    metadata={"error": str(e), "iterations": iterations},
                )

            # If model returned direct answer without requesting tools -> finished turn
            if not assistant_msg.tool_calls:
                final_content = assistant_msg.content or "Task completed."
                break

            # Model requested one or more tool calls
            logger.info(f"Iteration {iterations}: Model requested {len(assistant_msg.tool_calls)} tool call(s)")
            
            # Persist assistant's tool call intent message to memory
            self.memory.add_message(assistant_msg)

            for tc in assistant_msg.tool_calls:
                all_tool_calls.append(tc)

                tool = self.tools.get(tc.name)
                if not tool:
                    err_msg = f"Error: Tool '{tc.name}' is not registered or available in FRIDAY's tool registry."
                    logger.warning(err_msg)
                    result = ToolResult(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=err_msg,
                        is_error=True,
                        safety_level=SafetyLevel.SAFE,
                    )
                else:
                    # 1. Validation happens BEFORE authorization request
                    is_valid, validation_err = tool.validate_arguments(tc.arguments)
                    if not is_valid:
                        err_msg = f"Invalid arguments for tool '{tc.name}': {validation_err}"
                        logger.warning(err_msg)
                        result = ToolResult(
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=err_msg,
                            is_error=True,
                            safety_level=tool.safety_level,
                        )
                    else:
                        # 2. Extract affected resource (e.g. file paths) if present
                        affected_res = tc.arguments.get("path") or tc.arguments.get("file_path") or tc.arguments.get("directory")
                        if affected_res:
                            affected_res = str(affected_res)

                        auth_req = AuthorizationRequest(
                            tool_name=tc.name,
                            safety_level=tool.safety_level,
                            arguments=tc.arguments,
                            purpose=tool.description,
                            affected_resource=affected_res,
                        )

                        # 3. Handle authorization check (legacy allow_sensitive auto-approves for tests compatibility)
                        if allow_sensitive:
                            auth_resp = AuthorizationResponse(
                                decision=AuthorizationDecision.APPROVED,
                                reason="Bypassed authorization check via legacy allow_sensitive=True flag.",
                            )
                        else:
                            logger.info(f"Requesting authorization for tool '{tc.name}' [Safety: {tool.safety_level.value}]")
                            auth_resp = self.authorizer.authorize(auth_req)

                        logger.info(
                            f"Authorization outcome for tool '{tc.name}': {auth_resp.decision.value} "
                            f"(Reason: {auth_resp.reason})"
                        )

                        # 4. Execution happens ONLY after explicit authorization
                        if auth_resp.decision == AuthorizationDecision.APPROVED:
                            result = self.tools.execute(
                                name=tc.name,
                                arguments=tc.arguments,
                                tool_call_id=tc.id,
                                allow_sensitive=True,
                            )
                        else:
                            err_msg = (
                                f"Authorization Block: Execution of tool '{tc.name}' was {auth_resp.decision.value}. "
                                f"Reason: {auth_resp.reason}"
                            )
                            result = ToolResult(
                                tool_call_id=tc.id,
                                name=tc.name,
                                content=err_msg,
                                is_error=True,
                                safety_level=tool.safety_level,
                            )

                all_tool_results.append(result)

                # Notify callback if registered (e.g. for CLI status display)
                if self.tool_callback:
                    try:
                        self.tool_callback(tc, result)
                    except Exception as cb_err:
                        logger.warning(f"Tool callback error: {cb_err}")

                # Persist tool execution result message to memory
                self.memory.add_message(
                    Message(
                        role=Role.TOOL,
                        name=tc.name,
                        content=result.content,
                        tool_call_id=tc.id,
                    )
                )

        # If iteration limit was hit without a final text response, synthesize from results
        if not final_content:
            if all_tool_results:
                logger.warning(f"Agent reached max iterations ({self.max_tool_iterations}). Summarizing executed tools.")
                summaries = "\n\n".join(r.content for r in all_tool_results)
                final_content = f"I completed the requested tool operations:\n\n{summaries}"
            else:
                final_content = "I reached my reasoning iteration limit before completing the response."

        # 5. Persist final assistant turn in conversation memory
        final_msg = Message(role=Role.ASSISTANT, content=final_content)
        self.memory.add_message(final_msg)

        duration = time.perf_counter() - start_time
        logger.info(f"Turn processed successfully in {duration:.2f}s across {iterations} iteration(s)")

        return AgentResponse(
            content=final_content,
            tool_calls=all_tool_calls if all_tool_calls else None,
            tool_results=all_tool_results if all_tool_results else None,
            is_done=True,
            metadata={
                "duration_seconds": duration,
                "iterations": iterations,
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
            "max_tool_iterations": self.max_tool_iterations,
            "tools_registered": [f"{t.name} ({t.safety_level.value})" for t in self.tools.list_tools()],
        }
