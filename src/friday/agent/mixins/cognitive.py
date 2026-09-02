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

            # Universe Orchestration fast-path (AI Universe Integration)
            if not hasattr(self, "_universe_orchestrator"):
                from friday.integrations.universe_orchestrator import UniverseOrchestrator
                self._universe_orchestrator = UniverseOrchestrator(
                    memory=self.memory,
                    decomposer=getattr(self, "decomposer", None),
                )
            if self._universe_orchestrator.can_handle(clean_input):
                logger.info(f"AI Universe orchestration triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Decomposing Universe goal")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Executing Universe simulation")
                sim_res = self._universe_orchestrator.execute_universe_goal(clean_input)
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating Universe experiment outcomes")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Universe experiment complete")

                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=sim_res["synthesis"])
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=sim_res["synthesis"],
                    is_done=True,
                    metadata={
                        "universe_world_id": sim_res["world_id"],
                        "agent_count": sim_res["agent_count"],
                        "total_steps": sim_res["total_steps"],
                        "metrics": sim_res["metrics"],
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # Autonomous Dev Workflow fast-path (Autonomous Self-Coding)
            if not hasattr(self, "_dev_workflow"):
                from friday.workflows.dev_workflow import AutonomousDevWorkflow
                dev_ag = self.agent_registry.get_agent("developer")
                self._dev_workflow = AutonomousDevWorkflow(
                    developer_agent=dev_ag,
                    tool_registry=self.tools,
                )
            if self._dev_workflow.can_handle(clean_input):
                logger.info(f"Autonomous Dev Workflow triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Planning autonomous issue fix")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Writing code and running automated test verification")
                
                import asyncio
                import threading
                
                def run_coro_sync(coro):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        res = []
                        exc = []
                        def run_in_thread():
                            try:
                                res.append(asyncio.run(coro))
                            except Exception as e:
                                exc.append(e)
                        t = threading.Thread(target=run_in_thread)
                        t.start()
                        t.join()
                        if exc:
                            raise exc[0]
                        return res[0]
                    return asyncio.run(coro)

                dev_res = run_coro_sync(self._dev_workflow.execute_issue_fix(clean_input))

                self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying test suite outcome")
                self.state_machine.transition_to(
                    TaskState.COMPLETED if dev_res.get("success") else TaskState.FAILED,
                    reason=dev_res.get("summary", "Dev workflow complete"),
                )

                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=dev_res.get("summary", "Done."))
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=dev_res.get("summary", "Done."),
                    is_done=True,
                    metadata={
                        "dev_workflow": True,
                        "issue_id": dev_res.get("issue_id"),
                        "branch": dev_res.get("branch"),
                        "tests_passed": dev_res.get("tests_passed"),
                        "steps_taken": dev_res.get("steps_taken", []),
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # Self-Healing / Auto-Fix Workflow fast-path
            if not hasattr(self, "_self_healing_workflow"):
                from friday.workflows.self_healing_workflow import SelfHealingWorkflow
                self_dev_ag = self.agent_registry.get_agent("self_developer")
                self._self_healing_workflow = SelfHealingWorkflow(
                    self_dev_agent=self_dev_ag,
                    tool_registry=self.tools,
                    memory=self.memory,
                )
            if self._self_healing_workflow.can_handle(clean_input):
                logger.info(f"Self-Healing Workflow triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Planning autonomous self-fix")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Diagnosing and editing codebase")
                
                import asyncio
                import threading
                
                def run_coro_sync(coro):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        res = []
                        exc = []
                        def run_in_thread():
                            try:
                                res.append(asyncio.run(coro))
                            except Exception as e:
                                exc.append(e)
                        t = threading.Thread(target=run_in_thread)
                        t.start()
                        t.join()
                        if exc:
                            raise exc[0]
                        return res[0]
                    return asyncio.run(coro)

                fix_res = run_coro_sync(self._self_healing_workflow.execute_self_fix(clean_input))

                self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying self-fix outcome")
                self.state_machine.transition_to(
                    TaskState.COMPLETED if fix_res.get("success") else TaskState.FAILED,
                    reason=fix_res.get("summary", "Self-healing complete"),
                )

                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=fix_res.get("summary", "Done."))
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=fix_res.get("summary", "Done."),
                    is_done=True,
                    metadata={
                        "self_healing": True,
                        "steps_taken": fix_res.get("steps_taken", []),
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # Morning Briefing Workflow fast-path (Calendar & Morning Briefings)
            if not hasattr(self, "_briefing_workflow"):
                from friday.workflows.briefing_workflow import MorningBriefingWorkflow
                cal_tool = self.tools.get_tool("get_todays_events")
                search_tool = self.tools.get_tool("web_search")
                self._briefing_workflow = MorningBriefingWorkflow(
                    calendar_tool=cal_tool,
                    search_tool=search_tool,
                )
            if self._briefing_workflow.can_handle(clean_input):
                logger.info(f"Morning Briefing Workflow triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Aggregating schedule, weather, and daily briefing")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Executing calendar fetch and forecast lookup")
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    briefing_res = loop.run_until_complete(self._briefing_workflow.generate_briefing())
                except RuntimeError:
                    briefing_res = asyncio.run(self._briefing_workflow.generate_briefing())

                self.state_machine.transition_to(TaskState.VERIFYING, reason="Formatting spoken briefing output")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Morning briefing delivered")

                speech_text = briefing_res.get("spoken_text", "Good morning.")
                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=speech_text)
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=speech_text,
                    is_done=True,
                    metadata={
                        "briefing_workflow": True,
                        "meeting_count": briefing_res.get("meeting_count", 0),
                        "weather": briefing_res.get("weather", "clear"),
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # Email Drafting Workflow fast-path (Web Research & Email Automation)
            if not hasattr(self, "_email_workflow"):
                from friday.workflows.email_workflow import EmailDraftingWorkflow
                send_tool = self.tools.get_tool("send_email")
                self._email_workflow = EmailDraftingWorkflow(send_tool=send_tool)
            if self._email_workflow.can_handle(clean_input):
                logger.info(f"Email Drafting Workflow triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Drafting email content via LLM")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Synthesizing email body and subject line")
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    draft_res = loop.run_until_complete(self._email_workflow.draft_email(clean_input))
                except RuntimeError:
                    draft_res = asyncio.run(self._email_workflow.draft_email(clean_input))

                self.state_machine.transition_to(TaskState.VERIFYING, reason="Formatting email preview")
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Draft email presented to user for review")

                preview_text = draft_res.get("preview_text", "Here is your email draft. Would you like me to send this?")
                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=preview_text)
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=preview_text,
                    is_done=True,
                    metadata={
                        "email_workflow": True,
                        "recipient": draft_res.get("recipient"),
                        "subject": draft_res.get("subject"),
                        "body": draft_res.get("body"),
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # Recursive Self-Improvement Workflow fast-path (Recursive Self-Improvement)
            if not hasattr(self, "_self_improve_workflow"):
                from friday.workflows.self_improve_workflow import SelfImprovementWorkflow
                self_ag = self.agent_registry.get_agent("self_developer")
                self._self_improve_workflow = SelfImprovementWorkflow(
                    self_dev_agent=self_ag,
                    tool_registry=self.tools,
                )
            if self._self_improve_workflow.can_handle(clean_input):
                logger.info(f"Recursive Self-Improvement Workflow triggered for: '{clean_input}'")
                self.state_machine.transition_to(TaskState.PLANNING, reason="Planning autonomous tool creation & codebase expansion")
                self.state_machine.transition_to(TaskState.EXECUTING, reason="Synthesizing Python tool and verifying with pytest")
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    improve_res = loop.run_until_complete(
                        self._self_improve_workflow.execute_self_improvement(clean_input)
                    )
                except RuntimeError:
                    improve_res = asyncio.run(
                        self._self_improve_workflow.execute_self_improvement(clean_input)
                    )

                self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying test suite outcome")
                self.state_machine.transition_to(
                    TaskState.COMPLETED if improve_res.get("success") else TaskState.FAILED,
                    reason=improve_res.get("summary", "Self-improvement complete"),
                )

                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)
                asst_msg = Message(role=Role.ASSISTANT, content=improve_res.get("summary", "Done."))
                self.memory.add_message(asst_msg)

                return AgentResponse(
                    content=improve_res.get("summary", "Done."),
                    is_done=True,
                    metadata={
                        "self_improve_workflow": True,
                        "feature": improve_res.get("feature"),
                        "target_filepath": improve_res.get("target_filepath"),
                        "tests_passed": improve_res.get("tests_passed"),
                        "steps_taken": improve_res.get("steps_taken", []),
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            # OpenJarvis-inspired Skills Execution Fast-Path
            if self.skill_registry:
                matched_skill_tuple = self.skill_registry.find_matching_skill(clean_input)
                if matched_skill_tuple:
                    matched_skill, match_score = matched_skill_tuple
                    logger.info(f"Skill match detected: '{matched_skill.name}' (score: {match_score:.2f})")

                    # Capability Gating Check
                    is_auth, auth_reason = self.authorizer.authorize_skill(matched_skill)
                    if not is_auth:
                        logger.warning(f"Skill '{matched_skill.name}' rejected by Capability Gating: {auth_reason}")
                        blocked_msg = f"Skill execution blocked: {auth_reason}"
                        user_msg = Message(role=Role.USER, content=clean_input)
                        self.memory.add_message(user_msg)
                        asst_msg = Message(role=Role.ASSISTANT, content=blocked_msg)
                        self.memory.add_message(asst_msg)
                        self.state_machine.fail(reason=auth_reason, metadata={"skill_blocked": True})

                        return AgentResponse(
                            content=blocked_msg,
                            is_done=True,
                            metadata={
                                "skill_name": matched_skill.name,
                                "skill_blocked": True,
                                "reason": auth_reason,
                                "success": False,
                                "task_state": self.state_machine.current_state.value,
                                "state_history": [r.to_dict() for r in self.state_machine.history],
                            },
                        )

                    # Skill Authorized -> Autonomous Execution
                    self.state_machine.transition_to(TaskState.PLANNING, reason=f"Planning skill execution: {matched_skill.name}")
                    self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing autonomous skill: {matched_skill.name}")

                    user_msg = Message(role=Role.USER, content=clean_input)
                    self.memory.add_message(user_msg)

                    exec_res = matched_skill.execute(
                        user_request=clean_input,
                        agent=self,
                        tool_registry=self.tools,
                        llm_provider=self.llm,
                        authorizer=self.authorizer,
                    )

                    self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying skill execution result")
                    if exec_res.success:
                        self.state_machine.transition_to(TaskState.COMPLETED, reason="Skill completed successfully")
                    else:
                        self.state_machine.fail(reason=exec_res.error or "Skill execution failed")

                    final_content = exec_res.output
                    asst_msg = Message(role=Role.ASSISTANT, content=final_content)
                    self.memory.add_message(asst_msg)

                    return AgentResponse(
                        content=final_content,
                        is_done=True,
                        metadata={
                            "skill_name": matched_skill.name,
                            "skill_executed": True,
                            "match_score": match_score,
                            "success": exec_res.success,
                            "step_results": exec_res.step_results,
                            "task_state": self.state_machine.current_state.value,
                            "state_history": [r.to_dict() for r in self.state_machine.history],
                        },
                    )

            # Intent detection for semantic UI actions
            intent_result = IntentDetector.detect(clean_input)
            if intent_result.intent == ActionIntent.SEMANTIC_UI_ACTION and intent_result.confidence >= 0.90:
                logger.info(f"Semantic UI action detected with confidence {intent_result.confidence}")
                if self.ui_provider:
                    uia_response = self._execute_semantic_ui_action(intent_result, clean_input)
                    if uia_response is not None:
                        return uia_response
                else:
                    logger.warning("UI Automation provider not initialized.")
            # Evaluate Deterministic Computer Action Fast-Path (Bypasses LLM & Vision entirely)
            det_intent = DeterministicActionDetector.detect(clean_input)
            if det_intent and det_intent.confidence >= 0.95:
                logger.info(
                    f"[FAST-PATH] Deterministic computer action detected: {det_intent.action_type.value} "
                    f"(Args: {det_intent.arguments}, Confidence: {det_intent.confidence})"
                )
                self.state_machine.transition_to(TaskState.PLANNING, reason="Formulating deterministic action proposal")
                proposal = det_intent.to_proposal()

                # Record user turn in memory
                user_msg = Message(role=Role.USER, content=clean_input)
                self.memory.add_message(user_msg)

                # Evaluate authorization requirement
                auth_req = AuthorizationRequest(
                    tool_name="execute_computer_action",
                    safety_level=det_intent.risk_level,
                    arguments=det_intent.arguments,
                    tool_call_id=str(uuid.uuid4()),
                    purpose=det_intent.intent,
                    affected_resource="windows_desktop",
                )
                auth_resp = self.authorizer.authorize(auth_req)

                if auth_resp.decision == AuthorizationDecision.APPROVED:
                    self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing deterministic {det_intent.action_type.value} action")
                    interactive, reason = check_desktop_interactivity()
                    sandboxed_mode = not interactive
                    executor = ComputerActionExecutor(sandboxed=sandboxed_mode)
                    exec_result = executor.execute_proposal(proposal, user_confirmed=True)

                    self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying action execution result")

                    if exec_result.is_success:
                        self.state_machine.transition_to(TaskState.COMPLETED, reason="Deterministic action executed successfully")
                        
                        if det_intent.action_type == ActionType.MOVE:
                            x_coord = det_intent.arguments.get("x")
                            y_coord = det_intent.arguments.get("y")
                            if "center" in clean_input.lower():
                                resp_content = f"Moved the mouse cursor to the center of the screen ({x_coord}, {y_coord})."
                            else:
                                resp_content = f"Moved the mouse cursor to ({x_coord}, {y_coord})."
                        elif det_intent.action_type == ActionType.SCROLL:
                            delta = det_intent.arguments.get("delta_y", 0)
                            dir_str = "up" if delta > 0 else "down"
                            resp_content = f"Scrolled the screen {dir_str}."
                        elif det_intent.action_type in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
                            x_coord = det_intent.arguments.get("x")
                            y_coord = det_intent.arguments.get("y")
                            resp_content = f"Clicked at coordinates ({x_coord}, {y_coord})."
                        else:
                            resp_content = f"Executed {det_intent.action_type.value} successfully."

                        assistant_resp_msg = Message(role=Role.ASSISTANT, content=resp_content)
                        self.memory.add_message(assistant_resp_msg)

                        return AgentResponse(
                            content=resp_content,
                            is_done=True,
                            metadata={
                                "fast_path": True,
                                "deterministic": True,
                                "action_type": det_intent.action_type.value,
                                "arguments": det_intent.arguments,
                                "execution_result": exec_result.to_dict(),
                                "duration_seconds": time.perf_counter() - start_time,
                                "task_state": self.state_machine.current_state.value,
                                "state_history": [r.to_dict() for r in self.state_machine.history],
                            }
                        )
                    else:
                        self.state_machine.fail(reason=f"Action execution failed: {exec_result.details}")
                        err_content = f"Failed to execute computer action: {exec_result.details}"
                        self.memory.add_message(Message(role=Role.ASSISTANT, content=err_content))
                        return AgentResponse(
                            content=err_content,
                            is_done=True,
                            metadata={
                                "fast_path": True,
                                "success": False,
                                "error": exec_result.details,
                                "duration_seconds": time.perf_counter() - start_time,
                                "task_state": self.state_machine.current_state.value,
                                "state_history": [r.to_dict() for r in self.state_machine.history],
                            }
                        )
                elif auth_resp.decision == AuthorizationDecision.DENIED:
                    self.state_machine.fail(reason=f"Authorization denied: {auth_resp.reason}")
                    denial_content = f"Action was not authorized: {auth_resp.reason}"
                    self.memory.add_message(Message(role=Role.ASSISTANT, content=denial_content))
                    return AgentResponse(
                        content=denial_content,
                        is_done=True,
                        metadata={
                            "fast_path": True,
                            "authorized": False,
                            "duration_seconds": time.perf_counter() - start_time,
                            "task_state": self.state_machine.current_state.value,
                            "state_history": [r.to_dict() for r in self.state_machine.history],
                        }
                    )
                else:
                    self.state_machine.cancel(reason="User cancelled authorization prompt")
                    cancel_content = "Action cancelled by user."
                    self.memory.add_message(Message(role=Role.ASSISTANT, content=cancel_content))
                    return AgentResponse(
                        content=cancel_content,
                        is_done=True,
                        metadata={
                            "fast_path": True,
                            "cancelled": True,
                            "duration_seconds": time.perf_counter() - start_time,
                            "task_state": self.state_machine.current_state.value,
                            "state_history": [r.to_dict() for r in self.state_machine.history],
                        }
                    )

            recalled = self._retrieve_relevant_memories(clean_input)
            if recalled:
                logger.info(f"Controlled Recall: Retrieved {len(recalled)} relevant historical memory item(s).")

            # 2. Append user message to long-term memory & initialize active working context
            user_msg = Message(role=Role.USER, content=clean_input)
            self.memory.add_message(user_msg)
            self.task_context = ActiveTaskContext(task_id=str(uuid.uuid4()), goal=clean_input)

            # 3. Construct base system prompt augmented with bounded historical context
            system_content = self.system_message.content
            if recalled:
                memory_block = "\n".join(
                    f"- [{r.timestamp.strftime('%Y-%m-%d')} | Trust: {r.trust_level.value if hasattr(r, 'trust_level') else 'trusted_user'}] {r.role.value.capitalize()}: {r.content}"
                    for r in recalled
                )
                augmented_system = (
                    f"{system_content}\n\n"
                    f"[Relevant Historical Memories]\n"
                    f"{memory_block}\n"
                    f"[End of Historical Memories]"
                )
                base_sys_msg = Message(role=Role.SYSTEM, content=augmented_system)
            else:
                base_sys_msg = self.system_message

            # 4. State: PLANNING (evaluating task complexity and action plan)
            self.state_machine.transition_to(TaskState.PLANNING, reason="Evaluating context and determining action plan")

            # Multi-Agent Complex Workflow Routing (Multi-Agent Specialist Architecture)
            # Trigger specialist multi-agent workflows for explicit project/research/multi-agent goals
            has_complex_cues = any(cue in clean_input.lower() for cue in [
                "step by step workflow", "multi-agent", "delegate to specialist",
                "research and write", "analyze and summarize project", "build and test workflow",
                "research the latest", "research and summarize", "find and summarize", "research about",
            ])
            if has_complex_cues:
                try:
                    decomposition = self.task_decomposer.decompose(clean_input)
                    if decomposition.is_complex and len(decomposition.subtasks) > 1:
                        logger.info(
                            f"[MULTI-AGENT] Goal decomposed into {len(decomposition.subtasks)} subtasks. "
                            f"Rationale: {decomposition.rationale}"
                        )
                        self.state_machine.transition_to(
                            TaskState.EXECUTING,
                            reason=f"Delegating to {len(decomposition.subtasks)} specialist agents",
                        )
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                            multi_res = loop.run_until_complete(
                                self._execute_via_specialist_agents(clean_input, decomposition)
                            )
                        except RuntimeError:
                            multi_res = asyncio.run(
                                self._execute_via_specialist_agents(clean_input, decomposition)
                            )

                        self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying specialist agent outputs")
                        self.state_machine.transition_to(TaskState.COMPLETED, reason="Multi-agent workflow completed")
                        self.memory.add_message(Message(role=Role.ASSISTANT, content=multi_res))
                        return AgentResponse(
                            content=multi_res,
                            is_done=True,
                            metadata={
                                "multi_agent": True,
                                "subtasks_count": len(decomposition.subtasks),
                                "duration_seconds": time.perf_counter() - start_time,
                                "task_state": self.state_machine.current_state.value,
                            },
                        )
                except Exception as e:
                    logger.warning(f"[MULTI-AGENT] Multi-agent orchestration fallback to single agent loop: {e}")

            working_context: list[Message] = [base_sys_msg] + self.memory.get_context_window(
                max_messages=self.settings.memory_max_messages,
                max_turns=5,
                max_tokens=3000,
            )

            # 5. Retrieve registered tool schemas
            tool_schemas = self.tools.get_schemas() if self.tools.list_tools() else None

            all_tool_calls: list[ToolCall] = []
            all_tool_results: list[ToolResult] = []
            final_content = ""
            iterations = 0
            tool_error_retries = 0
            max_self_correction_retries = 3

            # 6. Multi-step Reasoning & Autonomous Tool-calling Loop
            while iterations < self.max_tool_iterations:
                iterations += 1
                logger.debug(f"Agent decision iteration {iterations}/{self.max_tool_iterations}")

                # Rebuild working context from memory dynamically to maintain precise dialogue history
                working_context = [base_sys_msg] + self.memory.get_context_window(
                    max_messages=self.settings.memory_max_messages,
                    max_turns=5,
                    max_tokens=3000,
                )

                try:
                    assistant_msg = self.llm.generate(messages=working_context, tools=tool_schemas)
                except Exception as e:
                    logger.exception(f"LLM generation failed at iteration {iterations}: {e}")
                    self.state_machine.fail(reason=f"LLM generation failed: {type(e).__name__}", metadata={"error_type": type(e).__name__})
                    
                    # User friendly translated error messages
                    err_text = "I encountered a transient network issue while communicating with my intelligence core. Please try again in a moment."
                    err_str = str(e).lower()
                    
                    if "credential_exhausted" in err_str:
                        err_text = "I can't access my vision or reasoning service right now because all configured AI credentials are unavailable."
                    elif "circuit breaker active" in err_str:
                        err_text = "The AI service is temporarily paused after repeated failures. I'll retry after the cooldown."
                    elif "budget exceeded" in err_str:
                        err_text = "My AI budget limits have been reached for this session or task. I'm halting to prevent infinite loops or quota burn."
                    elif "rate limit" in err_str or "status 429" in err_str or "quota" in err_str:
                        err_text = "My AI quota is currently exhausted or experiencing high demand. Please hold on a moment and try again."
                    elif "authentication" in err_str or "api key" in err_str or "status 401" in err_str or "status 403" in err_str:
                        err_text = "I'm unable to authenticate with my intelligence core. Please verify your API key settings."
                    elif "connection" in err_str or "timeout" in err_str or "dns" in err_str:
                        err_text = "I'm having trouble connecting to my intelligence core. Please check your internet connection and try again."

                    self.memory.add_message(Message(role=Role.ASSISTANT, content=err_text))
                    return AgentResponse(
                        content=err_text,
                        is_done=True,
                        metadata={
                            "error": str(e),
                            "iterations": iterations,
                            "success": False,
                            "duration_seconds": time.perf_counter() - start_time,
                            "task_state": self.state_machine.current_state.value,
                            "state_history": [r.to_dict() for r in self.state_machine.history],
                            "failure_reason": self.state_machine.failure_reason,
                        },
                    )

                # Log and track inner monologue (<thought> scratchpad) if present
                if assistant_msg.content and "<thought>" in assistant_msg.content:
                    thought_match = re.search(r"<thought>(.*?)</thought>", assistant_msg.content, flags=re.DOTALL)
                    if thought_match:
                        thought_text = thought_match.group(1).strip()
                        logger.info(f"[THOUGHT] {thought_text}")
                        if self.task_context:
                            self.task_context.add_observation(
                                step_id=f"thought_{iterations}",
                                content=thought_text,
                                source_tool="inner_monologue",
                            )

                # If model returned direct answer without requesting tools -> finalize
                if not assistant_msg.tool_calls:
                    final_content = strip_thought_tags(assistant_msg.content or "Task completed.")
                    break

                # Model requested one or more tool calls -> State: EXECUTING
                if self.state_machine.current_state != TaskState.EXECUTING:
                    self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing {len(assistant_msg.tool_calls)} requested tool call(s)")

                logger.info(f"Iteration {iterations}: Model requested {len(assistant_msg.tool_calls)} tool call(s)")
                
                # Progress reporting: notify callbacks / logs before tool execution for background visibility
                for tc in assistant_msg.tool_calls:
                    if self.tool_callback:
                        try:
                            self.tool_callback(tc, None)
                        except Exception as cb_err:
                            logger.debug(f"Pre-execution tool callback error: {cb_err}")
                    if tc.name in ("fetch_webpage", "web_search", "fetch_webpage_content", "read_own_codebase", "run_tests"):
                        logger.info(f"Progress: Currently executing long-running task '{tc.name}'...")

                # Persist assistant's tool call intent message to memory
                self.memory.add_message(assistant_msg)

                # Safety level classification check: determine if all tool calls are SAFE
                all_safe = True
                for tc in assistant_msg.tool_calls:
                    tool = self.tools.get(tc.name)
                    # If tool doesn't exist, we class as SAFE for routing (rejection happens early in execute method)
                    if tool and tool.safety_level != SafetyLevel.SAFE:
                        all_safe = False
                        break

                batch_results: list[ToolResult] = []
                batch_start = time.perf_counter()
                tool_timeout = self.tool_timeout

                if all_safe and len(assistant_msg.tool_calls) > 1:
                    # SAFE independent tools -> Parallel execution supported safely via shared pool with timeout boundaries
                    logger.info(f"Coordinated execution: Executing {len(assistant_msg.tool_calls)} SAFE tools in parallel.")
                    from concurrent.futures import TimeoutError as FuturesTimeoutError
                    futures = [
                        self.tools._thread_executor.submit(self._execute_single_tool_call, tc, tool_timeout)
                        for tc in assistant_msg.tool_calls
                    ]
                    for fut, tc in zip(futures, assistant_msg.tool_calls):
                        remaining_timeout = max(0.01, tool_timeout - (time.perf_counter() - batch_start))
                        try:
                            res = fut.result(timeout=remaining_timeout)
                            batch_results.append(res)
                        except (FuturesTimeoutError, TimeoutError):
                            logger.error(f"Tool '{tc.name}' execution timed out (limit: {tool_timeout}s)")
                            batch_results.append(
                                ToolResult(
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                    content=f"Error: Tool execution timed out after {tool_timeout} seconds.",
                                    is_error=True,
                                    safety_level=SafetyLevel.SAFE,
                                )
                            )
                    latency = time.perf_counter() - batch_start
                    logger.info(f"Coordinated parallel execution completed in {latency:.4f}s.")
                else:
                    # Mixed or SENSITIVE/DANGEROUS tools -> Sequential ordering and auth semantics preserved
                    logger.info(f"Coordinated execution: Executing {len(assistant_msg.tool_calls)} tools sequentially.")
                    for tc in assistant_msg.tool_calls:
                        res = self._execute_single_tool_call_with_timeout(tc, timeout=tool_timeout)
                        batch_results.append(res)
                    latency = time.perf_counter() - batch_start
                    logger.info(f"Coordinated sequential execution completed in {latency:.4f}s.")

                # Process batch results in the exact requested order
                iteration_had_error = False
                for tc, result in zip(assistant_msg.tool_calls, batch_results):
                    all_tool_calls.append(tc)
                    all_tool_results.append(result)

                    # Record observation in active working memory context
                    if self.task_context:
                        self.task_context.add_observation(
                            step_id=tc.id,
                            content=result.content,
                            source_tool=tc.name,
                        )
                        self.task_context.record_step_result(
                            step_id=tc.id,
                            result=result.content,
                        )

                    # Notify callback if registered (e.g. for CLI status display)
                    if self.tool_callback:
                        try:
                            self.tool_callback(tc, result)
                        except Exception as cb_err:
                            logger.warning(f"Tool callback error: {cb_err}")

                    # Persist tool execution result message to memory with explicit UNTRUSTED_EXTERNAL trust level
                    self.memory.add_message(
                        Message(
                            role=Role.TOOL,
                            name=tc.name,
                            content=result.content,
                            tool_call_id=tc.id,
                            trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                            metadata={
                                "source_tool": tc.name,
                                "is_untrusted_observation": True,
                                "safety_level": result.safety_level.value if hasattr(result.safety_level, "value") else str(result.safety_level),
                            },
                        )
                    )

                    # Verify step execution outcome and trigger self-correction on tool error
                    if result.is_error:
                        iteration_had_error = True
                        tool_error_retries += 1
                        logger.warning(f"Tool error in '{tc.name}': {result.content[:120]!r} (retry {tool_error_retries}/{max_self_correction_retries})")

                        if tool_error_retries <= max_self_correction_retries:
                            # Feed error back into context with explicit self-correction prompt
                            self_correction_prompt = (
                                f"Your previous tool call '{tc.name}' failed with this error: {result.content}. "
                                f"Analyze it, adjust your plan, and try a different approach or tool."
                            )
                            if self.state_machine.current_state == TaskState.EXECUTING:
                                self.state_machine.transition_to(
                                    TaskState.PLANNING,
                                    reason=f"Self-correcting after error in '{tc.name}' (attempt {tool_error_retries}/{max_self_correction_retries})",
                                )
                                self.state_machine.transition_to(
                                    TaskState.EXECUTING,
                                    reason="Executing adjusted plan after tool error",
                                )
                            self.memory.add_message(
                                Message(
                                    role=Role.SYSTEM,
                                    content=self_correction_prompt,
                                    trust_level=TrustLevel.SYSTEM_INSTRUCTION,
                                )
                            )
                        else:
                            logger.warning(f"Exceeded max autonomous retries ({max_self_correction_retries}) for tool errors.")

                # If all tool calls in this batch succeeded, reset error retry counter
                if not iteration_had_error:
                    tool_error_retries = 0

                # If error retry budget exceeded, break out of loop to provide user with summary
                if iteration_had_error and tool_error_retries > max_self_correction_retries:
                    break

            # If iteration limit was hit without a final text response, synthesize from results
            if not final_content:
                if all_tool_results:
                    has_errors = any(r.is_error for r in all_tool_results)
                    if has_errors and tool_error_retries >= max_self_correction_retries:
                        err_summaries = "\n".join(f"- {r.name}: {r.content}" for r in all_tool_results if r.is_error)
                        final_content = (
                            f"I attempted to complete your request, but encountered persistent errors:\n\n{err_summaries}\n\n"
                            f"Could you please check the target or provide additional details?"
                        )
                    else:
                        summaries = "\n\n".join(r.content for r in all_tool_results)
                        final_content = f"I completed the requested tool operations:\n\n{summaries}"
                else:
                    final_content = "I reached my reasoning iteration limit before completing the response."
            else:
                final_content = strip_thought_tags(final_content)

            # State: VERIFYING (checking outcome and ensuring response integrity)
            if self.state_machine.current_state != TaskState.VERIFYING:
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying response content and execution integrity")

            # Check if all tools succeeded or if any tool returned an unrecoverable failure
            has_tool_errors = any(r.is_error for r in all_tool_results) if all_tool_results else False

            # State: COMPLETED or FAILED
            if has_tool_errors and tool_error_retries > max_self_correction_retries:
                self.state_machine.fail(reason="Tool operations failed after autonomous self-correction retries", metadata={"tool_errors": True})
            else:
                self.state_machine.transition_to(TaskState.COMPLETED, reason="Response verified and completed successfully")

            # Finalize working memory and compact into long-term summary ONLY for multi-step tasks.
            # Single-step tool calls already have the tool result in memory; injecting a redundant
            # summary would corrupt tests that assert exact message counts and add noise to context.
            if self.task_context and len(self.task_context.observations) >= 2:
                self.task_context.set_state(self.state_machine.current_state)
                summary_msg = self.task_context.finalize_and_extract_long_term_summary(success=(self.state_machine.current_state == TaskState.COMPLETED))
                if summary_msg:
                    self.memory.add_message(summary_msg)

            # 5. Check and prepend any pending proactive notifications
            proactive_summary = None
            if hasattr(self, "notifications") and self.notifications:
                proactive_summary = self.notifications.pop_notifications_summary()

            if proactive_summary:
                final_content = f"{proactive_summary}\n\n{final_content}"

            # 6. Persist final assistant turn in conversation memory
            final_msg = Message(role=Role.ASSISTANT, content=final_content)
            self.memory.add_message(final_msg)

            duration = time.perf_counter() - start_time
            logger.info(f"Turn processed successfully in {duration:.2f}s across {iterations} iteration(s) [Final State: {self.state_machine.current_state.value}]")

            recalled_info = [
                {
                    "source_conversation": r.conversation_id,
                    "timestamp": r.timestamp.isoformat(),
                    "content": r.content,
                    "score": r.score,
                }
                for r in recalled
            ]

            return AgentResponse(
                content=final_content,
                tool_calls=all_tool_calls if all_tool_calls else None,
                tool_results=all_tool_results if all_tool_results else None,
                is_done=True,
                metadata={
                    "duration_seconds": duration,
                    "iterations": iterations,
                    "request_count": iterations,
                    "tools_used": list(set(tc.name for tc in all_tool_calls)),
                    "success": (self.state_machine.current_state == TaskState.COMPLETED),
                    "provider": self.llm.provider_name,
                    "model": self.llm.model,
                    "cost_mode": getattr(self.settings, "cost_mode", "free_first"),
                    "recalled_memories": recalled_info,
                    "task_state": self.state_machine.current_state.value,
                    "state_history": [r.to_dict() for r in self.state_machine.history],
                    "failure_reason": self.state_machine.failure_reason,
                    "cognitive_phase": cognitive_decision.current_phase.value,
                    "confidence": cognitive_decision.confidence.to_dict(),
                    "routed_capability": routing_decision.selected_capability.value,
                },
            )

