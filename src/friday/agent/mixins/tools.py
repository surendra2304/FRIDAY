import logging
import os
import random
import re
import subprocess
import time
import warnings
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus
import uuid
from datetime import datetime
from friday.agent.checkpoint import TaskCheckpoint, TaskCheckpointStore
from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.agent.executor import (
    ExecutionProgress,
    TaskExecutionEngine,
    TaskExecutionResult,
)
from friday.agent.planner import GoalDecomposer, TaskPlan
from friday.agent.prompts import build_system_message
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.agents.base_agent import AgentTask, BaseAgent
from friday.agents.decomposer import TaskDecomposer
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from friday.core.types import (
    AgentResponse,
    AuthorizationDecision,
    AuthorizationRequest,
    MemorySearchResult,
    Message,
    Role,
    SafetyLevel,
    ToolCall,
    ToolResult,
    TrustLevel,
)
from friday.llm.base import BaseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.memory.base import BaseMemory
from friday.memory.factory import create_memory
from friday.memory.policies import should_retrieve_memory
from friday.memory.task_context import ActiveTaskContext
from friday.observability.notifications import NotificationManager
from friday.routing.capability_router import CapabilityRouter
from friday.tools.builtin import (
    AIUniverseTool,
    CalculatorTool,
    CloseApplicationTool,
    ControlLightTool,
    ControlPlugTool,
    CreateGitBranchTool,
    CreateGitHubIssueTool,
    ExecuteCommandTool,
    FetchWebpageContentTool,
    FetchWebpageTool,
    FileListingTool,
    FileOperationsTool,
    FileReaderTool,
    FindOnScreenTool,
    GetActiveAppContextTool,
    GetAIUniverseStatusTool,
    GetSystemResourcesTool,
    GetTodaysEventsTool,
    GitCommitTool,
    GitPushTool,
    GitStatusTool,
    HealthCheckTool,
    KillProcessTool,
    LaunchApplicationTool,
    ListGitHubIssuesTool,
    ManageVolumeTool,
    ManageWindowsTool,
    MemorySearchTool,
    OpenApplicationTool,
    ProposeComputerActionTool,
    ReadActiveWindowTextTool,
    ReadOwnCodebaseTool,
    ReadScreenTextTool,
    ReplaceFileContentTool,
    RunTestsTool,
    ScreenPredictionTool,
    ScreenSnapshotTool,
    SendEmailTool,
    SynthesizeInformationTool,
    SystemControlTool,
    SystemInfoTool,
    SystemPowerControlTool,
    TimeDateTool,
    ToggleBluetoothTool,
    ToggleDarkModeTool,
    ToggleWifiTool,
    TypeTextTool,
    WebSearchTool,
    WriteCodeFileTool,
)
from friday.tools.registry import ToolRegistry
from friday.vision.actions import ActionType
from friday.vision.computer_control import ComputerActionExecutor
from friday.vision.detector import DeterministicActionDetector
from friday.vision.intent_detector import ActionIntent, IntentDetector
from friday.vision.windows_input_driver import (
    WindowsNativeInputDriver,
    check_desktop_interactivity,
)


logger = logging.getLogger(__name__)

