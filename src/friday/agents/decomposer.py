# -*- coding: utf-8 -*-
"""Task Decomposer for FRIDAY Multi-Agent Specialist System.

Breaks down complex goals into explicit, ordered subtasks formatted as JSON.
"""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Optional
import uuid

from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider

logger = get_logger("agents.decomposer")


@dataclass
class DecomposedSubtask:
    """Individual subtask generated from goal decomposition."""
    subtask_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    suggested_role: str = "general"
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecompositionResult:
    """Outcome of breaking down a high-level goal."""
    goal: str
    is_complex: bool
    subtasks: List[DecomposedSubtask] = field(default_factory=list)
    rationale: str = ""


class TaskDecomposer:
    """Decomposes complex requests into structured subtasks using LLM reasoning."""

    def __init__(self, llm_provider: BaseLLMProvider) -> None:
        self.llm = llm_provider

    def decompose(self, goal: str, context: Optional[Dict[str, Any]] = None) -> DecompositionResult:
        """Analyze a goal and decompose into subtasks if complex, or return single subtask."""
        clean_goal = (goal or "").strip()
        if not clean_goal:
            return DecompositionResult(goal="", is_complex=False, subtasks=[])

        prompt = (
            "You are the Task Decomposition Engine for the FRIDAY AI Operating System.\n"
            "Analyze the user's goal. Determine if it is a simple single-step action or a complex multi-step workflow.\n"
            "If it is complex, break it down into 2-5 clear, ordered subtasks.\n"
            "Assign each subtask a suggested specialist role such as: 'developer', 'researcher', 'coder', 'system_controller', 'writer', or 'general'.\n\n"
            "Respond ONLY with a valid JSON object matching this structure:\n"
            "{\n"
            '  "is_complex": true/false,\n'
            '  "rationale": "short explanation",\n'
            '  "subtasks": [\n'
            "    {\n"
            '      "title": "Subtask title",\n'
            '      "description": "Exact step instruction",\n'
            '      "suggested_role": "specialist_role",\n'
            '      "dependencies": []\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"User Goal: {clean_goal}\n"
            f"Context: {context or {}}"
        )

        messages = [
            Message(role=Role.SYSTEM, content="You are a strict JSON task decomposition assistant."),
            Message(role=Role.USER, content=prompt),
        ]

        try:
            resp = self.llm.generate(messages=messages)
            text = (resp.content or "").strip()
            
            # Extract JSON block
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                data = json.loads(text)

            is_complex = bool(data.get("is_complex", False))
            subtasks_raw = data.get("subtasks", [])
            subtasks: List[DecomposedSubtask] = []

            for idx, item in enumerate(subtasks_raw):
                subtasks.append(
                    DecomposedSubtask(
                        subtask_id=f"step_{idx + 1}",
                        title=item.get("title", f"Step {idx + 1}"),
                        description=item.get("description", ""),
                        suggested_role=item.get("suggested_role", "general"),
                        dependencies=item.get("dependencies", []),
                    )
                )

            if not subtasks:
                subtasks.append(
                    DecomposedSubtask(
                        subtask_id="step_1",
                        title="Execute Goal",
                        description=clean_goal,
                        suggested_role="general",
                    )
                )

            return DecompositionResult(
                goal=clean_goal,
                is_complex=is_complex and len(subtasks) > 1,
                subtasks=subtasks,
                rationale=data.get("rationale", ""),
            )

        except Exception as e:
            logger.warning(f"Task decomposition fallback to single task: {e}")
            return DecompositionResult(
                goal=clean_goal,
                is_complex=False,
                subtasks=[
                    DecomposedSubtask(
                        subtask_id="step_1",
                        title="Execute Goal",
                        description=clean_goal,
                        suggested_role="general",
                    )
                ],
                rationale=f"Direct fallback: {e}",
            )
