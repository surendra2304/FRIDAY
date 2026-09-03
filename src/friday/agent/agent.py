import os
import random
import re
import subprocess
import time
import warnings
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus

# Suppress noisy upstream COM threading and GenAI AFC warnings
warnings.filterwarnings("ignore", message=".*Revert to STA COM threading mode.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*automatic function calling.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*", category=UserWarning)
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
    LocationMapsTool,
    ManageTasksTool,
    ManageVolumeTool,
    ManageWindowsTool,
    MediaControlTool,
    MemorySearchTool,
    NewsTool,
    OpenApplicationTool,
    OpenWebsiteTool,
    ProposeComputerActionTool,
    ReadActiveWindowTextTool,
    ReadOwnCodebaseTool,
    ReadScreenTextTool,
    RememberFactTool,
    ReplaceFileContentTool,
    RunTestsTool,
    ScreenPredictionTool,
    ScreenSnapshotTool,
    SendEmailTool,
    DraftEmailTool,
    SynthesizeInformationTool,
    SystemControlTool,
    SystemInfoTool,
    SystemPowerControlTool,
    TimeDateTool,
    ToggleBluetoothTool,
    ToggleDarkModeTool,
    ToggleWifiTool,
    TypeTextTool,
    VerifyFaceIdentityTool,
    EnrollFaceIdentityTool,
    WeatherTool,
    WebSearchTool,
    WikipediaTool,
    WriteCodeFileTool,
    YouTubeTool,
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

logger = get_logger("agent.core")




from friday.agent.mixins import MemoryMixin, FastPathMixin, ToolExecutionMixin, TaskMixin, CognitiveMixin

