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


from friday.agent.prompts import build_system_message
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.agents.base_agent import AgentTask, BaseAgent

from friday.agents.registry import AgentRegistry

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

def strip_thought_tags(text: str) -> str:
    """Strip <thought>...</thought> scratchpad tags for clean user presentation."""
    if not text:
        return ""
    cleaned = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL).strip()
    if cleaned:
        return cleaned
    match = re.search(r"<thought>(.*?)</thought>", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

class CognitiveMixin:
    task_context: dict | None = None
    def process_message(
            self,
            user_input: str,
        ) -> AgentResponse:
            """Process a user message through reasoning, safety validation, and sequential/parallel tool execution."""
            start_time = time.perf_counter()
            clean_input = user_input.strip()

            # Initialize fresh state machine for this turn/request
            self.state_machine = ReasoningStateMachine()

            if not clean_input:
                self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Received empty turn")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing greeting prompt")
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating greeting response")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Greeting ready")
                return AgentResponse(
                    content=f"I'm listening. How can I assist you today, {self.settings.user_name}?",
                    is_done=True,
                    metadata={
                        "task_state": self.state_machine.current_state.value,
                        "state_history": [r.to_dict() for r in self.state_machine.history],
                    }
                )

            logger.info(f"Processing user turn: '{clean_input[:60]}...'")

            # Greeting fast-path: simple greetings bypass the cognitive loop
            # (which would otherwise ask for clarification), capability routing,
            # and the tool-calling state machine entirely.
            greeting_response = self._greeting_fast_path(clean_input)
            if greeting_response is not None:
                if hasattr(self, "notifications") and self.notifications:
                    proactive = self.notifications.pop_notifications_summary()
                    if proactive:
                        greeting_response.content = f"{proactive}\n\n{greeting_response.content}"
                return greeting_response

            direct_desktop_response = self._direct_desktop_action_fast_path(clean_input, start_time)
            if direct_desktop_response is not None:
                return direct_desktop_response

            # 1. State: UNDERSTANDING (evaluating cognitive confidence, information sufficiency & capability routing)
            self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Interpreting user turn and retrieving memories")

            # Evaluate cognitive loop & confidence
            cognitive_decision = self.cognitive_engine.evaluate_request(clean_input)
            if cognitive_decision.current_phase == CognitivePhase.CLARIFY and cognitive_decision.clarification_prompt:
                logger.info(
                    f"Cognitive loop triggered CLARIFY (confidence: {cognitive_decision.confidence.understanding_confidence:.2f})"
                )
                self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing clarification prompt")
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating clarification response")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Clarification ready")

                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                clarify_msg = Message(role=Role.ASSISTANT, content=cognitive_decision.clarification_prompt)
                self.memory.add_message(clarify_msg)

                return AgentResponse(
                    content=cognitive_decision.clarification_prompt,
                    is_done=True,
                    metadata={
                        "duration_seconds": time.perf_counter() - start_time,
                        "task_state": self.state_machine.current_state.value,
                        "state_history": [r.to_dict() for r in self.state_machine.history],
                        "cognitive_phase": cognitive_decision.current_phase.value,
                        "confidence": cognitive_decision.confidence.to_dict(),
                        "lacks_information": cognitive_decision.lacks_information,
                    },
                )

            # Evaluate capability routing
            routing_decision = self.capability_router.route_request(
                user_input=clean_input,
                context={"has_working_context": bool(self.task_context)},
            )
            logger.info(f"Capability routed to: {routing_decision.selected_capability.value}")

            # State: PLANNING & EXECUTING (Delegating to authoritative ExecutionGateway / JarvisOrchestrator)
            self.state_machine.transition_to(TaskState.PLANNING, reason="Delegating to authoritative ExecutionGateway")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Executing via JarvisOrchestrator")
            
            recalled = []
            if hasattr(self, "_retrieve_relevant_memories"):
                recalled = self._retrieve_relevant_memories(clean_input)
            elif should_retrieve_memory(clean_input):
                recalled = self.memory.search(clean_input, limit=5)
            
            context = {
                "has_working_context": bool(self.task_context),
                "recalled_memories": [r.to_dict() for r in recalled] if recalled else [],
                "routed_capability": routing_decision.selected_capability.value,
            }
            
            exec_res = self.execute_complex_task(goal=clean_input, context=context)
            
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying orchestrator output")
            
            if exec_res.metadata.get("is_successful", True):
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Orchestrator execution successful")
            else:
                self.state_machine.fail(reason="Orchestrator execution failed")
                
            final_content = exec_res.content
            
            # Check and prepend any pending proactive notifications
            proactive_summary = None
            if hasattr(self, "notifications") and self.notifications:
                proactive_summary = self.notifications.pop_notifications_summary()

            if proactive_summary:
                final_content = f"{proactive_summary}\n\n{final_content}"

            # Persist final assistant turn in conversation memory
            user_msg = Message(role=Role.USER, content=clean_input)
            self.memory.add_message(user_msg)
            
            final_msg = Message(role=Role.ASSISTANT, content=final_content)
            self.memory.add_message(final_msg)

            duration = time.perf_counter() - start_time
            logger.info(f"Turn processed successfully in {duration:.2f}s [Final State: {self.state_machine.current_state.value}]")

            return AgentResponse(
                content=final_content,
                is_done=True,
                metadata={
                    "duration_seconds": duration,
                    "success": (self.state_machine.current_state == TaskState.COMPLETED),
                    "provider": self.llm.provider_name,
                    "model": self.llm.model,
                    "cost_mode": getattr(self.settings, "cost_mode", "free_first"),
                    "task_state": self.state_machine.current_state.value,
                    "state_history": [r.to_dict() for r in self.state_machine.history],
                    "failure_reason": self.state_machine.failure_reason,
                    "cognitive_phase": cognitive_decision.current_phase.value,
                    "confidence": cognitive_decision.confidence.to_dict(),
                    "routed_capability": routing_decision.selected_capability.value,
                    "jarvis_orchestration": exec_res.metadata.get("jarvis_orchestration", False),
                    "graph_id": exec_res.metadata.get("graph_id"),
                    "total_tasks": exec_res.metadata.get("total_tasks"),
                    "completed_tasks": exec_res.metadata.get("completed_tasks"),
                },
            )
