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

class TaskMixin:
    def create_plan(self, goal: str, steps: list[dict[str, Any]] | None = None) -> TaskPlan:
            """Create and validate a structured TaskPlan for a given user goal."""
            if steps:
                plan = GoalDecomposer.create_multi_step_plan(goal=goal, step_definitions=steps)
            else:
                plan = GoalDecomposer.create_single_step_plan(goal=goal, description=f"Process goal: {goal}")
            
            plan.validate(tool_registry=self.tools)
            self._current_plan = plan
            self.task_context = ActiveTaskContext(task_id=plan.plan_id, goal=goal, plan=plan)
            return plan

    def execute_plan(
            self,
            plan: TaskPlan | None = None,
            on_step_progress: Callable[[ExecutionProgress], None] | None = None,
            step_timeout_seconds: float | None = None,
            cancellation_token: Any | None = None,
        ) -> TaskExecutionResult:
            """Execute a structured TaskPlan using the TaskExecutionEngine."""
            target_plan = plan or self._current_plan
            if not target_plan:
                raise ValueError("No active TaskPlan provided or currently set on the agent.")

            if not self.task_context or self.task_context.task_id != target_plan.plan_id:
                self.task_context = ActiveTaskContext(task_id=target_plan.plan_id, goal=target_plan.goal, plan=target_plan)

            effective_step_timeout = step_timeout_seconds if step_timeout_seconds is not None else self.tool_timeout
            engine = TaskExecutionEngine(
                tool_registry=self.tools,
                authorizer=self.authorizer,
                step_timeout_seconds=effective_step_timeout,
                on_step_progress=on_step_progress,
            )
            res = engine.execute_plan(
                target_plan,
                state_machine=self.state_machine,
                task_context=self.task_context,
                cancellation_token=cancellation_token,
            )

            # Finalize working context and record high-level summary to long-term memory
            if self.task_context:
                self.task_context.set_state(res.state)
                summary_msg = self.task_context.finalize_and_extract_long_term_summary(success=res.success)
                if summary_msg:
                    self.memory.add_message(summary_msg)

            return res

    def pause_current_task(self, reason: str = "Interrupted by user") -> TaskCheckpoint | None:
            """Pause active task, capture snapshot checkpoint, and transition state to PAUSED."""
            if not self._current_plan or self.state_machine.current_state != TaskState.EXECUTING:
                logger.warning("No active executing task to pause.")
                return None

            self.state_machine.pause(reason=reason)
            step_results = self.task_context.step_outputs if self.task_context else {}
            active_step = self.task_context.active_step_id if self.task_context else None

            chk = self.checkpoint_store.save_checkpoint(
                task_id=self._current_plan.plan_id,
                goal=self._current_plan.goal,
                plan=self._current_plan,
                state=TaskState.PAUSED,
                active_step_id=active_step,
                step_results=step_results,
            )
            return chk

    def resume_task(self, task_id: str | None = None) -> TaskExecutionResult:
            """Resume execution of a paused task from its last valid checkpoint."""
            target_id = task_id or (self._current_plan.plan_id if self._current_plan else None)
            if not target_id:
                raise ValueError("No task ID provided or active to resume.")

            chk = self.checkpoint_store.get_latest_checkpoint(target_id)
            if not chk:
                raise ValueError(f"No checkpoint found for task '{target_id}'.")

            # Reconstruct TaskPlan from saved dictionary
            plan = TaskPlan.from_dict(chk.plan_dict)
            self._current_plan = plan

            # Set up active working context with previous step results
            self.task_context = ActiveTaskContext(task_id=plan.plan_id, goal=plan.goal, plan=plan)
            for sid, res_str in chk.step_results.items():
                self.task_context.record_step_result(sid, res_str)

            # Initialize fresh state machine representing paused task state
            self.state_machine = ReasoningStateMachine(task_id=plan.plan_id, initial_state=TaskState.PAUSED)
            self.state_machine.resume(reason="Resuming task execution from checkpoint")

            return self.execute_plan(plan=plan)

    def cancel_task(self, reason: str = "Cancelled by user") -> bool:
            """Cancel active task execution and propagate cancellation to execution engine."""
            if self.state_machine.is_terminal:
                return False

            self.state_machine.cancel(reason=reason)
            if hasattr(self, "execution_engine") and self.execution_engine:
                self.execution_engine.cancel(reason=reason)
            if self._current_plan:
                self.checkpoint_store.delete_checkpoint(self._current_plan.plan_id)
            return True