class FridayAgent(MemoryMixin, FastPathMixin, ToolExecutionMixin, TaskMixin, CognitiveMixin):
    """The central FRIDAY agent orchestrating reasoning, memory, multi-step tool calling, and output."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm_provider: BaseLLMProvider | None = None,
        memory: BaseMemory | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_iterations: int = 5,
        tool_callback: Callable[[ToolCall, ToolResult], None] | None = None,
        authorizer: BaseAuthorizer | None = None,
        tool_timeout: float = 30.0,
        conversation_id: str | None = None,
        skill_registry: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._ui_provider = None
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
        self._current_plan: TaskPlan | None = None
        self.task_context: ActiveTaskContext | None = None
        self.checkpoint_store: TaskCheckpointStore = TaskCheckpointStore()
        self.cognitive_engine: CognitiveIntelligenceEngine = CognitiveIntelligenceEngine(
            llm_provider=self.llm,
            authorizer=self.authorizer,
        )
        self.capability_router: CapabilityRouter = CapabilityRouter()
        self._agent_registry: AgentRegistry | None = None
        self._task_decomposer: TaskDecomposer | None = None
        self._agent_router: AgentRouter | None = None
        self.notifications: NotificationManager = NotificationManager()
        self._skill_registry: Any | None = skill_registry

        if self.settings.memory_retention_days:
            self.prune_memory(self.settings.memory_retention_days)

        logger.info(
            f"Initialized {self.settings.agent_name} with provider '{self.llm.provider_name}' "
            f"(model: '{self.llm.model}') and {len(self.tools.list_tools())} loaded tools. "
            f"Max tool iterations: {self.max_tool_iterations}."
        )

    @property
    def ui_provider(self):
        """Lazy loader for UI Automation provider."""
        if self._ui_provider is None and self.settings.ui_automation_enabled:
            try:
                from friday.ui_automation.provider import WindowsUIAutomationProvider
                self._ui_provider = WindowsUIAutomationProvider()
            except Exception as e:
                logger.warning(f"UI Automation provider could not be initialized: {e}")
        return self._ui_provider

    @ui_provider.setter
    def ui_provider(self, value) -> None:
        self._ui_provider = value

    @property
    def agent_registry(self) -> AgentRegistry:
        """Lazy-loaded specialist agent registry."""
        if getattr(self, "_agent_registry", None) is None:
            self._agent_registry = self._init_default_agent_registry()
        assert self._agent_registry is not None
        return self._agent_registry

    @property
    def task_decomposer(self) -> TaskDecomposer:
        """Lazy-loaded task decomposer."""
        if getattr(self, "_task_decomposer", None) is None:
            self._task_decomposer = TaskDecomposer(llm_provider=self.llm)
        assert self._task_decomposer is not None
        return self._task_decomposer

    @property
    def agent_router(self) -> AgentRouter:
        """Lazy-loaded agent router."""
        if getattr(self, "_agent_router", None) is None:
            self._agent_router = AgentRouter(registry=self.agent_registry)
        assert self._agent_router is not None
        return self._agent_router

    @property
    def skill_registry(self):
        """Lazy-loaded skill registry."""
        if getattr(self, "_skill_registry", None) is None:
            try:
                from friday.skills.registry import skill_registry as default_skill_reg
                self._skill_registry = default_skill_reg
            except Exception:
                self._skill_registry = None
        return self._skill_registry

    @skill_registry.setter
    def skill_registry(self, value) -> None:
        self._skill_registry = value

    @property
    def conversation_id(self) -> str | None:
        """Return the active conversation identifier if supported by the memory backend."""
        if hasattr(self.memory, "active_conversation_id"):
            return self.memory.active_conversation_id
        return None

    @property
    def jarvis_orchestrator(self):
        """Lazy-loaded Microsoft JARVIS / HuggingGPT task graph orchestrator."""
        if getattr(self, "_jarvis_orchestrator", None) is None:
            from friday.planning.orchestrator import JarvisOrchestrator
            orch = JarvisOrchestrator(
                tool_registry=self.tools,
                llm_provider=self.llm,
                authorizer=self.authorizer,
            )
            # Register specialist agents into executor catalog
            if hasattr(self, "agent_registry") and self.agent_registry:
                try:
                    for agent in self.agent_registry.list_agents():
                        orch.register_specialist_agent(agent, getattr(agent, "role", "specialist"))
                except Exception as e:
                    logger.debug(f"Specialist agent registration: {e}")
            self._jarvis_orchestrator = orch
        return self._jarvis_orchestrator

    def execute_complex_task(self, goal: str, context: dict | None = None) -> AgentResponse:
        """Execute a complex multi-step user goal using Microsoft JARVIS task graph orchestration."""
        import time
        start_time = time.perf_counter()
        synth_response = self.jarvis_orchestrator.execute_goal(goal, context=context)
        duration = time.perf_counter() - start_time
        return AgentResponse(
            content=synth_response.content,
            is_done=True,
            metadata={
                "jarvis_orchestration": True,
                "graph_id": synth_response.graph_id,
                "total_tasks": synth_response.total_tasks,
                "completed_tasks": synth_response.completed_tasks,
                "failed_tasks": synth_response.failed_tasks,
                "duration_seconds": duration,
                "is_successful": synth_response.is_successful,
            },
        )









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


    _NOTEPAD_TYPE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:open|launch|start)?\s*(?:a\s+)?(?:new\s+)?(?:tab\s+in\s+)?(?:the\s+)?note\s*pad(?:\s+(?:in\s+)?(?:a\s+)?new\s+tab)?(?:\s+and)?\s+(?:type|write|say|enter)\s+(?P<text>.+?)\s*$",
        re.IGNORECASE,
    )
    _OPEN_APP_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:open|launch|start|run|oh\s*,?\s*been|oh\s*,?\s*open|oh\s*!?\s*pen|o\s*pen|pen)\s+(?:the\s+)?(?P<app>[a-zA-Z0-9\s_\-\.]+?)(?:\s+(?:app|application|program|window))?[\.\!]*\s*$",
        re.IGNORECASE,
    )
    _CHROME_SEARCH_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:(?:open|launch|start)\s+)?(?:chrome|google chrome)\s+and\s+search\s+(?P<query>.+?)\s*$|"
        r"^\s*(?:please\s+)?search\s+(?P<query2>.+?)\s+in\s+(?:chrome|google chrome)\s*$",
        re.IGNORECASE,
    )
    _CLOSE_CHROME_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:close|quit|exit)\s+(?:google\s+)?chrome\.?\s*$",
        re.IGNORECASE,
    )
    _SETTINGS_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:open|launch|start)\s+(?:windows\s+)?settings\.?\s*$",
        re.IGNORECASE,
    )
    _WINDOWS_UPDATE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:(?:check|see|look)\s+(?:if\s+)?(?:there\s+are\s+)?(?:any\s+)?updates(?:\s+for\s+my\s+laptop)?|"
        r"are\s+there\s+(?:any\s+)?updates(?:\s+for\s+my\s+laptop)?|"
        r"(?:if\s+)?there\s+are\s+(?:any\s+)?updates(?:\s+for\s+my\s+laptop)?|"
        r"(?:open|launch|start)\s+windows\s+update)[\.\?]?\s*$",
        re.IGNORECASE,
    )
    _TIME_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:what(?:'s| is)?|tell me)\s+(?:the\s+)?time(?:\s+now)?\??\s*$|"
        r"^\s*(?:please\s+)?what\s+time\s+(?:(?:is\s+)?it|it\s+is)\??\s*$",
        re.IGNORECASE,
    )
    _LAPTOP_SPECS_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:(?:tell|show)\s+(?:me\s+)?(?:its|my laptop(?:'s)?)\s+specs|"
        r"what\s+are\s+(?:the\s+)?specs\s+of\s+my\s+laptop|"
        r"tell\s+(?:its|my laptop(?:'s)?)\s+specs|"
        r"tell\s+(?:me\s+)?(?:its|the)\s+specs)\??\s*$",
        re.IGNORECASE,
    )
    _LAPTOP_IDENTITY_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:which|what)\s+laptop\s+is\s+this\??\s*$",
        re.IGNORECASE,
    )
    _LISTENING_CHECK_PATTERN = re.compile(
        r"^\s*(?:are\s+you\s+listening|can\s+you\s+hear\s+me)\??\s*$",
        re.IGNORECASE,
    )
    _VOLUME_UP_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:increase|raise|turn\s+up)\s+(?:the\s+)?volume"
        r"(?:\s+(?:by\s+)?(?P<step>\d{1,3})\s*(?:%|percent)?)?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _VOLUME_DOWN_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:decrease|reduce|lower|turn\s+down)\s+(?:the\s+)?volume"
        r"(?:\s+(?:by\s+)?(?P<step>\d{1,3})\s*(?:%|percent)?)?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _SET_VOLUME_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:set\s+)?volume\s+(?:to\s+)?(?P<level>\d{1,3})\s*(?:%|percent)?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _MUTE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?P<action>mute|unmute)(?:\s+the\s+volume)?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _BATTERY_PATTERN = re.compile(
        r"^\s*(?:please\s+)?"
        r"(?:what(?:'s|\s+is)\s+(?:my\s+)?battery(?:\s+(?:level|percentage|status))?"
        r"|how\s+much\s+battery(?:\s+do\s+i\s+have)?"
        r"|(?:check\s+)?(?:my\s+)?battery\s+(?:level|percentage|status))"
        r"[\.\?]?\s*$",
        re.IGNORECASE,
    )
    _SCREEN_DESCRIBE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:what'?s?\s+(?:currently\s+)?on\s+(?:my\s+)?(?:the\s+)?screen"
        r"|describe\s+(?:my\s+)?(?:the\s+)?screen|what\s+do\s+you\s+see)[\.\?]?\s*$",
        re.IGNORECASE,
    )
    _ACTIVE_WINDOW_TYPE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:(?:now|just|okay|ok|yeah|yes)\s*,?\s*)*(?:type|write|enter)\s+(?P<text>.+?)(?:\s+(?:here|in\s+this|at\s+the\s+cursor|where\s+the\s+mouse\s+pointer\s+is(?:\s+there)?|where\s+i\s+am))?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _CONTROL_LIGHT_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:turn|switch|dim|set)\s+(?:the\s+)?lights?\s+(?P<action>on|off|up|down|to\s+(?P<brightness>\d{1,3})\s*%?)[\.\!]?\s*$|"
        r"^\s*(?:please\s+)?dim\s+(?:the\s+)?lights?(?:\s+to\s+(?P<dim_brightness>\d{1,3})\s*%?)?[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _CONTROL_PLUG_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?P<action>on|off)\s+(?:the\s+)?(?:smart\s+plug|plug|switch)(?:\s+(?:for|called|named)?\s*(?P<device_id>[\w\-_]+))?[\.\!]?\s*$|"
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?:the\s+)?(?:smart\s+plug|plug|switch)(?:\s+(?:for|called|named)?\s*(?P<device_id2>[\w\-_]+))?\s+(?P<action2>on|off)[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _TOGGLE_DARK_MODE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:turn|switch|enable|set|toggle)\s+(?:on\s+)?(?:windows\s+)?(?P<mode>dark\s+mode|light\s+mode)(?:\s+on|\s+off)?[\.\!]?\s*$|"
        r"^\s*(?:please\s+)?(?:turn\s+off\s+dark\s+mode|disable\s+dark\s+mode)[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _TOGGLE_BLUETOOTH_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?P<action>on|off)\s+(?:the\s+)?bluetooth[\.\!]?\s*$|"
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?:the\s+)?bluetooth\s+(?P<action2>on|off)[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _TOGGLE_WIFI_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?P<action>on|off)\s+(?:the\s+)?(?:wi-?fi|wifi|wireless)[\.\!]?\s*$|"
        r"^\s*(?:please\s+)?(?:turn|switch)\s+(?:the\s+)?(?:wi-?fi|wifi|wireless)\s+(?P<action2>on|off)[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _STATUS_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:give\s+me\s+(?:a\s+)?)?(?:status\s+of\s+everything|status\s+of\s+all\s+agents|ecosystem\s+status|health\s+of\s+agents|health\s+of\s+all\s+systems|subsystems?\s+status)[\.\!]?\s*$",
        re.IGNORECASE,
    )
    _BRIEFING_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:brief\s+me|morning\s+briefing|evening\s+briefing|daily\s+briefing)[\.\!]?\s*$",
        re.IGNORECASE,
    )























    @property
    def current_state(self) -> TaskState:
        """Return the current reasoning state of the agent."""
        return self.state_machine.current_state

    @property
    def current_plan(self) -> TaskPlan | None:
        """Return the active TaskPlan if one exists."""
        return self._current_plan







    def get_history(self) -> list[Message]:
        """Retrieve stored conversation messages."""
        return self.memory.get_messages()

    def get_status(self) -> dict[str, Any]:
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

        if hasattr(self, "_agent_registry") and self._agent_registry:
            try:
                self._agent_registry.close()
            except Exception as e:
                logger.debug(f"Error closing agent registry: {e}")

        if hasattr(self, "memory") and hasattr(self.memory, "close"):
            try:
                self.memory.close()
            except Exception as e:
                logger.debug(f"Error closing memory: {e}")
