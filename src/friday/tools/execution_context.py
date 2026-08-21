from typing import Set, Optional

class ExecutionContext:
    """Carries request‑level data for tool orchestration.
    - retry_budget: total remaining retries for the whole request
    - seen_execution_ids: set of execution IDs already used (duplicate detection)
    - depth: current nested tool‑call depth (prevents infinite recursion)
    - circuit_breaker: shared CircuitBreaker instance for all tools in this request
    """

    def __init__(self, retry_budget: int = 10, max_depth: int = 5, circuit_breaker: Optional[object] = None):
        self.retry_budget: int = retry_budget
        self.max_depth: int = max_depth
        self.depth: int = 0
        self.seen_execution_ids: Set[str] = set()
        self.circuit_breaker = circuit_breaker

    def decrement_budget(self) -> bool:
        """Decrement the retry budget; return False if exhausted."""
        if self.retry_budget <= 0:
            return False
        self.retry_budget -= 1
        return True

    def increment_depth(self) -> bool:
        """Increase depth; return False if max depth exceeded."""
        self.depth += 1
        return self.depth <= self.max_depth

    def decrement_depth(self) -> None:
        self.depth = max(0, self.depth - 1)
