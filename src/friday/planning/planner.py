"""Dynamic Task Planner for FRIDAY Planning Architecture.

Inspired by Microsoft JARVIS / HuggingGPT Controller Stage:
- Uses the LLM as the central planning brain to decompose natural-language requests into executable task DAGs.
- Synthesizes typed subtasks, data dependencies, and executor selections using EasyTool summaries.
- Validates graph acyclicity and parameter structure before returning the TaskGraph.
- Includes a deterministic semantic fallback planner for offline/mock environments.
"""

from __future__ import annotations

import json
import re
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel
from friday.planning.executors import ExecutorRegistry
from friday.planning.router import ModelRouter
from friday.planning.types import TaskDataType, TaskGraph, TaskGraphValidationError, TaskStep

logger = get_logger("planning.planner")

PLANNER_SYSTEM_PROMPT = """You are FRIDAY's Task Planning Controller (inspired by Microsoft JARVIS / HuggingGPT).
Your job is to decompose a user request into a minimal, structured, dependency-aware Directed Acyclic Graph (DAG) of executable subtasks.

AVAILABLE EXECUTORS & TOOLS:
{executor_catalog}

RULES:
1. Decompose the request into discrete tasks. Independent tasks should have empty dependencies or share prerequisites so they can run in parallel.
2. Dependent tasks MUST specify the IDs of tasks they depend on in `dependencies` (e.g. `["task_1"]`).
3. To pass output from an earlier task into a parameter, use `<TASK_ID>` (e.g. `"file": "<task_1>"`).
4. Output MUST be ONLY a valid JSON array of task objects with this schema:
[
  {{
    "id": "task_1",
    "description": "Short description of the action",
    "objective": "Specific goal of this subtask",
    "dependencies": [],
    "input_types": ["text"],
    "output_type": "text",
    "executor": "name_of_executor_or_tool",
    "parameters": {{}}
  }}
]
Do not output markdown code fences or conversational explanation. Output ONLY the raw JSON array.
"""


