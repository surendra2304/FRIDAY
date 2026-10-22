"""Base Specialist Agent definition for FRIDAY Multi-Agent Specialist System.

Encapsulates an identity, role, scoped memory, allowed tools, and execution loop
utilizing the Unified Multi-Provider AI Gateway.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall, ToolResult
from friday.llm.base import BaseLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.registry import ToolRegistry

logger = get_logger("agents.base_agent")


@dataclass
class AgentTask:
    """Task specification dispatched to a specialist agent."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    subtask_index: int = 0
    total_subtasks: int = 1


@dataclass
class AgentTaskResult:
    """Outcome returned from a specialist agent's execution."""
    task_id: str
    agent_id: str
    role: str
    success: bool
    output: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """Identity and execution contract for specialist agents in FRIDAY."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        instructions: str,
        llm_provider: BaseLLMProvider,
        tool_registry: ToolRegistry | None = None,
        allowed_tools: list[str] | None = None,
        preferred_models: list[str] | None = None,
        memory_scope: str = "task",
        max_iterations: int = 5,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.instructions = instructions
        self.llm = llm_provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.allowed_tools = allowed_tools or []
        self.preferred_models = preferred_models or []
        self.memory_scope = memory_scope
        self.max_iterations = max_iterations
        self.memory = InMemoryConversationMemory()
        # Every agent gets a mind: a self-model, a capability ledger learned from
        # its own outcomes, and access to the fleet's shared episodic memory.
        from friday.cognition.mind import get_mind_registry

        self.mind = get_mind_registry().attach(self)

    def get_scoped_tool_schemas(self) -> list[dict[str, Any]] | None:
        """Return tool schemas filtered by allowed_tools if specified."""
        all_schemas = self.tool_registry.get_schemas()
        if not all_schemas:
            return None
        if not self.allowed_tools:
            return all_schemas
        allowed_set = set(self.allowed_tools)
        return [
            s for s in all_schemas
            if s.get("function", s).get("name") in allowed_set
        ]

    def to_agent_capability(self):
        """Export agent capability descriptor for ToolFirewall evaluation."""
        from friday_deep.contracts import AgentCapability
        return AgentCapability(
            agent_id=self.agent_id,
            role=self.role,
            allowed_tools=tuple(self.allowed_tools),
            preferred_models=tuple(self.preferred_models),
            max_parallel_tasks=1,
        )

    def run(self, goal: str, context: dict[str, Any] | None = None) -> AgentTaskResult:
        """Synchronously execute a task goal with the agent."""
        import asyncio
        task = AgentTask(goal=goal, context=context or {})
        if not self.llm:
            # Reporting success here would be a fabricated result: no model is
            # attached, so no reasoning and no tool loop ever ran.
            self.mind.finish(goal, success=False, capability=f"{self.role}.no_model", output="no model attached")
            return AgentTaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                role=self.role,
                success=False,
                output=(
                    f"No model is attached to agent '{self.agent_id}', so the task was not "
                    "attempted. Attach an LLM provider and retry."
                ),
                metadata={"error": "no_llm_provider", "attempted": False},
            )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self.execute_task(task)).result()
            return loop.run_until_complete(self.execute_task(task))
        except RuntimeError:
            return asyncio.run(self.execute_task(task))

    async def execute_task(self, task: AgentTask) -> AgentTaskResult:

        """Execute assigned subtask using LLM reasoning and scoped tool execution."""
        logger.info(f"Agent [{self.role} ({self.agent_id})] starting task: {task.goal}")
        
        # Fresh working memory per task if task-scoped
        if self.memory_scope == "task":
            self.memory.clear()

        prior = self._recall_prior_experience(task.goal)
        system_prompt = (
            f"You are the specialist agent '{self.role}' (ID: {self.agent_id}) in FRIDAY.\n"
            f"Role Instructions: {self.instructions}\n"
            f"Current Goal: {task.goal}\n"
            f"Context: {task.context}\n"
            + (f"Relevant prior experience (from shared memory):\n{prior}\n" if prior else "")
            + "Perform the task efficiently and return a direct, concise outcome."
        )
        
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=task.goal),
        ]
        for m in messages:
            self.memory.add_message(m)

        tool_schemas = self.get_scoped_tool_schemas()
        executed_calls: list[ToolCall] = []
        executed_results: list[ToolResult] = []
        iterations = 0
        final_output = ""
        success = False
        terminal_error = None

        while iterations < self.max_iterations:
            iterations += 1
            context_window = self.memory.get_context_window(20)
            
            try:
                assistant_msg = self.llm.generate(messages=context_window, tools=tool_schemas)
            except Exception as e:
                logger.error(f"Agent [{self.role}] generation failed: {e}")
                self.mind.finish(
                    task.goal,
                    success=False,
                    capability=f"{self.role}.generate",
                    output=f"{type(e).__name__}: {e}",
                )
                return AgentTaskResult(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    role=self.role,
                    success=False,
                    output=f"Error executing agent task: {e}",
                    tool_calls=executed_calls,
                    tool_results=executed_results,
                    metadata={"iterations": iterations, "error": str(e)},
                )

            self.memory.add_message(assistant_msg)

            if not assistant_msg.tool_calls:
                final_output = assistant_msg.content or "Completed."
                # Success is only granted if the LLM finishes without unrecovered errors
                success = not bool(terminal_error)
                break

            for tc in assistant_msg.tool_calls:
                executed_calls.append(tc)
                if self.allowed_tools and tc.name not in self.allowed_tools:
                    res = ToolResult(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=f"Tool '{tc.name}' not allowed for agent role '{self.role}'.",
                        is_error=True,
                    )
                else:
                    try:
                        from friday.tools.execution_context import ExecutionContext
                        exec_ctx = ExecutionContext()
                        exec_ctx.agent_capability = self.to_agent_capability()
                        res = self.tool_registry.execute(
                            name=tc.name,
                            arguments=tc.arguments,
                            tool_call_id=tc.id,
                            exec_context=exec_ctx,
                        )
                    except Exception as te:
                        res = ToolResult(
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=f"Tool execution failed: {te}",
                            is_error=True,
                        )

                executed_results.append(res)
                if res.is_error:
                    terminal_error = res.content
                else:
                    # Clear previous errors if the agent successfully uses a tool to recover
                    terminal_error = None

                self.memory.add_message(
                    Message(
                        role=Role.TOOL,
                        content=res.content,
                        tool_call_id=res.tool_call_id,
                        name=res.name,
                    )
                )

        if not final_output and iterations >= self.max_iterations:
            success = False
            terminal_error = terminal_error or f"Agent reached iteration limit ({self.max_iterations})."
            final_output = terminal_error

        self.mind.finish(
            task.goal,
            success=success,
            output=final_output if success else (terminal_error or final_output),
            tool_calls=[call.name for call in executed_calls],
        )

        return AgentTaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            role=self.role,
            success=success,
            output=final_output if success else (terminal_error or final_output),
            tool_calls=executed_calls,
            tool_results=executed_results,
            metadata={"iterations": iterations},
        )

    def _recall_prior_experience(self, goal: str, limit: int = 3) -> str:
        """What this agent — or any other — already learned about a goal like this.

        Recall failures must never break a task: a memory that is unavailable is
        reported as absent, not raised.
        """
        try:
            hits = self.mind.recall(goal, limit=limit)
        except Exception as exc:
            logger.warning("shared recall failed for agent %s: %s", self.agent_id, exc)
            return ""
        if not hits:
            return ""
        lines = []
        for hit in hits:
            episode = hit.episode
            verdict = "worked" if episode.success is True else "failed" if episode.success is False else "unknown"
            lines.append(f"- ({episode.agent}/{verdict}) {episode.summary} [{hit.why}]")
        return "\n".join(lines)

    def close(self) -> None:
        """Clean up working memory and agent resources."""
        if hasattr(self, "memory") and hasattr(self.memory, "clear"):
            try:
                self.memory.clear()
            except Exception:
                pass
