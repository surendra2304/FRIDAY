"""Executor Abstraction, Built-in Executors, and Executor Registry for FRIDAY.

Inspired by Microsoft JARVIS / HuggingGPT Model Selection & EasyTool Principles:
- Models and tools are represented as typed expert executors with explicit capabilities.
- Concise, semantically rich descriptions suitable for LLM prompt context without bloat.
- Automatic wrapping of all 50+ FRIDAY tools into the unified executor catalog.
- Support for local models, cloud LLMs, vision engines, specialist agents, and OS control.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.planning.types import TaskDataType
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry

logger = get_logger("planning.executors")


@dataclass
class ExecutorResult:
    """Standardized output produced by an executor."""

    success: bool
    output: Any
    error: str | None = None
    output_type: TaskDataType = TaskDataType.TEXT
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_result: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "output_type": self.output_type.value,
            "duration_seconds": round(self.duration_seconds, 3),
            "metadata": self.metadata,
        }


class BaseExecutor(ABC):
    """Abstract interface for all model, tool, agent, and OS action executors."""

    def __init__(
        self,
        name: str,
        capability: str,
        description: str,
        input_types: list[TaskDataType] | None = None,
        output_types: list[TaskDataType] | None = None,
        provider: str = "friday",
        model: str | None = None,
        is_local: bool = True,
        cost_profile: str = "free",  # "free", "low", "medium", "high"
        latency_profile: str = "fast",  # "fast", "medium", "slow"
        safety_level: SafetyLevel = SafetyLevel.SAFE,
    ) -> None:
        self.name = name
        self.capability = capability
        self.description = description
        self.input_types = set(input_types or [TaskDataType.ANY])
        self.output_types = set(output_types or [TaskDataType.TEXT])
        self.provider = provider
        self.model = model
        self.is_local = is_local
        self.cost_profile = cost_profile
        self.latency_profile = latency_profile
        self.safety_level = safety_level

    @abstractmethod
    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        """Execute the subtask and return a standardized ExecutorResult."""
        pass

    def to_easytool_format(self) -> str:
        """Render a concise EasyTool description for LLM controller prompt injection."""
        in_str = ", ".join(t.value for t in self.input_types)
        out_str = ", ".join(t.value for t in self.output_types)
        loc = "local" if self.is_local else "cloud"
        return f"- `{self.name}` ({self.capability} | {loc} | {self.safety_level.value}): {self.description} [Inputs: {in_str} -> Outputs: {out_str}]"


class ToolExecutor(BaseExecutor):
    """Wraps a FRIDAY BaseTool instance from the ToolRegistry as an Executor."""

    def __init__(self, tool: BaseTool) -> None:
        input_types = [TaskDataType.JSON, TaskDataType.TEXT]
        output_type = TaskDataType.TOOL_RESULT

        # Modality inference based on tool name
        name_lower = tool.name.lower()
        if "snapshot" in name_lower or "screenshot" in name_lower:
            output_type = TaskDataType.SCREENSHOT
        elif "ocr" in name_lower or "read_screen" in name_lower:
            input_types.append(TaskDataType.SCREENSHOT)
            output_type = TaskDataType.TEXT
        elif "file" in name_lower:
            input_types.append(TaskDataType.FILE)
            output_type = TaskDataType.FILE

        super().__init__(
            name=tool.name,
            capability=f"tool_{tool.name}",
            description=tool.description.strip().split("\n")[0],
            input_types=input_types,
            output_types=[output_type],
            provider="friday_builtin",
            model=None,
            is_local=True,
            cost_profile="free",
            latency_profile="fast",
            safety_level=tool.safety_level,
        )
        self.tool = tool

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        import time

        start_t = time.perf_counter()
        try:
            # Flatten or adapt inputs for tool call
            kwargs = {}
            if isinstance(inputs, dict):
                kwargs.update(inputs)

            result: ToolResult = self.tool.execute(**kwargs)
            duration = time.perf_counter() - start_t

            if result.is_error:
                return ExecutorResult(
                    success=False,
                    output=result.content,
                    error=result.content,
                    output_type=TaskDataType.TOOL_RESULT,
                    duration_seconds=duration,
                    raw_result=result,
                )

            return ExecutorResult(
                success=True,
                output=result.content,
                output_type=TaskDataType.TOOL_RESULT,
                duration_seconds=duration,
                raw_result=result,
            )
        except Exception as e:
            duration = time.perf_counter() - start_t
            logger.error(f"ToolExecutor '{self.name}' error: {e}")
            return ExecutorResult(
                success=False,
                output=None,
                error=str(e),
                output_type=TaskDataType.TOOL_RESULT,
                duration_seconds=duration,
            )


class LLMExecutor(BaseExecutor):
    """Executes high-level reasoning, code synthesis, or text transformation via an LLM provider."""

    def __init__(
        self,
        name: str = "llm_reasoning",
        llm_provider: Any = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__(
            name=name,
            capability="text_reasoning",
            description="Deep multi-step reasoning, plan analysis, text synthesis, and code generation.",
            input_types=[TaskDataType.TEXT, TaskDataType.JSON, TaskDataType.STRUCTURED_DATA],
            output_types=[TaskDataType.TEXT, TaskDataType.JSON],
            provider="llm_provider",
            model=model_name,
            is_local=False,
            cost_profile="low",
            latency_profile="medium",
            safety_level=SafetyLevel.SAFE,
        )
        self.llm = llm_provider

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        import time

        start_t = time.perf_counter()
        prompt = inputs.get("prompt") or inputs.get("query") or inputs.get("text") or str(inputs)

        if not self.llm:
            return ExecutorResult(
                success=False,
                output=None,
                error="LLM provider is not configured.",
                duration_seconds=time.perf_counter() - start_t,
            )

        try:
            from friday.core.types import Message, Role

            msgs = [
                Message(role=Role.SYSTEM, content="You are FRIDAY's reasoning and synthesis engine. Provide precise, actionable output."),
                Message(role=Role.USER, content=prompt),
            ]
            resp = self.llm.generate(msgs)
            duration = time.perf_counter() - start_t
            return ExecutorResult(
                success=True,
                output=resp.content,
                output_type=TaskDataType.TEXT,
                duration_seconds=duration,
                raw_result=resp,
            )
        except Exception as e:
            duration = time.perf_counter() - start_t
            return ExecutorResult(
                success=False,
                output=None,
                error=str(e),
                duration_seconds=duration,
            )


class VisionExecutor(BaseExecutor):
    """Multimodal visual inspection, screen comprehension, and OCR extraction."""

    def __init__(self, name: str = "vision_analyzer", llm_provider: Any = None) -> None:
        super().__init__(
            name=name,
            capability="visual_analysis",
            description="Analyzes screen snapshots, images, diagrams, and detects visual errors or UI elements.",
            input_types=[TaskDataType.SCREENSHOT, TaskDataType.IMAGE, TaskDataType.FILE],
            output_types=[TaskDataType.TEXT, TaskDataType.STRUCTURED_DATA],
            provider="multimodal_vision",
            model="gemini-flash-vision",
            is_local=False,
            cost_profile="low",
            latency_profile="medium",
            safety_level=SafetyLevel.SAFE,
        )
        self.llm = llm_provider

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        import time

        start_t = time.perf_counter()
        query = inputs.get("query", "Describe what is visible on this screen and detect any errors or notifications.")
        image_path = inputs.get("image_path") or inputs.get("screenshot_path")

        # Check local OCR first if query is text-oriented
        try:
            if "text" in query.lower() or "error" in query.lower():
                from friday.vision.active_context import get_active_window_context

                ctx = get_active_window_context()
                if ctx and ctx.visible_text:
                    duration = time.perf_counter() - start_t
                    return ExecutorResult(
                        success=True,
                        output=f"Extracted active window text:\n{ctx.visible_text[:800]}",
                        output_type=TaskDataType.TEXT,
                        duration_seconds=duration,
                    )
        except Exception:
            pass

        # Multimodal cloud vision fallback
        if self.llm and hasattr(self.llm, "generate"):
            try:
                from friday.core.types import Message, Role

                msgs = [
                    Message(role=Role.USER, content=f"[Screen/Image Query]: {query} (Source: {image_path or 'current display'})")
                ]
                resp = self.llm.generate(msgs)
                duration = time.perf_counter() - start_t
                return ExecutorResult(
                    success=True,
                    output=resp.content,
                    output_type=TaskDataType.TEXT,
                    duration_seconds=duration,
                )
            except Exception as e:
                duration = time.perf_counter() - start_t
                return ExecutorResult(
                    success=False,
                    output=None,
                    error=f"Vision model failure: {e}",
                    duration_seconds=duration,
                )

        return ExecutorResult(
            success=False,
            output=None,
            error="No vision engine available.",
            duration_seconds=time.perf_counter() - start_t,
        )


class SpecialistAgentExecutor(BaseExecutor):
    """Executes subtasks by delegating to a specialist agent (e.g. DeveloperAgent, ResearchAgent)."""

    def __init__(self, agent: Any, role_name: str) -> None:
        super().__init__(
            name=f"agent_{agent.agent_id}",
            capability=f"specialist_{role_name}",
            description=f"Specialist agent focused on {role_name}.",
            input_types=[TaskDataType.TEXT, TaskDataType.JSON],
            output_types=[TaskDataType.TEXT, TaskDataType.JSON],
            provider="friday_specialist",
            is_local=True,
            cost_profile="free",
            latency_profile="medium",
            safety_level=SafetyLevel.SAFE,
        )
        self.agent = agent

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        import time

        start_t = time.perf_counter()
        query = inputs.get("query") or inputs.get("goal") or str(inputs)
        try:
            from friday.agents.base_agent import AgentTask

            task = AgentTask(description=query)
            res = self.agent.execute_task(task)
            duration = time.perf_counter() - start_t
            return ExecutorResult(
                success=res.success,
                output=res.result,
                error=res.error,
                duration_seconds=duration,
            )
        except Exception as e:
            return ExecutorResult(
                success=False,
                output=None,
                error=str(e),
                duration_seconds=time.perf_counter() - start_t,
            )


class ExecutorRegistry:
    """Catalog of all available executors, tools, vision systems, and specialist agents."""

    def __init__(self, register_defaults: bool = True) -> None:
        self._executors: dict[str, BaseExecutor] = {}
        if register_defaults:
            try:
                from friday.integrations.browser_use.executor import BrowserUseExecutor
                self.register(BrowserUseExecutor())
            except Exception as e:
                logger.debug(f"Default BrowserUseExecutor not registered: {e}")

            try:
                from friday.integrations.mini_swe.executor import MiniSWEAgentExecutor
                self.register(MiniSWEAgentExecutor())
            except Exception as e:
                logger.debug(f"Default MiniSWEAgentExecutor not registered: {e}")

            try:
                self.register(VisionExecutor())
            except Exception as e:
                logger.debug(f"Default VisionExecutor not registered: {e}")

    def register(self, executor: BaseExecutor) -> None:
        self._executors[executor.name] = executor

    def get(self, name: str) -> BaseExecutor | None:
        return self._executors.get(name)

    def list_executors(self) -> list[BaseExecutor]:
        return list(self._executors.values())

    def find_by_capability(self, capability: str) -> list[BaseExecutor]:
        return [e for e in self._executors.values() if capability.lower() in e.capability.lower()]

    def find_by_input_type(self, data_type: TaskDataType) -> list[BaseExecutor]:
        return [
            e for e in self._executors.values()
            if TaskDataType.ANY in e.input_types or data_type in e.input_types
        ]

    def register_tool_registry(self, tool_registry: ToolRegistry) -> None:
        """Automatically wrap and register every tool from ToolRegistry."""
        for tool in tool_registry.list_tools():
            self.register(ToolExecutor(tool))

    def get_easytool_catalog(self, limit: int = 50) -> str:
        """Produce a compact EasyTool format catalog for LLM prompt context."""
        lines = []
        for e in list(self._executors.values())[:limit]:
            lines.append(e.to_easytool_format())
        return "\n".join(lines)
