"""Dynamic Re-planner & Failure Recovery for FRIDAY Planning Architecture.

Inspired by Microsoft JARVIS / HuggingGPT Fault Tolerance & Dynamic Replanning:
- Diagnoses failed subtasks (timeout, model unavailable, unparseable output, parameter error).
- Dispatches multi-tiered recovery:
  Tier 1: Bounded retry with exponential backoff (handled by Scheduler).
  Tier 2: Immediate fallback executor execution (e.g. vision model down -> local OCR).
  Tier 3: Dynamic subgraph replacement via LLM or deterministic rules.
  Tier 4: Graceful partial completion without terminating unaffected branches.
- Strict Invariant: Recovery never bypasses BaseAuthorizer safety boundaries.
"""

from __future__ import annotations

import json
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.planning.events import (
    TaskEventType,
    TaskProgressEvent,
    global_task_event_bus,
)
from friday.planning.executors import ExecutorRegistry
from friday.planning.types import (
    TaskDataType,
    TaskGraph,
    TaskStatus,
    TaskStep,
)

logger = get_logger("planning.replanner")


class DynamicReplanner:
    """Intelligently repairs, substitutes, or replans failing tasks during execution."""

    def __init__(
        self,
        executor_registry: ExecutorRegistry,
        llm_provider: Any = None,
        event_bus: Any = None,
    ) -> None:
        self.registry = executor_registry
        self.llm = llm_provider
        self.event_bus = event_bus or global_task_event_bus

    def handle_task_failure(
        self,
        task: TaskStep,
        graph: TaskGraph,
        error_message: str,
        registry: ExecutorRegistry,
    ) -> bool:
        """Attempt to recover from a task failure. Returns True if recovered, False otherwise."""
        logger.info(f"DynamicReplanner diagnosing failure in task '{task.id}': {error_message}")

        # 1. Tier 2 Recovery: Try Fallback Executors
        if task.fallback_executors:
            for fallback_name in task.fallback_executors:
                fallback_exc = registry.get(fallback_name)
                if fallback_exc and fallback_name != task.selected_executor:
                    logger.info(f"Attempting fallback executor '{fallback_name}' for task '{task.id}'...")
                    try:
                        resolved_inputs = graph.resolve_inputs_for_task(task.id)
                        res = fallback_exc.execute(resolved_inputs)
                        if res.success:
                            logger.info(f"Task '{task.id}' recovered successfully using fallback executor '{fallback_name}'.")
                            graph.mark_completed(task.id, result=res.output, outputs={"result": res.output})
                            task.selected_executor = fallback_name
                            task.metadata["recovered_by_fallback"] = fallback_name
                            self.event_bus.publish(
                                TaskProgressEvent(
                                    event_type=TaskEventType.EXECUTION_REPLANNED,
                                    graph_id=graph.graph_id,
                                    task_id=task.id,
                                    message=f"Recovered task using fallback executor '{fallback_name}'",
                                    data={"fallback": fallback_name},
                                )
                            )
                            return True
                    except Exception as e:
                        logger.warning(f"Fallback executor '{fallback_name}' failed: {e}")

        # 2. Tier 3 Recovery: LLM-driven Subgraph Replacement
        if self.llm and hasattr(self.llm, "generate"):
            try:
                replacement_tasks = self._generate_subgraph_replacement(task, graph, error_message)
                if replacement_tasks:
                    logger.info(f"Replacing subgraph for task '{task.id}' with {len(replacement_tasks)} tasks.")
                    graph.replace_subgraph(task.id, replacement_tasks)
                    self.event_bus.publish(
                        TaskProgressEvent(
                            event_type=TaskEventType.EXECUTION_REPLANNED,
                            graph_id=graph.graph_id,
                            task_id=task.id,
                            message=f"Replanned task into {len(replacement_tasks)} replacement steps",
                        )
                    )
                    return True
            except Exception as e:
                logger.warning(f"LLM subgraph replanning failed: {e}")

        # 3. Tier 4: Graceful Degradation / Non-critical skipping
        # If task is low-priority (priority == 1) and no dependents exist, skip without failing workflow
        dependents = graph.get_dependents(task.id)
        if not dependents and task.priority <= 1:
            logger.info(f"Task '{task.id}' is non-critical with no dependents. Marking SKIPPED.")
            graph.mark_skipped(task.id, reason=f"Non-critical failure: {error_message}")
            self.event_bus.publish(
                TaskProgressEvent(
                    event_type=TaskEventType.TASK_SKIPPED,
                    graph_id=graph.graph_id,
                    task_id=task.id,
                    message=f"Non-critical task skipped: {error_message}",
                )
            )
            return True

        return False

    def _generate_subgraph_replacement(
        self,
        failed_task: TaskStep,
        graph: TaskGraph,
        error: str,
    ) -> list[TaskStep] | None:
        """Prompt the LLM to generate alternative replacement steps for a failed subtask."""
        dependents = [d.id for d in graph.get_dependents(failed_task.id)]
        catalog = self.registry.get_easytool_catalog(limit=30)

        prompt = f"""A subtask in an autonomous task execution graph has failed.
GOAL: {graph.goal}
FAILED TASK:
ID: {failed_task.id}
Description: {failed_task.description}
Executor: {failed_task.selected_executor}
Parameters: {failed_task.parameters}
Error: {error}
Dependents waiting on this task: {dependents}

AVAILABLE EXECUTORS:
{catalog}

Generate 1 or 2 replacement tasks to achieve this subtask's objective using alternative tools/models.
Output ONLY a JSON array of task objects matching the TaskStep schema:
[
  {{
    "id": "{failed_task.id}_alt1",
    "description": "Alternative action",
    "executor": "alternative_executor",
    "parameters": {{}}
  }}
]
"""
        messages = [
            Message(role=Role.SYSTEM, content="You are FRIDAY's Dynamic Task Replanner. Output only raw JSON array."),
            Message(role=Role.USER, content=prompt),
        ]
        resp = self.llm.generate(messages)
        content = resp.content.strip()

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return None

        replacements = []
        for item in parsed:
            step = TaskStep(
                id=item.get("id", f"{failed_task.id}_alt"),
                description=item.get("description", "Alternative step"),
                selected_executor=item.get("executor"),
                parameters=item.get("parameters", {}),
                inputs=item.get("parameters", {}),
                dependencies=list(failed_task.dependencies),
            )
            replacements.append(step)

        return replacements