class ToolExecutionMixin:
    def _create_default_registry(self) -> ToolRegistry:
            """Instantiate default tool registry with built-in safe tools."""
            registry = ToolRegistry()
            registry.register(SystemInfoTool())
            registry.register(TimeDateTool())
            registry.register(CalculatorTool())
            registry.register(FileReaderTool())
            registry.register(FileListingTool())
            registry.register(MemorySearchTool(self.memory))
            registry.register(ScreenSnapshotTool())
            registry.register(ProposeComputerActionTool())
            registry.register(OpenApplicationTool())
            registry.register(TypeTextTool())
            registry.register(CloseApplicationTool())
            registry.register(ManageVolumeTool())
            registry.register(SystemPowerControlTool())
            registry.register(ManageWindowsTool())
            registry.register(WebSearchTool())
            registry.register(FetchWebpageTool())
            registry.register(FileOperationsTool())
            registry.register(ExecuteCommandTool())
            registry.register(ReadScreenTextTool())
            registry.register(FindOnScreenTool())
            registry.register(GetActiveAppContextTool())
            registry.register(ReadActiveWindowTextTool())
            registry.register(GitStatusTool())
            registry.register(GitCommitTool())
            registry.register(GitPushTool())
            registry.register(ListGitHubIssuesTool())
            registry.register(CreateGitHubIssueTool())
            registry.register(GetSystemResourcesTool())
            registry.register(KillProcessTool())
            registry.register(LaunchApplicationTool())
            registry.register(SystemControlTool())
            registry.register(HealthCheckTool())
            registry.register(WriteCodeFileTool())
            registry.register(ReplaceFileContentTool())
            registry.register(RunTestsTool())
            registry.register(CreateGitBranchTool())
            registry.register(ControlLightTool())
            registry.register(ControlPlugTool())
            registry.register(FetchWebpageContentTool())
            registry.register(SynthesizeInformationTool())
            registry.register(ToggleDarkModeTool())
            registry.register(ToggleBluetoothTool())
            registry.register(ToggleWifiTool())
            registry.register(GetTodaysEventsTool())
            registry.register(SendEmailTool())
            registry.register(ReadOwnCodebaseTool())
            registry.register(AIUniverseTool(memory=self.memory))
            
            # FRIDAY Android Control Tools
            try:
                from friday.tools.builtin.android_control import (
                    OpenAndroidAppTool,
                    SwipeScreenTool,
                    TapScreenTool,
                    TypeTextTool as AndroidTypeTextTool,
                )
                registry.register(TapScreenTool())
                registry.register(SwipeScreenTool())
                registry.register(OpenAndroidAppTool())
                registry.register(AndroidTypeTextTool())
            except ImportError:
                pass
            registry.register(GetAIUniverseStatusTool())
            registry.register(ScreenPredictionTool())
            return registry

    def _init_default_agent_registry(self) -> AgentRegistry:
            """Instantiate default specialist agent pool for Multi-Agent Specialist Architecture."""
            from friday.agents.specialists.developer_agent import DeveloperAgent
            from friday.agents.specialists.research_agent import ResearchAgent
            from friday.agents.specialists.self_dev_agent import SelfDevAgent
            reg = AgentRegistry()
            reg.register_agent(
                DeveloperAgent(
                    agent_id="developer_01",
                    role="developer",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                )
            )
            reg.register_agent(
                SelfDevAgent(
                    agent_id="self_developer_01",
                    role="self_developer",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                )
            )
            reg.register_agent(
                ResearchAgent(
                    agent_id="researcher_01",
                    role="researcher",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                )
            )
            reg.register_agent(
                BaseAgent(
                    agent_id="system_controller_01",
                    role="system_controller",
                    instructions="Manage desktop windows, open and close apps, adjust volume, launch commands, and control system state.",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                    allowed_tools=[
                        "open_application",
                        "launch_application",
                        "close_application",
                        "manage_windows",
                        "manage_volume",
                        "system_control",
                        "health_check",
                        "type_text",
                    ],
                )
            )
            reg.register_agent(
                BaseAgent(
                    agent_id="coder_01",
                    role="coder",
                    instructions="Inspect codebase, manipulate files, parse code structures, and run test/build commands.",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                    allowed_tools=["read_file", "list_files", "file_operations", "execute_command", "calculator"],
                )
            )
            reg.register_agent(
                BaseAgent(
                    agent_id="general_01",
                    role="general",
                    instructions="General purpose reasoning, conversation, and fallback execution.",
                    llm_provider=self.llm,
                    tool_registry=self.tools,
                )
            )
            return reg

    async def _execute_via_specialist_agents(self, goal: str, decomposition) -> str:
            """Orchestrate execution across multiple specialist agents and return synthesized outcome."""
            subtask_summaries: list[str] = []
            for idx, subtask in enumerate(decomposition.subtasks):
                decision = self.agent_router.route_subtask(subtask)
                agent = decision.selected_agent
                logger.info(
                    f"[MULTI-AGENT] Routing subtask '{subtask.title}' to specialist '{agent.role}' "
                    f"(Score: {decision.score}, Reason: {decision.rationale})"
                )
                task_obj = AgentTask(
                    goal=f"{subtask.title}: {subtask.description}",
                    subtask_index=idx,
                    total_subtasks=len(decomposition.subtasks),
                )
                result = await agent.execute_task(task_obj)
                subtask_summaries.append(f"- **{subtask.title}** ({agent.role}): {result.output.strip()}")

            synthesized = (
                f"Completed complex workflow via {len(decomposition.subtasks)} specialist agents:\n\n"
                + "\n".join(subtask_summaries)
            )
            return synthesized

    def _execute_single_tool_call_internal(self, tc: ToolCall, timeout: float | None = None) -> ToolResult:
            """Internal helper handling validation, authorization, and execution of a single tool call."""
            # Replay prevention within turn
            if tc.id in self._processed_tool_ids:
                return ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=f"Error: Duplicate tool call ID '{tc.id}' ignored.",
                    is_error=True,
                    safety_level=SafetyLevel.SAFE,
                )
            self._processed_tool_ids.add(tc.id)

            tool = self.tools.get(tc.name)
            if not tool:
                err_msg = f"Error: Tool '{tc.name}' is not registered or available in FRIDAY's tool registry."
                logger.warning(err_msg)
                return ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=err_msg,
                    is_error=True,
                    safety_level=SafetyLevel.SAFE,
                )

            # 1. Validation happens BEFORE authorization request
            is_valid, validation_err = tool.validate_arguments(tc.arguments)
            if not is_valid:
                err_msg = f"Invalid arguments for tool '{tc.name}': {validation_err}"
                logger.warning(err_msg)
                return ToolResult(
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=err_msg,
                    is_error=True,
                    safety_level=tool.safety_level,
                )

            # 2. Extract affected resource (e.g. file paths) if present
            affected_res = tc.arguments.get("path") or tc.arguments.get("file_path") or tc.arguments.get("directory")
            if affected_res:
                affected_res = str(affected_res)

            auth_req = AuthorizationRequest(
                tool_name=tc.name,
                safety_level=tool.safety_level,
                arguments=tc.arguments,
                tool_call_id=tc.id,
                purpose=tool.description,
                affected_resource=affected_res,
            )

            # 3. Handle authorization check
            logger.info(f"Requesting authorization for tool '{tc.name}' [Safety: {tool.safety_level.value}]")
            auth_resp = self.authorizer.authorize(auth_req)

            logger.info(
                f"Authorization outcome for tool '{tc.name}': {auth_resp.decision.value} "
                f"(Reason: {auth_resp.reason})"
            )

            # 4. Execution happens ONLY after explicit authorization capability
            effective_timeout = timeout if timeout is not None else self.tool_timeout
            if auth_resp.decision == AuthorizationDecision.APPROVED:
                return self.tools.execute(
                    name=tc.name,
                    arguments=tc.arguments,
                    tool_call_id=tc.id,
                    authorization=auth_resp.capability,
                    timeout=effective_timeout,
                )
            
            err_msg = (
                f"Authorization Block: Execution of tool '{tc.name}' was {auth_resp.decision.value}. "
                f"Reason: {auth_resp.reason}"
            )
            return ToolResult(
                tool_call_id=tc.id,
                name=tc.name,
                content=err_msg,
                is_error=True,
                safety_level=tool.safety_level,
            )

    def _execute_single_tool_call(self, tc: ToolCall, timeout: float | None = None) -> ToolResult:
            """Validate, authorize, and execute a single tool call request with duration logging."""
            tool_start = time.perf_counter()
            result = self._execute_single_tool_call_internal(tc, timeout=timeout)
            tool_duration = time.perf_counter() - tool_start
            logger.info(
                f"Tool '{tc.name}' execution completed in {tool_duration:.4f}s "
                f"(Success: {not result.is_error})"
            )
            return result

    def _execute_single_tool_call_with_timeout(
            self, tc: ToolCall, timeout: float = 30.0
        ) -> ToolResult:
            """Execute a single tool call through ToolRegistry's shared worker pool and timeout mechanism."""
            return self._execute_single_tool_call(tc, timeout=timeout)

