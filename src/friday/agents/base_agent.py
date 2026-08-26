# -*- coding: utf-8 -*-
"""Base Specialist Agent definition for FRIDAY Multi-Agent Specialist System.

Encapsulates an identity, role, scoped memory, allowed tools, and execution loop
utilizing the Unified Multi-Provider AI Gateway.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import uuid

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
    context: Dict[str, Any] = field(default_factory=dict)
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
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """Identity and execution contract for specialist agents in FRIDAY."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        instructions: str,
        llm_provider: BaseLLMProvider,
        tool_registry: Optional[ToolRegistry] = None,
        allowed_tools: Optional[List[str]] = None,
        preferred_models: Optional[List[str]] = None,
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

    def get_scoped_tool_schemas(self) -> Optional[List[Dict[str, Any]]]:
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

    async def execute_task(self, task: AgentTask) -> AgentTaskResult:
        """Execute assigned subtask using LLM reasoning and scoped tool execution."""
        logger.info(f"Agent [{self.role} ({self.agent_id})] starting task: {task.goal}")
        
        # Fresh working memory per task if task-scoped
        if self.memory_scope == "task":
            self.memory.clear()

        system_prompt = (
            f"You are the specialist agent '{self.role}' (ID: {self.agent_id}) in FRIDAY.\n"
            f"Role Instructions: {self.instructions}\n"
            f"Current Goal: {task.goal}\n"
            f"Context: {task.context}\n"
            f"Perform the task efficiently and return a direct, concise outcome."
        )
        
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=task.goal),
        ]
        for m in messages:
            self.memory.add_message(m)

        tool_schemas = self.get_scoped_tool_schemas()
        executed_calls: List[ToolCall] = []
        executed_results: List[ToolResult] = []
        iterations = 0
        final_output = ""
        success = True

        while iterations < self.max_iterations:
            iterations += 1
            context_window = self.memory.get_context_window(20)
            
            try:
                assistant_msg = self.llm.generate(messages=context_window, tools=tool_schemas)
            except Exception as e:
                logger.error(f"Agent [{self.role}] generation failed: {e}")
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
                        res = self.tool_registry.execute(
                            name=tc.name,
                            arguments=tc.arguments,
                            tool_call_id=tc.id,
                        )
                    except Exception as te:
                        res = ToolResult(
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=f"Tool execution failed: {te}",
                            is_error=True,
                        )

                executed_results.append(res)
                self.memory.add_message(
                    Message(
                        role=Role.TOOL,
                        content=res.content,
                        tool_call_id=res.tool_call_id,
                        name=res.name,
                    )
                )

        if not final_output and iterations >= self.max_iterations:
            final_output = f"Agent reached iteration limit ({self.max_iterations})."

        return AgentTaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            role=self.role,
            success=success,
            output=final_output,
            tool_calls=executed_calls,
            tool_results=executed_results,
            metadata={"iterations": iterations},
        )

    def close(self) -> None:
        """Clean up working memory and agent resources."""
        if hasattr(self, "memory") and hasattr(self.memory, "clear"):
            try:
                self.memory.clear()
            except Exception:
                pass
