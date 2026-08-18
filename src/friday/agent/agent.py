"""Core Agent orchestration loop with multi-step sequential tool calling for FRIDAY."""

import time
from typing import Any, Callable, Dict, List, Optional
from friday.agent.prompts import build_system_message
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from datetime import datetime
from friday.core.types import (
    AgentResponse,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    MemorySearchResult,
    Message,
    Role,
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.llm.base import BaseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.memory.base import BaseMemory
from friday.memory.factory import create_memory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.builtin import (
    SystemInfoTool,
    TimeDateTool,
    CalculatorTool,
    FileReaderTool,
    FileListingTool,
    MemorySearchTool,
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
        tool_timeout: float = 30.0,
        conversation_id: Optional[str] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm_provider or create_llm_provider(self.settings)
        self.memory = memory or create_memory(self.settings, conversation_id=conversation_id)
        self.tools = tool_registry or self._create_default_registry()
        self.max_tool_iterations = max(1, max_tool_iterations)
        self.tool_callback = tool_callback
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.tool_timeout = tool_timeout
        self.system_message = build_system_message(self.settings)

        logger.info(
            f"Initialized {self.settings.agent_name} with provider '{self.llm.provider_name}' "
            f"(model: '{self.llm.model}') and {len(self.tools.list_tools())} loaded tools. "
            f"Max tool iterations: {self.max_tool_iterations}."
        )

    @property
    def conversation_id(self) -> Optional[str]:
        """Return the active conversation identifier if supported by the memory backend."""
        if hasattr(self.memory, "active_conversation_id"):
            return self.memory.active_conversation_id
        return None

    def switch_conversation(self, conversation_id: str) -> None:
        """Switch the active conversation session."""
        self.memory.load_conversation(conversation_id)

    def create_new_conversation(self, title: Optional[str] = None) -> Optional[str]:
        """Create and activate a new conversation session."""
        return self.memory.create_conversation(title=title)

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List available conversation sessions."""
        return self.memory.list_conversations(limit=limit)

    def get_current_conversation(self) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for the current active conversation."""
        if self.conversation_id:
            return self.memory.get_conversation(self.conversation_id)
        return None

    def rename_conversation(self, new_title: str, conversation_id: Optional[str] = None) -> bool:
        """Rename an existing conversation."""
        target_id = conversation_id or self.conversation_id
        if target_id:
            return self.memory.rename_conversation(target_id, new_title)
        return False

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation session and all its messages."""
        return self.memory.delete_conversation(conversation_id)

    def search_memory(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MemorySearchResult]:
        """Search historical conversation messages."""
        return self.memory.search(
            query=query,
            conversation_id=conversation_id,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )

    def _create_default_registry(self) -> ToolRegistry:
        """Instantiate default tool registry with built-in safe tools."""
        registry = ToolRegistry()
        registry.register(SystemInfoTool())
        registry.register(TimeDateTool())
        registry.register(CalculatorTool())
        registry.register(FileReaderTool())
        registry.register(FileListingTool())
        registry.register(MemorySearchTool(self.memory))
        return registry

    def _execute_single_tool_call_internal(self, tc: ToolCall, allow_sensitive: bool) -> ToolResult:
        """Validate, authorize, and execute a single tool call request internally."""
        tool = self.tools.get(tc.name)
        if not tool:
            err_msg = f"Error: Tool '{tc.name}' is not registered or available in FRIDAY's tool registry."
            logger.warning(err_msg)
            return ToolResult(
                tool_call_id=tc.id,
                name=tc.name,
                content=err_msg,
                is_error=True,
                safety_level=SafetyLevel.SAFE,
            )

        # 1. Validation happens BEFORE authorization request
        is_valid, validation_err = tool.validate_arguments(tc.arguments)
        if not is_valid:
            err_msg = f"Invalid arguments for tool '{tc.name}': {validation_err}"
            logger.warning(err_msg)
            return ToolResult(
                tool_call_id=tc.id,
                name=tc.name,
                content=err_msg,
                is_error=True,
                safety_level=tool.safety_level,
            )

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

        # 3. Handle authorization check (legacy allow_sensitive and SAFE tools auto-approve)
        if tool.safety_level == SafetyLevel.SAFE:
            auth_resp = AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
            )
        elif allow_sensitive:
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
            return self.tools.execute(
                name=tc.name,
                arguments=tc.arguments,
                tool_call_id=tc.id,
                allow_sensitive=True,
            )
        
        err_msg = (
            f"Authorization Block: Execution of tool '{tc.name}' was {auth_resp.decision.value}. "
            f"Reason: {auth_resp.reason}"
        )
        return ToolResult(
            tool_call_id=tc.id,
            name=tc.name,
            content=err_msg,
            is_error=True,
            safety_level=tool.safety_level,
        )

    def _execute_single_tool_call(self, tc: ToolCall, allow_sensitive: bool) -> ToolResult:
        """Validate, authorize, and execute a single tool call request with duration logging."""
        tool_start = time.perf_counter()
        result = self._execute_single_tool_call_internal(tc, allow_sensitive)
        tool_duration = time.perf_counter() - tool_start
        logger.info(
            f"Tool '{tc.name}' execution completed in {tool_duration:.4f}s "
            f"(Success: {not result.is_error})"
        )
        return result

    def _execute_single_tool_call_with_timeout(
        self, tc: ToolCall, allow_sensitive: bool, timeout: float = 30.0
    ) -> ToolResult:
        """Execute a single tool call wrapped inside a thread executor to enforce a strict timeout."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._execute_single_tool_call, tc, allow_sensitive)
            try:
                return future.result(timeout=timeout)
            except TimeoutError:
                logger.error(f"Tool '{tc.name}' execution timed out (limit: {timeout}s)")
                return ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=f"Error: Tool execution timed out after {timeout} seconds.",
                    is_error=True,
                    safety_level=SafetyLevel.SAFE,
                )

    def process_message(
        self,
        user_input: str,
        allow_sensitive: bool = False,
    ) -> AgentResponse:
        """Process a user message through reasoning, safety validation, and sequential/parallel tool execution."""
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
                
                # User friendly translated error messages
                err_text = "I encountered a transient network issue while communicating with my intelligence core. Please try again in a moment."
                err_str = str(e).lower()
                if "rate limit" in err_str or "status 429" in err_str:
                    err_text = "My intelligence core is currently experiencing high demand. Please hold on a moment and try again."
                elif "authentication" in err_str or "api key" in err_str or "status 401" in err_str or "status 403" in err_str:
                    err_text = "I'm unable to authenticate with my intelligence core. Please verify your API key settings."
                elif "connection" in err_str or "timeout" in err_str or "dns" in err_str:
                    err_text = "I'm having trouble connecting to my intelligence core. Please check your internet connection and try again."
                
                self.memory.add_message(Message(role=Role.ASSISTANT, content=err_text))
                return AgentResponse(
                    content=err_text,
                    is_done=True,
                    metadata={
                        "error": str(e),
                        "iterations": iterations,
                        "success": False,
                        "duration_seconds": time.perf_counter() - start_time,
                    },
                )

            # If model returned direct answer without requesting tools -> finished turn
            if not assistant_msg.tool_calls:
                final_content = assistant_msg.content or "Task completed."
                break

            # Model requested one or more tool calls
            logger.info(f"Iteration {iterations}: Model requested {len(assistant_msg.tool_calls)} tool call(s)")
            
            # Persist assistant's tool call intent message to memory
            self.memory.add_message(assistant_msg)

            # Safety level classification check: determine if all tool calls are SAFE
            all_safe = True
            for tc in assistant_msg.tool_calls:
                tool = self.tools.get(tc.name)
                # If tool doesn't exist, we class as SAFE for routing (rejection happens early in execute method)
                if tool and tool.safety_level != SafetyLevel.SAFE:
                    all_safe = False
                    break

            batch_results: List[ToolResult] = []
            batch_start = time.perf_counter()
            tool_timeout = self.tool_timeout

            if all_safe and len(assistant_msg.tool_calls) > 1:
                # SAFE independent tools -> Parallel execution supported safely with timeout boundaries
                logger.info(f"Coordinated execution: Executing {len(assistant_msg.tool_calls)} SAFE tools in parallel.")
                from concurrent.futures import ThreadPoolExecutor, TimeoutError
                with ThreadPoolExecutor(max_workers=len(assistant_msg.tool_calls)) as executor:
                    futures = [
                        executor.submit(self._execute_single_tool_call, tc, allow_sensitive)
                        for tc in assistant_msg.tool_calls
                    ]
                    for fut, tc in zip(futures, assistant_msg.tool_calls):
                        try:
                            res = fut.result(timeout=tool_timeout)
                            batch_results.append(res)
                        except TimeoutError:
                            logger.error(f"Tool '{tc.name}' execution timed out (limit: {tool_timeout}s)")
                            batch_results.append(
                                ToolResult(
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                    content=f"Error: Tool execution timed out after {tool_timeout} seconds.",
                                    is_error=True,
                                    safety_level=SafetyLevel.SAFE,
                                )
                            )
                latency = time.perf_counter() - batch_start
                logger.info(f"Coordinated parallel execution completed in {latency:.4f}s.")
            else:
                # Mixed or SENSITIVE/DANGEROUS tools -> Sequential ordering and auth semantics preserved
                logger.info(f"Coordinated execution: Executing {len(assistant_msg.tool_calls)} tools sequentially.")
                for tc in assistant_msg.tool_calls:
                    res = self._execute_single_tool_call_with_timeout(tc, allow_sensitive, timeout=tool_timeout)
                    batch_results.append(res)
                latency = time.perf_counter() - batch_start
                logger.info(f"Coordinated sequential execution completed in {latency:.4f}s.")

            # Process batch results in the exact requested order
            for tc, result in zip(assistant_msg.tool_calls, batch_results):
                all_tool_calls.append(tc)
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
                "tools_used": list(set(tc.name for tc in all_tool_calls)),
                "success": all(not r.is_error for r in all_tool_results) if all_tool_results else True,
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
        status = {
            "agent_name": self.settings.agent_name,
            "user_name": self.settings.user_name,
            "provider": self.llm.provider_name,
            "model": self.llm.model,
            "memory_backend": self.settings.memory_backend,
            "memory_messages": len(self.memory.get_messages()),
            "memory_capacity": self.settings.memory_max_messages,
            "max_tool_iterations": self.max_tool_iterations,
            "tools_registered": [f"{t.name} ({t.safety_level.value})" for t in self.tools.list_tools()],
        }
        if self.conversation_id:
            status["conversation_id"] = self.conversation_id
        return status
