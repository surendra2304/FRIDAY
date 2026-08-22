"""Core Agent orchestration loop with multi-step sequential tool calling for FRIDAY."""

import random
import re
import time
from typing import Any, Callable, Dict, List, Optional
from friday.agent.prompts import build_system_message
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from datetime import datetime
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
from friday.tools.builtin import (
    SystemInfoTool,
    TimeDateTool,
    CalculatorTool,
    FileReaderTool,
    FileListingTool,
    MemorySearchTool,
    ScreenSnapshotTool,
    ProposeComputerActionTool,
    OpenApplicationTool,
    TypeTextTool,
)
from friday.agent.state import TaskState, ReasoningStateMachine
from friday.agent.planner import TaskPlan, GoalDecomposer
from friday.agent.executor import TaskExecutionEngine, TaskExecutionResult, ExecutionProgress
from friday.agent.checkpoint import TaskCheckpoint, TaskCheckpointStore
from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.routing.capability_router import CapabilityRouter
from friday.vision.actions import ActionType
from friday.vision.detector import DeterministicActionDetector
from friday.vision.intent_detector import IntentDetector, ActionIntent
from friday.vision.computer_control import ComputerActionExecutor
from friday.vision.windows_input_driver import (
    check_desktop_interactivity,
)
from friday.memory.task_context import ActiveTaskContext
from friday.tools.registry import ToolRegistry
import uuid

logger = get_logger("agent.core")


