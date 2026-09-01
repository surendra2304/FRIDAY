"""Verification test suite for hardened tool execution timeouts and cancellation."""

import threading
import time

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class IntentionallyBlockingTool(BaseTool):
    name = "intentionally_blocking"
    description = "Tool that sleeps indefinitely to simulate a hung operations"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}
    timeout = 0.5  # 0.5s timeout

    def execute(self, **kwargs) -> ToolResult:
        # Sleep for 5 seconds (simulates a block)
        time.sleep(5.0)
        return ToolResult(
            name=self.name,
            content="Execution finished after delay",
            is_error=False,
            safety_level=self.safety_level,
        )


class CooperativeCancellationBlockingTool(BaseTool):
    name = "cooperative_cancel_blocking"
    description = "Tool that checks cancellation_token to stop work cooperatively"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}
    timeout = 0.5

    def __init__(self):
        super().__init__()
        self.was_cancelled = False

    def execute(self, cancellation_token: threading.Event, **kwargs) -> ToolResult:
        for _ in range(50):
            if cancellation_token.is_set():
                self.was_cancelled = True
                return ToolResult(
                    name=self.name,
                    content="Cooperatively cancelled",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            time.sleep(0.1)

        return ToolResult(
            name=self.name,
            content="Finished complete work loop",
            is_error=False,
            safety_level=self.safety_level,
        )


def test_timeout_returns_immediately_without_waiting_for_thread():
    """Verify that a timed-out operation does not block execution until thread exits."""
    registry = ToolRegistry()
    tool = IntentionallyBlockingTool()
    registry.register(tool)

    start = time.perf_counter()
    result = registry.execute("intentionally_blocking", {})
    elapsed = time.perf_counter() - start

    # It must return immediately around the 0.5s timeout limit, not wait for the 5.0s sleep to finish
    assert result.is_error is True
    assert "timeout" in result.content.lower()
    assert elapsed < 2.0, f"Apparent timeout blocked: took {elapsed:.2f} seconds"


def test_cooperative_cancellation_notifies_tool():
    """Verify that a tool supporting cancellation_token receives the cancellation signal on timeout."""
    registry = ToolRegistry()
    tool = CooperativeCancellationBlockingTool()
    registry.register(tool)

    start = time.perf_counter()
    result = registry.execute("cooperative_cancel_blocking", {})
    elapsed = time.perf_counter() - start

    assert result.is_error is True
    assert "timeout" in result.content.lower()
    assert elapsed < 2.0

    # Wait another 0.5 seconds to give the background thread time to notice and exit
    time.sleep(0.5)
    assert tool.was_cancelled is True