class DynamicTaskPlanner:
    """Decomposes natural language user goals into validated TaskGraph DAGs."""

    def __init__(
        self,
        executor_registry: ExecutorRegistry,
        llm_provider: Any = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        self.registry = executor_registry
        self.llm = llm_provider
        self.router = model_router or ModelRouter(executor_registry)

    def plan(self, user_request: str, context: dict[str, Any] | None = None) -> TaskGraph:
        """Create a validated TaskGraph from a natural language request."""
        clean_request = user_request.strip()
        if not clean_request:
            raise TaskGraphValidationError("Cannot plan for an empty request.")

        # 1. Attempt LLM-driven planning if provider is available
        if self.llm and hasattr(self.llm, "generate"):
            try:
                graph = self._plan_with_llm(clean_request, context)
                if graph and len(graph.list_tasks()) > 0:
                    return graph
            except Exception as e:
                logger.warning(f"LLM task planning failed, falling back to deterministic planner: {e}")

        # 2. Deterministic heuristic fallback planner
        return self._plan_heuristically(clean_request, context)

    def _plan_with_llm(self, user_request: str, context: dict[str, Any] | None) -> TaskGraph | None:
        """Query LLM to generate the task graph."""
        catalog = self.registry.get_easytool_catalog(limit=40)
        sys_prompt = PLANNER_SYSTEM_PROMPT.format(executor_catalog=catalog)

        ctx_line = ""
        if context and context.get("screen_text"):
            ctx_line = f"\nCurrent Screen Context:\n{str(context['screen_text'])[:300]}\n"

        prompt = f"{ctx_line}User Request: {user_request}\nDecompose into JSON task graph:"

        messages = [
            Message(role=Role.SYSTEM, content=sys_prompt),
            Message(role=Role.USER, content=prompt),
        ]
        resp = self.llm.generate(messages)
        content = resp.content.strip()

        # Clean markdown codeblocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Parse JSON
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return None

        tasks: list[TaskStep] = []
        for idx, item in enumerate(parsed, start=1):
            t_id = str(item.get("id") or f"task_{idx}")
            desc = str(item.get("description") or f"Subtask {idx}")
            obj = str(item.get("objective") or desc)
            deps = [str(d) for d in item.get("dependencies", [])]
            in_types = [
                TaskDataType(t) if t in TaskDataType._value2member_map_ else TaskDataType.ANY
                for t in item.get("input_types", ["any"])
            ]
            out_type_str = item.get("output_type", "text")
            out_type = TaskDataType(out_type_str) if out_type_str in TaskDataType._value2member_map_ else TaskDataType.TEXT
            executor_name = item.get("executor")
            params = item.get("parameters", {})

            step = TaskStep(
                id=t_id,
                description=desc,
                objective=obj,
                dependencies=deps,
                input_types=in_types,
                output_type=out_type,
                selected_executor=executor_name,
                parameters=params,
                inputs=params,
            )
            # Route and assign executor
            self.router.route_task(step)
            tasks.append(step)

        graph = TaskGraph(goal=user_request, tasks=tasks)
        # Validate acyclicity
        cycles = graph.detect_cycles()
        if cycles:
            logger.warning(f"LLM produced cyclic plan: {cycles}. Aborting LLM plan.")
            return None

        return graph

    def _plan_heuristically(self, user_request: str, context: dict[str, Any] | None) -> TaskGraph:
        """Deterministic fallback planner when LLM is unavailable or unparseable."""
        req_lower = user_request.lower()
        tasks: list[TaskStep] = []

        # Pattern: "look at my screen / screenshot and ..."
        if "screen" in req_lower or "screenshot" in req_lower:
            t1 = TaskStep(
                id="task_1",
                description="Capture screen snapshot",
                objective="Capture screenshot of active display",
                dependencies=[],
                input_types=[TaskDataType.ANY],
                output_type=TaskDataType.SCREENSHOT,
                tool_name="screen_snapshot",
            )
            self.router.route_task(t1)
            tasks.append(t1)

            t2 = TaskStep(
                id="task_2",
                description="Analyze screen content for errors or requested details",
                objective="Analyze screen",
                dependencies=["task_1"],
                input_types=[TaskDataType.SCREENSHOT],
                output_type=TaskDataType.TEXT,
                parameters={"query": user_request, "image": "<task_1>"},
                inputs={"query": user_request, "image": "<task_1>"},
            )
            self.router.route_task(t2)
            tasks.append(t2)

        # Pattern: Multi-part query connected by "and", "then", "after that"
        elif any(sep in req_lower for sep in (" and then ", " then ", " after that ")):
            parts = re.split(r"\s+(?:and\s+then|then|after\s+that)\s+", user_request, flags=re.IGNORECASE)
            prev_id = None
            for idx, part in enumerate(parts, start=1):
                t_id = f"task_{idx}"
                deps = [prev_id] if prev_id else []
                step = TaskStep(
                    id=t_id,
                    description=part.strip(),
                    objective=part.strip(),
                    dependencies=deps,
                    input_types=[TaskDataType.TEXT],
                    output_type=TaskDataType.TEXT,
                    parameters={"query": part.strip()},
                    inputs={"query": part.strip()},
                )
                self.router.route_task(step)
                tasks.append(step)
                prev_id = t_id

        # Pattern: Parallel comparison ("compare X and Y", "analyze A, B and C")
        elif "compare" in req_lower and (" and " in req_lower or "," in req_lower):
            # Split items to compare
            cleaned = req_lower.replace("compare", "").strip()
            items = [item.strip() for item in re.split(r",|\sand\s", cleaned) if item.strip()]
            if len(items) >= 2:
                dep_ids = []
                for idx, item in enumerate(items, start=1):
                    t_id = f"task_search_{idx}"
                    s_step = TaskStep(
                        id=t_id,
                        description=f"Research details on {item}",
                        objective=f"Research {item}",
                        dependencies=[],
                        input_types=[TaskDataType.TEXT],
                        output_type=TaskDataType.TEXT,
                        parameters={"query": f"{item} specifications and details"},
                        inputs={"query": f"{item} specifications and details"},
                    )
                    self.router.route_task(s_step)
                    tasks.append(s_step)
                    dep_ids.append(t_id)

                # Final synthesis comparison step
                comp_step = TaskStep(
                    id="task_compare",
                    description=f"Compare findings and summarize recommendation for: {', '.join(items)}",
                    objective="Compare candidates",
                    dependencies=dep_ids,
                    input_types=[TaskDataType.TEXT],
                    output_type=TaskDataType.TEXT,
                    parameters={"prompt": f"Compare these options: {', '.join(items)}"},
                    inputs={"prompt": f"Compare these options: {', '.join(items)}"},
                )
                self.router.route_task(comp_step)
                tasks.append(comp_step)

        # Default: Single step
        if not tasks:
            step = TaskStep(
                id="task_1",
                description=user_request,
                objective=user_request,
                dependencies=[],
                input_types=[TaskDataType.TEXT],
                output_type=TaskDataType.TEXT,
                parameters={"query": user_request},
                inputs={"query": user_request},
            )
            self.router.route_task(step)
            tasks.append(step)

        return TaskGraph(goal=user_request, tasks=tasks)