class FridayAgent:
    """The central FRIDAY agent orchestrating reasoning, memory, multi-step tool calling, and output."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        memory: Optional[BaseMemory] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_tool_iterations: int = 5,
        tool_callback: Optional[Callable[[ToolCall, ToolResult], None]] = None,
        authorizer: Optional[BaseAuthorizer] = None,
        tool_timeout: float = 30.0,
        conversation_id: Optional[str] = None,
    ) -> None:
        self.settings = settings or get_settings()
        # Initialize UI Automation provider if enabled and on Windows
        self.ui_provider = None
        if self.settings.ui_automation_enabled:
            try:
                from friday.ui_automation.provider import WindowsUIAutomationProvider
                self.ui_provider = WindowsUIAutomationProvider()
            except Exception as e:
                logger.warning(f"UI Automation provider could not be initialized: {e}")
        self.llm = llm_provider or create_llm_provider(self.settings)
        self.memory = memory if memory is not None else create_memory(self.settings, conversation_id=conversation_id)
        self.tools = tool_registry or self._create_default_registry()
        self.max_tool_iterations = max(1, max_tool_iterations)
        self.tool_callback = tool_callback
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.tool_timeout = tool_timeout
        self.system_message = build_system_message(self.settings)
        self._processed_tool_ids: set = set()
        self.state_machine: ReasoningStateMachine = ReasoningStateMachine()
        self._current_plan: Optional[TaskPlan] = None
        self.task_context: Optional[ActiveTaskContext] = None
        self.checkpoint_store: TaskCheckpointStore = TaskCheckpointStore()
        self.cognitive_engine: CognitiveIntelligenceEngine = CognitiveIntelligenceEngine(
            llm_provider=self.llm,
            authorizer=self.authorizer,
        )
        self.capability_router: CapabilityRouter = CapabilityRouter()

        if self.settings.memory_retention_days:
            self.prune_memory(self.settings.memory_retention_days)

        logger.info(
            f"Initialized {self.settings.agent_name} with provider '{self.llm.provider_name}' "
            f"(model: '{self.llm.model}') and {len(self.tools.list_tools())} loaded tools. "
            f"Max tool iterations: {self.max_tool_iterations}."
        )

    @property
    def conversation_id(self) -> Optional[str]:
        """Return the active conversation identifier if supported by the memory backend."""
        if hasattr(self.memory, "active_conversation_id"):
            return self.memory.active_conversation_id
        return None

    def switch_conversation(self, conversation_id: str) -> None:
        """Switch the active conversation session."""
        self.memory.load_conversation(conversation_id)

    def create_new_conversation(self, title: Optional[str] = None) -> Optional[str]:
        """Create and activate a new conversation session."""
        return self.memory.create_conversation(title=title)

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List available conversation sessions."""
        return self.memory.list_conversations(limit=limit)

    def get_current_conversation(self) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for the current active conversation."""
        if self.conversation_id:
            return self.memory.get_conversation(self.conversation_id)
        return None

    def rename_conversation(self, new_title: str, conversation_id: Optional[str] = None) -> bool:
        """Rename an existing conversation."""
        target_id = conversation_id or self.conversation_id
        if target_id:
            return self.memory.rename_conversation(target_id, new_title)
        return False

    def delete_conversation(self, conversation_id: str, confirm: bool = True) -> bool:
        """Delete a conversation session and all its messages."""
        return self.memory.delete_conversation(conversation_id, confirm=confirm)

    def purge_all_memory(self, confirm: bool = True) -> int:
        """Permanently delete all stored conversations and messages."""
        return self.memory.purge_all(confirm=confirm)

    # Minimum fuzzy-match score an enumerated UI element must reach before FRIDAY
    # clicks it via UI Automation (element match confidence, independent of the
    # intent regex confidence which is always 1.0 for pattern hits).
    UIA_ELEMENT_CONFIDENCE_THRESHOLD = 0.60

    # Greeting fast-path: a bare greeting (optionally "there" + punctuation) is
    # answered conversationally without entering the cognitive loop, capability
    # routing, or tool-calling state machine. Addressed or compound requests
    # like "hello FRIDAY" or "hey, open notepad" intentionally do NOT match and
    # flow through the normal pipeline (the LLM handles them via the prompt's
    # GREETING HANDLING rule).
    _GREETING_PATTERN = re.compile(
        r"^\s*(?:hi|hello|hey|sup)\b(?:\s+there)?\s*[!.,?]*$",
        re.IGNORECASE,
    )

    _GREETING_RESPONSES = (
        "Hello {user_name}, how can I help you today?",
        "Hey {user_name}! What can I do for you?",
        "Hi {user_name}. What do you need?",
        "Hello {user_name}. I'm ready when you are.",
    )

    def _greeting_fast_path(self, clean_input: str) -> Optional[AgentResponse]:
        """Return a direct conversational greeting response, or None if not a greeting."""
        if not self._GREETING_PATTERN.match(clean_input):
            return None
        response = random.choice(self._GREETING_RESPONSES).format(user_name=self.settings.user_name)
        logger.info("Greeting fast-path: responding directly without cognitive loop or tools")
        self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Greeting recognized")
        self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing greeting response")
        self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating greeting response")
        self.state_machine.transition_to(TaskState.COMPLETED, reason="Greeting ready")
        self.memory.add_message(Message(role=Role.USER, content=clean_input))
        self.memory.add_message(Message(role=Role.ASSISTANT, content=response))
        return AgentResponse(
            content=response,
            is_done=True,
            metadata={
                "greeting_fast_path": True,
                "task_state": self.state_machine.current_state.value,
            },
        )

    def _execute_semantic_ui_action(self, intent_result, user_input: str) -> Optional[AgentResponse]:
        """Execute a high-confidence semantic UI action via the pywinauto provider.

        Returns an AgentResponse when the action was handled here (bypassing
        LLM/Vision entirely), or None to fall through to the normal pipeline.
        """
        parsed = intent_result.parsed_data or {}
        action = parsed.get("action_type")
        target = parsed.get("target", "")
        self.memory.add_message(Message(role=Role.USER, content=user_input))

        if action == "launch":
            executable = parsed.get("executable", "")
            # Proposal != Execution: application launches pass through the authorizer.
            shell_apps = {"cmd.exe", "powershell.exe", "wt.exe", "taskmgr.exe"}
            risk = SafetyLevel.SENSITIVE if executable.lower() in shell_apps else SafetyLevel.SAFE
            auth_req = AuthorizationRequest(
                tool_name="execute_computer_action",
                safety_level=risk,
                arguments={"action_type": "launch", "executable": executable},
                tool_call_id=str(uuid.uuid4()),
                purpose=f"Semantic UI launch of {target}",
                affected_resource="windows_desktop",
            )
            auth_resp = self.authorizer.authorize(auth_req)
            if auth_resp.decision != AuthorizationDecision.APPROVED:
                logger.warning(f"[UIA] Launch of '{target}' was not authorized ({auth_resp.decision}).")
                return None
            logger.info(f"[UIA] Launching application '{target}' ({executable})")
            if self.ui_provider.launch_application(executable):
                resp_content = f"Opened {target}."
                self.memory.add_message(Message(role=Role.ASSISTANT, content=resp_content))
                return AgentResponse(
                    content=resp_content,
                    is_done=True,
                    metadata={"ui_automation": True, "action": "launch", "target": target},
                )
            logger.warning(f"[UIA] Failed to launch application '{executable}'.")
            return None

        if action in ("click", "key_press"):
            element = self.ui_provider.find_element(target)
            if element and getattr(element, "confidence", 0) >= self.UIA_ELEMENT_CONFIDENCE_THRESHOLD:
                if self.ui_provider.click(element):
                    resp_content = f"Clicked the {target} via UI Automation."
                    self.memory.add_message(Message(role=Role.ASSISTANT, content=resp_content))
                    return AgentResponse(
                        content=resp_content,
                        is_done=True,
                        metadata={
                            "ui_automation": True,
                            "action": "click",
                            "target": target,
                            "element_confidence": getattr(element, "confidence", 0.0),
                            "intent_confidence": intent_result.confidence,
                        },
                    )
                logger.warning("[UIA] UI Automation click failed.")
            else:
                logger.warning(
                    f"[UIA] UI element '{target}' not found or below confidence threshold "
                    f"({getattr(element, 'confidence', 0.0):.2f} < {self.UIA_ELEMENT_CONFIDENCE_THRESHOLD})."
                )
        return None

    def clear_memory(self, confirm: bool = True) -> None:
        """Clear messages from the active conversation."""
        self.memory.clear(conversation_id=self.conversation_id, confirm=confirm)

    def prune_memory(self, retention_days: Optional[int] = None) -> int:
        """Prune messages older than the retention threshold."""
        days = retention_days or self.settings.memory_retention_days
        if days:
            return self.memory.prune_expired_messages(days)
        return 0

    def backup_database(self, backup_path: str) -> str:
        """Create an online hot backup of the persistent database to the target destination path."""
        return self.memory.backup(backup_path)

    def export_conversation(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """Export full conversation metadata and messages to a dictionary."""
        target_id = conversation_id or self.conversation_id
        if not target_id:
            raise ValueError("No active conversation to export.")
        return self.memory.export_conversation_to_dict(target_id)

    def search_memory(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MemorySearchResult]:
        """Search historical conversation messages."""
        return self.memory.search(
            query=query,
            conversation_id=conversation_id,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )

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
        return registry

    def _execute_single_tool_call_internal(self, tc: ToolCall, timeout: Optional[float] = None) -> ToolResult:
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

    def _execute_single_tool_call(self, tc: ToolCall, timeout: Optional[float] = None) -> ToolResult:
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

    def _retrieve_relevant_memories(self, query: str) -> List[MemorySearchResult]:
        """Controlled retrieval of relevant historical context based on settings."""
        if not getattr(self.settings, "enable_auto_recall", True):
            return []

        mode = getattr(self.settings, "retrieval_mode", "hybrid").lower().strip()
        if mode in ("none", "disabled", "false", ""):
            return []

        clean_query = query.strip()
        if not should_retrieve_memory(clean_query):
            return []

        limit = getattr(self.settings, "max_recalled_memories", 3)
        threshold = getattr(self.settings, "recall_similarity_threshold", 0.6)
        max_chars = getattr(self.settings, "max_recall_chars", 1000)

        results: List[MemorySearchResult] = []
        try:
            if mode == "semantic":
                sem_res = self.memory.search_semantic(clean_query, limit=limit, threshold=threshold)
                results = [
                    MemorySearchResult(
                        conversation_id=sr.conversation_id,
                        conversation_title=sr.metadata.get("conversation_title", ""),
                        message_id=sr.message_id or sr.record_id,
                        role=Role(sr.metadata.get("role", "assistant")),
                        content=sr.source_text,
                        timestamp=sr.created_at,
                        score=sr.score,
                    )
                    for sr in sem_res
                ]
            elif mode == "fts":
                results = self.memory.search(clean_query, limit=limit)
            else:  # hybrid
                results = self.memory.search_hybrid(clean_query, limit=limit)
        except Exception as e:
            logger.warning(f"Auto memory recall failed: {e}")
            return []

        filtered: List[MemorySearchResult] = []
        total_chars = 0
        for r in results:
            if r.content.strip().lower() == clean_query.lower():
                continue
            if total_chars + len(r.content) > max_chars:
                break
            filtered.append(r)
            total_chars += len(r.content)

        return filtered

    @property
    def current_state(self) -> TaskState:
        """Return the current reasoning state of the agent."""
        return self.state_machine.current_state

    @property
    def current_plan(self) -> Optional[TaskPlan]:
        """Return the active TaskPlan if one exists."""
        return self._current_plan

    def create_plan(self, goal: str, steps: Optional[List[Dict[str, Any]]] = None) -> TaskPlan:
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
        plan: Optional[TaskPlan] = None,
        on_step_progress: Optional[Callable[[ExecutionProgress], None]] = None,
        step_timeout_seconds: Optional[float] = None,
        cancellation_token: Optional[Any] = None,
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

    def pause_current_task(self, reason: str = "Interrupted by user") -> Optional[TaskCheckpoint]:
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

    def resume_task(self, task_id: Optional[str] = None) -> TaskExecutionResult:
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
            return greeting_response

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

        # 4. State: PLANNING (constructing working context and evaluating tool schemas)
        self.state_machine.transition_to(TaskState.PLANNING, reason="Evaluating context and determining action plan")
        working_context: List[Message] = [base_sys_msg] + self.memory.get_context_window(
            self.settings.memory_max_messages
        )

        # 5. Retrieve registered tool schemas
        tool_schemas = self.tools.get_schemas() if self.tools.list_tools() else None

        all_tool_calls: List[ToolCall] = []
        all_tool_results: List[ToolResult] = []
        final_content = ""
        iterations = 0

        # 6. Multi-step Reasoning & Tool-calling Loop
        while iterations < self.max_tool_iterations:
            iterations += 1
            logger.debug(f"Agent decision iteration {iterations}/{self.max_tool_iterations}")

            # Rebuild working context from memory dynamically to maintain precise dialogue history
            working_context = [base_sys_msg] + self.memory.get_context_window(
                self.settings.memory_max_messages
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

            # If model returned direct answer without requesting tools -> proceed to verification
            if not assistant_msg.tool_calls:
                final_content = assistant_msg.content or "Task completed."
                break

            # Model requested one or more tool calls -> State: EXECUTING
            if self.state_machine.current_state != TaskState.EXECUTING:
                self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing {len(assistant_msg.tool_calls)} requested tool call(s)")

            logger.info(f"Iteration {iterations}: Model requested {len(assistant_msg.tool_calls)} tool call(s)")
            
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

            batch_results: List[ToolResult] = []
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

                # Verify step execution outcome (log any tool error detected)
                if result.is_error:
                    logger.warning(f"Step verification notice for '{tc.name}': tool returned an error — {result.content[:120]!r}")

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

        # If iteration limit was hit without a final text response, synthesize from results
        if not final_content:
            if all_tool_results:
                logger.warning(f"Agent reached max iterations ({self.max_tool_iterations}). Summarizing executed tools.")
                summaries = "\n\n".join(r.content for r in all_tool_results)
                final_content = f"I completed the requested tool operations:\n\n{summaries}"
            else:
                final_content = "I reached my reasoning iteration limit before completing the response."

        # State: VERIFYING (checking outcome and ensuring response integrity)
        self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying response content and execution integrity")

        # Check if all tools succeeded or if any tool returned an unrecoverable failure
        has_tool_errors = any(r.is_error for r in all_tool_results) if all_tool_results else False

        # State: COMPLETED or FAILED
        if has_tool_errors and not final_content:
            self.state_machine.fail(reason="All tool operations failed during execution", metadata={"tool_errors": True})
        else:
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Response verified and completed successfully")

        # Finalize working memory and compact into long-term summary ONLY for multi-step tasks.
        # Single-step tool calls already have the tool result in memory; injecting a redundant
        # summary would corrupt tests that assert exact message counts and add noise to context.
        if self.task_context and len(self.task_context.observations) >= 2:
            self.task_context.set_state(self.state_machine.current_state)
            summary_msg = self.task_context.finalize_and_extract_long_term_summary(success=(not has_tool_errors))
            if summary_msg:
                self.memory.add_message(summary_msg)

        # 5. Persist final assistant turn in conversation memory
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
                "success": (not has_tool_errors) and (self.state_machine.current_state == TaskState.COMPLETED),
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

    def get_history(self) -> List[Message]:
        """Retrieve stored conversation messages."""
        return self.memory.get_messages()

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status information about the agent."""
        # Get safe LLM active project label if available
        active_project = "PRIMARY"
        if hasattr(self.llm, "credential_pool") and self.llm.credential_pool:
            try:
                active_project = self.llm.credential_pool.get_active_label()
            except Exception:
                active_project = "UNKNOWN"

        # Check embedding status
        embedding_status = "AVAILABLE"
        if self.settings.embedding_provider == "gemini":
            from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
            if time.time() < GeminiEmbeddingProvider._circuit_breaker_cooldown_until:
                embedding_status = "QUOTA COOLDOWN"

        status = {
            "agent_name": self.settings.agent_name,
            "user_name": self.settings.user_name,
            "provider": self.llm.provider_name,
            "model": self.llm.model,
            "active_project": active_project,
            "task_state": self.state_machine.current_state.value,
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": self.settings.embedding_model,
            "embedding_status": embedding_status,
            "memory_backend": self.settings.memory_backend,
            "memory_messages": len(self.memory.get_messages()),
            "memory_capacity": self.settings.memory_max_messages,
            "max_tool_iterations": self.max_tool_iterations,
            "active_plan": self._current_plan.to_dict() if self._current_plan else None,
            "active_task_context": self.task_context.to_dict() if self.task_context else None,
            "tools_registered": [f"{t.name} ({t.safety_level.value})" for t in self.tools.list_tools()],
        }
        if self.conversation_id:
            status["conversation_id"] = self.conversation_id
        return status

    def close(self) -> None:
        """Deterministically close all agent resources, worker pools, and memory stores."""
        if hasattr(self, "tools") and hasattr(self.tools, "_shared_executor") and self.tools._shared_executor:
            try:
                self.tools._shared_executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logger.debug(f"Error shutting down tool executor: {e}")

        if hasattr(self, "task_context") and self.task_context:
            self.task_context.clear()

        if hasattr(self, "memory") and hasattr(self.memory, "close"):
            try:
                self.memory.close()
            except Exception as e:
                logger.debug(f"Error closing memory: {e}")
