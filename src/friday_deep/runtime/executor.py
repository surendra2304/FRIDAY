from __future__ import annotations
import time
from dataclasses import dataclass
from ..contracts import ExecutionResult, Status
from .budget import Budget, BudgetExceeded
from .dedupe import DuplicateCallGuard


@dataclass
class RuntimeHooks:
    started: object | None = None
    finished: object | None = None
    budget_exhausted: object | None = None


class AgentRuntime:
    def __init__(self, max_steps=64, max_tools=128, max_failures=8, max_seconds=900, duplicate_limit=2):
        self.budget = Budget(max_steps, max_tools, max_failures, max_seconds)
        self.dupes = DuplicateCallGuard(duplicate_limit)

    def run(self, task_id, agent_id, iteration):
        start = time.monotonic()
        self.budget.start()
        output = ""
        try:
            while True:
                self.budget.step()
                done, output = iteration(self.budget.steps, self.dupes, self.budget)
                if done:
                    return ExecutionResult(
                        task_id,
                        agent_id,
                        Status.SUCCEEDED,
                        output,
                        iterations=self.budget.steps,
                        elapsed_seconds=time.monotonic() - start,
                    )
        except BudgetExceeded as e:
            return ExecutionResult(
                task_id,
                agent_id,
                Status.INCOMPLETE,
                output,
                "BUDGET_EXHAUSTED",
                str(e),
                self.budget.steps,
                self.budget.tools,
                time.monotonic() - start,
            )
        except Exception as e:
            return ExecutionResult(
                task_id,
                agent_id,
                Status.FAILED,
                output,
                type(e).__name__,
                str(e),
                self.budget.steps,
                self.budget.tools,
                time.monotonic() - start,
            )
