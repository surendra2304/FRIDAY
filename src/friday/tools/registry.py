"""Tool Registry for tool registration, discovery, schema export, validation, and execution."""

from typing import Any, Dict, List, Optional
import uuid
import asyncio
from friday.core.exceptions import ToolError
from friday.core.logging import get_logger, redact_tool_args
from friday.core.types import SafetyLevel, ToolResult
from .errors import ToolErrorDetail, ToolTimeoutError, CircuitBreakerError
from .circuit import CircuitBreaker
from .execution_context import ExecutionContext
from friday.tools.base import BaseTool
from friday.security.authorization import ToolAuthorizer, ToolAuthorizationCapability, tool_authorizer

logger = get_logger("tools.registry")


class ToolRegistry:
    """Central registry for managing agent tools and enforcing safety policies."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self._thread_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="friday-tool-worker")
        self._timed_out_executions = set()
        self._timed_out_lock = threading.Lock()

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        if not tool.name:
            raise ToolError("Cannot register tool without a valid name")
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool registration: '{tool.name}'")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: '{tool.name}' [Safety: {tool.safety_level.value}]")

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_schemas(self, max_safety: Optional[SafetyLevel] = None) -> List[Dict[str, Any]]:
        """Export OpenAI-compatible schemas for all registered tools.

        Optionally filters tools by maximum safety tolerance.
        """
        schemas = []
        safety_order = {
            SafetyLevel.SAFE: 0,
            SafetyLevel.SENSITIVE: 1,
            SafetyLevel.DANGEROUS: 2,
        }
        
        for tool in self._tools.values():
            if max_safety:
                tool_val = safety_order.get(tool.safety_level, 0)
                max_val = safety_order.get(max_safety, 2)
                if tool_val > max_val:
                    continue
            schemas.append(tool.to_openai_schema())
        return schemas

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str = "",
        authorization: Optional[ToolAuthorizationCapability] = None,
        exec_context: Optional[ExecutionContext] = None,
        authorizer: Optional[ToolAuthorizer] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Validate and execute a tool by name with cryptographic authorization checks.

        Args:
            name: Tool name.
            arguments: Dictionary of arguments.
            tool_call_id: Associated LLM tool call ID.
            authorization: Signed ToolAuthorizationCapability granting execution rights.
            exec_context: Optional execution context for circuit breaker.
            authorizer: Optional custom ToolAuthorizer instance.

        Returns:
            ToolResult containing execution status and output.
        """
        tool = self.get(name)
        if not tool:
            err_msg = f"Error: Tool '{name}' is not registered or available in FRIDAY's tool registry."
            logger.error(err_msg)
            # Structured error
            exec_id = tool_call_id or str(uuid.uuid4())
            error_detail = ToolErrorDetail(
                code="UNKNOWN_TOOL",
                message=err_msg,
                tool_name=name,
                execution_id=exec_id,
            )
            return ToolResult(
                tool_call_id=exec_id,
                name=name,
                content=error_detail.message,
                is_error=True,
                safety_level=SafetyLevel.SAFE,
                error_detail=error_detail,
            )

        # Validate arguments against parameter schema
        is_valid, validation_err = tool.validate_arguments(arguments)
        if not is_valid:
            err_msg = f"Invalid arguments for tool '{name}': {validation_err}"
            logger.warning(err_msg)
            exec_id = tool_call_id or str(uuid.uuid4())
            error_detail = ToolErrorDetail(
                code="INVALID_ARGUMENTS",
                message=err_msg,
                tool_name=name,
                execution_id=exec_id,
                data={"validation_error": validation_err},
            )
            return ToolResult(
                tool_call_id=exec_id,
                name=name,
                content=error_detail.message,
                is_error=True,
                safety_level=tool.safety_level,
                error_detail=error_detail,
            )

        # Check safety permissions via cryptographic ToolAuthorizationCapability
        if tool.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS):
            active_authz = authorizer or tool_authorizer
            is_authorized, auth_reason = active_authz.verify_and_consume(
                capability=authorization,
                tool_name=name,
                arguments=arguments,
                tool_call_id=tool_call_id,
            )
            if not is_authorized:
                err_msg = (
                    f"Safety Block: Tool '{name}' is classified as '{tool.safety_level.value}' "
                    f"and requires a valid ToolAuthorizationCapability. Denied: {auth_reason}"
                )
                logger.warning(err_msg)
                exec_id = tool_call_id or str(uuid.uuid4())
                error_detail = ToolErrorDetail(
                    code="SAFETY_BLOCK",
                    message=err_msg,
                    tool_name=name,
                    execution_id=exec_id,
                    data={"authorization_denied_reason": auth_reason},
                )
                return ToolResult(
                    tool_call_id=exec_id,
                    name=name,
                    content=error_detail.message,
                    is_error=True,
                    safety_level=tool.safety_level,
                    error_detail=error_detail,
                )

        try:
            # Circuit breaker check
            cb = exec_context.circuit_breaker if exec_context else CircuitBreaker()
            if cb.is_open(name):
                exec_id = tool_call_id or str(uuid.uuid4())
                error_detail = CircuitBreakerError(name, exec_id)
                logger.warning(error_detail.message)
                return ToolResult(
                    tool_call_id=exec_id,
                    name=name,
                    content=error_detail.message,
                    is_error=True,
                    safety_level=tool.safety_level,
                    error_detail=error_detail,
                )

            # Prepare execution ID
            exec_id = tool_call_id or str(uuid.uuid4())

            # Filter out optional parameters with None values so Python defaults are used
            required_fields = tool.parameters.get("required", [])
            exec_args = {
                k: v for k, v in arguments.items()
                if v is not None or k in required_fields
            }
            logger.info(
                "Executing tool '%s' [Safety: %s, arg_count: %d, args_meta: %s]",
                name,
                tool.safety_level.value,
                len(exec_args),
                redact_tool_args(exec_args),
            )

            # Timeout handling (async if tool.execute is coroutine)
            timeout_seconds = kwargs.get("timeout") or getattr(tool, "timeout", 30)
            import inspect
            import threading
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            cancel_event = threading.Event()
            sig = inspect.signature(tool.execute)
            if "cancellation_token" in sig.parameters:
                exec_args["cancellation_token"] = cancel_event
            elif "cancel_event" in sig.parameters:
                exec_args["cancel_event"] = cancel_event

            try:
                if asyncio.iscoroutinefunction(tool.execute):
                    # Run async tool with timeout
                    result = asyncio.run(asyncio.wait_for(tool.execute(**exec_args), timeout=timeout_seconds))
                else:
                    # Run sync tool using the shared thread executor (so we don't wait for worker shutdown!)
                    future = self._thread_executor.submit(tool.execute, **exec_args)
                    result = future.result(timeout=timeout_seconds)
            except (asyncio.TimeoutError, FuturesTimeoutError, TimeoutError):
                cancel_event.set()
                with self._timed_out_lock:
                    self._timed_out_executions.add(exec_id)
                error_detail = ToolTimeoutError(name, exec_id, timeout_seconds)
                logger.error(error_detail.message)
                cb.record_failure(name)
                return ToolResult(
                    tool_call_id=exec_id,
                    name=name,
                    content=error_detail.message,
                    is_error=True,
                    safety_level=tool.safety_level,
                    error_detail=error_detail,
                )

            # Record success for circuit breaker
            cb.record_success(name)

            # Attach execution ID to result
            result.tool_call_id = exec_id

            # Verification method if supplied
            if getattr(tool, "verification_method", None):
                try:
                    verified = tool.verification_method(result)
                    if not verified:
                        err_msg = f"Verification failed for tool '{name}'."
                        logger.warning(err_msg)
                        error_detail = ToolErrorDetail(
                            code="VERIFICATION_FAILED",
                            message=err_msg,
                            tool_name=name,
                            execution_id=exec_id,
                        )
                        return ToolResult(
                            tool_call_id=exec_id,
                            name=name,
                            content=err_msg,
                            is_error=True,
                            safety_level=tool.safety_level,
                            error_detail=error_detail,
                        )
                except Exception as ve:
                    logger.exception(f"Verification method error for tool '{name}': {ve}")

            return result
        except Exception as e:
            logger.exception(f"Exception during tool '{name}' execution: {e}")
            exec_id = tool_call_id or str(uuid.uuid4())
            error_detail = ToolErrorDetail(
                code="EXECUTION_ERROR",
                message=str(e),
                tool_name=name,
                execution_id=exec_id,
            )
            return ToolResult(
                tool_call_id=exec_id,
                name=name,
                content=f"Tool execution encountered an internal error: {str(e)}",
                is_error=True,
                safety_level=tool.safety_level,
                error_detail=error_detail,
            )
