"""Result Synthesizer for FRIDAY Planning Architecture.

Inspired by Microsoft JARVIS / HuggingGPT Stage 4:
- Consolidates results from multiple specialist models, tools, and visual sensors.
- Eliminates raw JSON / tool syntax noise.
- Resolves conflicts across modalities to produce a coherent, natural, human-centric response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.planning.types import TaskGraph, TaskStatus

logger = get_logger("planning.synthesizer")

SYNTHESIS_SYSTEM_PROMPT = """You are FRIDAY's Result Synthesis Engine.
The user gave a complex goal, which was decomposed into subtasks and executed across specialist models and tools.
Your job is to synthesize all executed results into a clean, direct, coherent, and natural response for the user.

RULES:
1. Speak naturally as FRIDAY to the user.
2. Directly address the user's initial request using the verified task results.
3. If multiple tools or models produced complementary information, combine them seamlessly.
4. If a non-critical tool failed or was skipped, mention it gracefully only if relevant to the answer.
5. Do NOT dump raw JSON, internal Python dictionaries, or technical execution traces unless specifically asked.
6. Keep the response intelligent, concise, and structured.
"""


@dataclass
class SynthesizedResponse:
    """Consolidated answer produced by the ResultSynthesizer."""

    content: str
    goal: str
    graph_id: str
    is_successful: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    task_outputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "goal": self.goal,
            "graph_id": self.graph_id,
            "is_successful": self.is_successful,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "task_outputs": self.task_outputs,
        }


class ResultSynthesizer:
    """Integrates heterogeneous task outputs into a unified natural response."""

    def __init__(self, llm_provider: Any = None) -> None:
        self.llm = llm_provider

    def synthesize(self, graph: TaskGraph) -> SynthesizedResponse:
        """Synthesize the results of an executed TaskGraph."""
        tasks = graph.list_tasks()
        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]

        task_outputs = {}
        for t in tasks:
            if t.status == TaskStatus.COMPLETED:
                task_outputs[t.id] = {
                    "description": t.description,
                    "result": t.result,
                }
            elif t.status == TaskStatus.FAILED:
                task_outputs[t.id] = {
                    "description": t.description,
                    "error": t.error,
                }

        # 1. Attempt LLM-driven synthesis
        if self.llm and hasattr(self.llm, "generate") and completed:
            try:
                content = self._synthesize_with_llm(graph, completed, failed)
                if content:
                    return SynthesizedResponse(
                        content=content,
                        goal=graph.goal,
                        graph_id=graph.graph_id,
                        is_successful=graph.is_successful(),
                        total_tasks=len(tasks),
                        completed_tasks=len(completed),
                        failed_tasks=len(failed),
                        task_outputs=task_outputs,
                    )
            except Exception as e:
                logger.warning(f"LLM synthesis failed, falling back to deterministic synthesis: {e}")

        # 2. Deterministic Structured Fallback Synthesis
        content = self._synthesize_deterministically(graph, completed, failed)
        return SynthesizedResponse(
            content=content,
            goal=graph.goal,
            graph_id=graph.graph_id,
            is_successful=graph.is_successful(),
            total_tasks=len(tasks),
            completed_tasks=len(completed),
            failed_tasks=len(failed),
            task_outputs=task_outputs,
        )

    def _synthesize_with_llm(
        self,
        graph: TaskGraph,
        completed: list[Any],
        failed: list[Any],
    ) -> str | None:
        results_summary = []
        for t in completed:
            results_summary.append(f"Task '{t.description}' ({t.id}):\n{str(t.result)[:600]}")

        failures_summary = []
        for t in failed:
            failures_summary.append(f"Task '{t.description}' ({t.id}) failed: {t.error}")

        prompt = f"""USER GOAL: {graph.goal}

COMPLETED SUBTASK RESULTS:
{chr(10).join(results_summary)}

FAILED SUBTASKS:
{chr(10).join(failures_summary) if failures_summary else 'None'}

Synthesize the final answer for the user:"""

        messages = [
            Message(role=Role.SYSTEM, content=SYNTHESIS_SYSTEM_PROMPT),
            Message(role=Role.USER, content=prompt),
        ]
        resp = self.llm.generate(messages)
        return resp.content.strip() if resp and resp.content else None

    def _synthesize_deterministically(
        self,
        graph: TaskGraph,
        completed: list[Any],
        failed: list[Any],
    ) -> str:
        """Deterministic output aggregation when LLM is unavailable."""
        if not completed and failed:
            return f"I encountered an issue executing this request: {failed[0].error}"

        # If only 1 completed task, return its direct result
        if len(completed) == 1 and not failed:
            return str(completed[0].result)

        # Multi-task consolidation
        lines = [f"Goal completed: {graph.goal}"]
        for t in completed:
            res_str = str(t.result).strip()
            # If result is multiline, indent it
            if "\n" in res_str:
                lines.append(f"\n* {t.description}:")
                lines.append(f"  {res_str}")
            else:
                lines.append(f"* {t.description}: {res_str}")

        if failed:
            lines.append("\nNote: Some secondary subtasks could not be completed:")
            for t in failed:
                lines.append(f"- {t.description}: {t.error}")

        return "\n".join(lines)
