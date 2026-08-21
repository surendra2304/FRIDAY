from dataclasses import dataclass
from typing import Optional

@dataclass
class ToolErrorDetail:
    code: str
    message: str
    tool_name: str
    execution_id: str
    # optional additional data
    data: Optional[dict] = None

class ToolTimeoutError(ToolErrorDetail):
    def __init__(self, tool_name: str, execution_id: str, timeout: int):
        super().__init__(
            code="TIMEOUT",
            message=f"Tool '{tool_name}' execution exceeded timeout of {timeout}s.",
            tool_name=tool_name,
            execution_id=execution_id,
        )

class CircuitBreakerError(ToolErrorDetail):
    def __init__(self, tool_name: str, execution_id: str):
        super().__init__(
            code="CIRCUIT_BREAKER",
            message=f"Circuit breaker open for tool '{tool_name}'. Execution blocked.",
            tool_name=tool_name,
            execution_id=execution_id,
        )
