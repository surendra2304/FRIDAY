"""mini-SWE-Agent Bridge for FRIDAY.

Connects to MiniSWEAgentExecutor and CodingWorkspaceGuard, providing bounded
software engineering capabilities under strict directory containment.
"""

from __future__ import annotations

from typing import Any

from friday.integrations.mini_swe.executor import MiniSWEAgentExecutor
from friday.integrations.mini_swe.safety import CodingWorkspaceGuard


class MiniSWEAgentBridge:
    """Bridge for software engineering execution."""

    def __init__(self, allowed_roots: list[str] | None = None, timeout: int = 300) -> None:
        self.executor = MiniSWEAgentExecutor(allowed_roots=allowed_roots, timeout_seconds=float(timeout))

    @property
    def available(self) -> bool:
        return self.executor.is_cli_available

    def run(self, task: str, workdir: str | None = None) -> dict[str, Any]:
        res = self.executor.execute({"task_type": "diagnose", "task": task, "workdir": workdir})
        return {
            "success": res.success,
            "output": res.output,
            "error": res.error,
            "metadata": res.metadata,
        }
