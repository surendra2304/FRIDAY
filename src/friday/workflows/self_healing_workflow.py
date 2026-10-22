from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from friday.agents.specialists.self_dev_agent import SelfDevAgent
from friday.core.logging import get_logger
from friday.tools.builtin.dev_tools import RunTestsTool
from friday.tools.registry import ToolRegistry
from friday.memory.base import BaseMemory
from friday.agents.base_agent import AgentTask

logger = get_logger("workflows.self_healing")


class SelfHealingWorkflow:
    """End-to-end workflow to resolve local code failures or fix requested issues using SelfDevAgent."""

    def __init__(
        self,
        self_dev_agent: SelfDevAgent | None = None,
        tool_registry: ToolRegistry | None = None,
        memory: BaseMemory | None = None,
    ) -> None:
        self.self_dev_agent = self_dev_agent
        self.tool_registry = tool_registry or ToolRegistry()
        self.memory = memory

    def can_handle(self, user_prompt: str) -> bool:
        """Check if user prompt matches a local self-fix / self-healing goal."""
        if not user_prompt:
            return False
        # Match phrases like "fix it", "fix yourself", "test yourself and fix it", "fix the error", "fix the code"
        # but not "fix issue #123" which is handled by dev_workflow
        pattern = r"\b(?:fix\s+it|fix\s+yourself|test\s+yourself|fix\s+(?:the\s+)?error|fix\s+(?:the\s+)?code)\b"
        if bool(re.search(r"\bissue\s*#?\d+\b", user_prompt, re.IGNORECASE)):
            return False
        return bool(re.search(pattern, user_prompt, re.IGNORECASE))

    async def execute_self_fix(
        self,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Orchestrate autonomous local resolution of a failure."""
        steps: list[str] = []
        logger.info(f"Initiating self-healing workflow for prompt: '{user_prompt}'")

        context_str = "No recent conversational context."
        if self.memory:
            recent_msgs = self.memory.get_context_window(max_messages=10)
            context_str = "\n".join([f"{m.role.value}: {m.content}" for m in recent_msgs])

        dev_output = ""
        if self.self_dev_agent:
            goal_str = f"The user asked to '{user_prompt}'. Review the recent conversation and logs to understand what failed. Then, edit the source code in the `src/friday` codebase to fix the issue. Run `run_tests` or other terminal commands to verify your fix. Ensure you are fixing the exact bug or feature requested."
            task = AgentTask(
                goal=goal_str,
                context={"recent_conversation": context_str},
            )
            task_res = await self.self_dev_agent.execute_task(task)
            dev_output = task_res.output
            steps.append(f"SelfDev Agent Fix Execution: {dev_output}")
        else:
            steps.append("SelfDev Agent Fix: SelfDevAgent not directly attached, unable to proceed.")
            return {
                "success": False,
                "steps_taken": steps,
                "error": "SelfDevAgent not available.",
                "summary": "SelfDevAgent is not available to execute the fix.",
            }

        return {
            "success": True,
            "steps_taken": steps,
            "summary": f"Autonomously attempted to fix the issue requested by '{user_prompt}'.\n\nResult:\n{dev_output}",
        }
