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
            clean_input = self.normalize_wake_phrase(user_input)

            # Initialize fresh state machine for this turn/request
            self.state_machine = ReasoningStateMachine()
            self._processed_tool_ids.clear()

            if not clean_input:
                self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Received empty turn")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing greeting prompt")
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating greeting response")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Greeting ready")
                return AgentResponse(
                    content=(
                        f"I'm listening. How can I assist you today, {self.settings.user_name}?"
                        if getattr(self.settings, "persona", "friday") != "friday"
                        else f"{self.settings.user_name}. I'm listening and at your command. What would you like done?"
                    ),
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
                        from friday.persona.friday import proactive_style
                        persona = getattr(self.settings, "persona", "friday") or "friday"
                        proactive = proactive_style(persona, proactive, self.settings.user_name)
                        greeting_response.content = f"{proactive}\n\n{greeting_response.content}"
                return greeting_response

            conversational_response = self._conversational_fast_path(clean_input)
            if conversational_response is not None:
                return conversational_response

            direct_desktop_response = self._direct_desktop_action_fast_path(clean_input, start_time)
            if direct_desktop_response is not None:
                return direct_desktop_response

            deterministic_response = self._deterministic_action_fast_path(clean_input, start_time)
            if deterministic_response is not None:
                return deterministic_response

            # Multi-turn context resolution: Handle affirmative or negative responses to previous turn
            low_input = clean_input.lower().strip().rstrip(".!? ")
            affirmative_words = {
                "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "proceed",
                "send", "send it", "confirm", "confirmed", "do it", "go ahead",
                "approve", "approved", "please do", "sounds good", "let's do it",
                "execute", "run it"
            }
            negation_words = {
                "no", "n", "nope", "cancel", "stop", "abort", "don't", "dont",
                "do not", "never mind", "nevermind", "discard"
            }

            recent_messages = self.memory.get_messages()
            last_assistant_msg = next((m for m in reversed(recent_messages) if m.role == Role.ASSISTANT), None)

            effective_goal = clean_input
            is_confirmation_turn = False

            if last_assistant_msg and last_assistant_msg.content:
                last_text = last_assistant_msg.content
                has_pending_prompt = (
                    "?" in last_text
                    or "would you like" in last_text.lower()
                    or "ready to send" in last_text.lower()
                    or "should i" in last_text.lower()
                    or "draft" in last_text.lower()
                    or "confirmation" in last_text.lower()
                )

                if low_input in negation_words and has_pending_prompt:
                    # Graceful instant cancellation
                    cancel_reply = "Understood. I have cancelled the pending action."
                    self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Action cancellation received")
                    self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing cancellation confirmation")
                    self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating cancellation response")
                    self.state_machine.transition_to(TaskState.COMPLETED, reason="Cancellation complete")

                    self.memory.add_message(Message(role=Role.USER, content=clean_input))
                    self.memory.add_message(Message(role=Role.ASSISTANT, content=cancel_reply))
                    try:
                        from friday.memory.memora_client import memora_client
                        memora_client.record_interaction_async(
                            user_input=clean_input,
                            agent_output=cancel_reply,
                            agent_name="friday",
                            event_type="dialogue",
                            tags=["cancellation"],
                        )
                    except Exception as e:
                        logger.debug(f"Memora cancellation record skipped: {e}")

                    return AgentResponse(
                        content=cancel_reply,
                        is_done=True,
                        metadata={
                            "duration_seconds": time.perf_counter() - start_time,
                            "task_state": self.state_machine.current_state.value,
                            "action_cancelled": True,
                        },
                    )

                if low_input in affirmative_words and has_pending_prompt:
                    is_confirmation_turn = True
                    # Check if previous message was an email draft
                    m_to = re.search(r"(?:To|to):\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", last_text)
                    m_subj = re.search(r"(?:Subject|subject):\s*([^\n]+)", last_text)
                    if m_to and m_subj:
                        to_addr = m_to.group(1).strip()
                        subject_str = m_subj.group(1).strip()
                        effective_goal = (
                            f"The user confirmed '{clean_input}' to send the drafted email to '{to_addr}' "
                            f"with subject '{subject_str}'. Execute the send_email tool now to deliver this email."
                        )
                    else:
                        effective_goal = (
                            f"The user replied '{clean_input}' confirming the action from your previous message: "
                            f"'{last_text[:120]}'. Execute the confirmed action now using the appropriate tools."
                        )

            # 1. State: UNDERSTANDING (evaluating cognitive confidence, information sufficiency & capability routing)
            self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Interpreting user turn and retrieving memories")

            # Evaluate cognitive loop & confidence (CLARIFY prompt bypassed if this is a confirmed action turn)
            cognitive_decision = self.cognitive_engine.evaluate_request(clean_input)
            if not is_confirmation_turn:
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
                user_input=effective_goal,
                context={"has_working_context": bool(self.task_context) or is_confirmation_turn},
            )
            logger.info(f"Capability routed to: {routing_decision.selected_capability.value}")

            # State: PLANNING & EXECUTING (Delegating to authoritative ExecutionGateway / FridayOrchestrator)
            self.state_machine.transition_to(TaskState.PLANNING, reason="Planning the requested action")
            
            recalled = []
            if hasattr(self, "_retrieve_relevant_memories"):
                recalled = self._retrieve_relevant_memories(effective_goal)
            elif should_retrieve_memory(effective_goal):
                recalled = self.memory.search(effective_goal, limit=5)
            
            context = {
                "has_working_context": bool(self.task_context) or is_confirmation_turn,
                "recalled_memories": [
                    r.to_dict() if hasattr(r, "to_dict") else (r.model_dump() if hasattr(r, "model_dump") else dict(r))
                    for r in recalled
                ] if recalled else [],
                "routed_capability": routing_decision.selected_capability.value,
            }
            
            exec_res = self.execute_complex_task(goal=effective_goal, context=context)
            
            if exec_res.tool_calls or exec_res.tool_results:
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Executing authorized tools")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying action or response")
            
            if exec_res.metadata.get("is_successful", True):
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Orchestrator execution successful")
            else:
                self.state_machine.fail(reason=exec_res.content or "LLM generation failed")
                
            final_content = exec_res.content
            
            # Check and prepend any pending proactive notifications
            proactive_summary = None
            if hasattr(self, "notifications") and self.notifications:
                proactive_summary = self.notifications.pop_notifications_summary()

            if proactive_summary:
                final_content = f"{proactive_summary}\n\n{final_content}"

            # Persist turns and intermediate tool traces in conversation memory
            user_msg = Message(role=Role.USER, content=clean_input)
            self.memory.add_message(user_msg)

            # Record turn and extract long-term facts/preferences into Memora
            try:
                from friday.memory.memora_client import memora_client
                memora_client.record_interaction_async(
                    user_input=clean_input,
                    agent_output=final_content or "",
                    agent_name="friday",
                    event_type="dialogue"
                )
            except Exception as e:
                logger.debug(f"Memora auto-record skipped: {e}")

            all_tool_calls = exec_res.tool_calls
            if exec_res.tool_results:
                if not all_tool_calls:
                    all_tool_calls = []
                    for idx, tr in enumerate(exec_res.tool_results):
                        all_tool_calls.append(ToolCall(id=tr.tool_call_id or f"call_{idx}", name=tr.name, arguments={}))
                for tc, tr in zip(all_tool_calls, exec_res.tool_results):
                    if getattr(self, "tool_callback", None):
                        try:
                            self.tool_callback(tc, tr)
                        except Exception:
                            pass
                assistant_tc_msg = Message(role=Role.ASSISTANT, content="", tool_calls=all_tool_calls)
                self.memory.add_message(assistant_tc_msg)
                for tr in exec_res.tool_results:
                    self.memory.add_message(Message(role=Role.TOOL, content=tr.content, name=tr.name, tool_call_id=tr.tool_call_id or "call_0"))

            final_msg = Message(role=Role.ASSISTANT, content=final_content)
            self.memory.add_message(final_msg)

            duration = time.perf_counter() - start_time
            logger.info(f"Turn processed successfully in {duration:.2f}s [Final State: {self.state_machine.current_state.value}]")

            return AgentResponse(
                content=final_content,
                tool_calls=all_tool_calls,
                tool_results=exec_res.tool_results,
                is_done=True,
                metadata={
                    "iterations": exec_res.metadata.get("iterations", exec_res.metadata.get("total_tasks", 1) or 1),
                    "request_count": exec_res.metadata.get("iterations", exec_res.metadata.get("total_tasks", 1) or 1),
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
                    "goal_orchestration": exec_res.metadata.get("goal_orchestration", False),
                    "graph_id": exec_res.metadata.get("graph_id"),
                    "total_tasks": exec_res.metadata.get("total_tasks"),
                    "completed_tasks": exec_res.metadata.get("completed_tasks"),
                },
            )
