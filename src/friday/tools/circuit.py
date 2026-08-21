import time
from typing import Dict, Optional

class CircuitBreaker:
    """Simple circuit breaker per tool.
    Tracks consecutive failures; opens circuit after `max_failures` and resets after `reset_timeout` seconds.
    """

    def __init__(self, max_failures: int = 3, reset_timeout: int = 60):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        # state: {tool_name: (failure_count, opened_timestamp)}
        self._state: Dict[str, tuple[int, Optional[float]]] = {}

    def record_success(self, tool_name: str) -> None:
        self._state.pop(tool_name, None)

    def record_failure(self, tool_name: str) -> None:
        count, opened = self._state.get(tool_name, (0, None))
        count += 1
        if count >= self.max_failures:
            opened = time.time()
        self._state[tool_name] = (count, opened)

    def is_open(self, tool_name: str) -> bool:
        state = self._state.get(tool_name)
        if not state:
            return False
        count, opened = state
        if opened is None:
            return False
        # if reset timeout passed, reset
        if time.time() - opened >= self.reset_timeout:
            self._state.pop(tool_name, None)
            return False
        return True
