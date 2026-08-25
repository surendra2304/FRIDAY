"""Core Agent orchestration loop with multi-step sequential tool calling for FRIDAY."""

import random
import re
import os
import subprocess
import time
from urllib.parse import quote_plus
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
    CloseApplicationTool,
    ManageVolumeTool,
    SystemPowerControlTool,
    ManageWindowsTool,
    WebSearchTool,
    FetchWebpageTool,
    FileOperationsTool,
    ExecuteCommandTool,
    ReadScreenTextTool,
    FindOnScreenTool,
    GetActiveAppContextTool,
    ReadActiveWindowTextTool,
    GitStatusTool,
    GitCommitTool,
    GitPushTool,
    ListGitHubIssuesTool,
    CreateGitHubIssueTool,
    GetSystemResourcesTool,
    KillProcessTool,
    LaunchApplicationTool,
    SystemControlTool,
    HealthCheckTool,
    WriteCodeFileTool,
    RunTestsTool,
    CreateGitBranchTool,
    ControlLightTool,
    ControlPlugTool,
    FetchWebpageContentTool,
    SynthesizeInformationTool,
    ToggleDarkModeTool,
    ToggleBluetoothTool,
    ToggleWifiTool,
    GetTodaysEventsTool,
    SendEmailTool,
    ScreenPredictionTool,
)
from friday.agent.state import TaskState, ReasoningStateMachine
from friday.agent.planner import TaskPlan, GoalDecomposer
from friday.agent.executor import TaskExecutionEngine, TaskExecutionResult, ExecutionProgress
from friday.agents.base_agent import AgentTask, BaseAgent
from friday.agents.decomposer import TaskDecomposer
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.observability.notifications import NotificationManager
from friday.agent.checkpoint import TaskCheckpoint, TaskCheckpointStore
from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.routing.capability_router import CapabilityRouter
from friday.vision.actions import ActionType
from friday.vision.detector import DeterministicActionDetector
from friday.vision.intent_detector import IntentDetector, ActionIntent
from friday.vision.computer_control import ComputerActionExecutor
from friday.vision.windows_input_driver import (
    WindowsNativeInputDriver,
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
        self._current_plan: Optional[TaskPlan] = None
        self.task_context: Optional[ActiveTaskContext] = None
        self.checkpoint_store: TaskCheckpointStore = TaskCheckpointStore()
        self.cognitive_engine: CognitiveIntelligenceEngine = CognitiveIntelligenceEngine(
            llm_provider=self.llm,
            authorizer=self.authorizer,
        )
        self.capability_router: CapabilityRouter = CapabilityRouter()
        self._agent_registry: Optional[AgentRegistry] = None
        self._task_decomposer: Optional[TaskDecomposer] = None
        self._agent_router: Optional[AgentRouter] = None
        self.notifications: NotificationManager = NotificationManager()

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
        return self._agent_registry

    @property
    def task_decomposer(self) -> TaskDecomposer:
        """Lazy-loaded task decomposer."""
        if getattr(self, "_task_decomposer", None) is None:
            self._task_decomposer = TaskDecomposer(llm_provider=self.llm)
        return self._task_decomposer

    @property
    def agent_router(self) -> AgentRouter:
        """Lazy-loaded agent router."""
        if getattr(self, "_agent_router", None) is None:
            self._agent_router = AgentRouter(registry=self.agent_registry)
        return self._agent_router

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

    _NOTEPAD_TYPE_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:open|launch|start)?\s*(?:a\s+)?(?:new\s+)?(?:tab\s+in\s+)?(?:the\s+)?note\s*pad(?:\s+(?:in\s+)?(?:a\s+)?new\s+tab)?(?:\s+and)?\s+(?:type|write|say|enter)\s+(?P<text>.+?)\s*$",
        re.IGNORECASE,
    )
    _OPEN_APP_PATTERN = re.compile(
        r"^\s*(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+)?(?P<app>[a-zA-Z0-9\s_\-\.]+?)(?:\s+(?:app|application|program|window))?[\.\!]?\s*$",
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

    def _launch_process(self, executable: str, *args: str) -> None:
        """Launch a desktop process without blocking the agent turn."""
        try:
            subprocess.Popen([executable, *args], shell=False)
        except Exception:
            if args:
                subprocess.Popen(["cmd.exe", "/c", "start", "", executable, *args], shell=False)
            else:
                os.startfile(executable)

    def _focus_window_for_direct_action(self, title_substring: str, timeout: float = 3.0) -> bool:
        """Best-effort focus for a newly opened desktop window with Win32 foreground activation."""
        import ctypes
        deadline = time.time() + max(0.1, timeout)
        needle = title_substring.lower()
        while time.time() < deadline:
            try:
                from pywinauto import Desktop

                windows = Desktop(backend="uia").windows()
                matches = [w for w in windows if needle in (w.window_text() or "").lower()]
                if matches:
                    w = matches[0]
                    hwnd = getattr(w, "handle", None)
                    if hwnd:
                        try:
                            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                        except Exception:
                            pass
                    w.set_focus()
                    time.sleep(0.4)  # Allow RichEdit / Tab to become ready for keystrokes
                    return True
            except Exception as e:
                logger.debug(f"Direct action focus attempt failed for '{title_substring}': {e}")
            time.sleep(0.15)
        return False

    def _dedupe_repeated_query_tail(self, query: str) -> str:
        """Trim accidental duplicated voice fragments from a search query."""
        words = query.strip().split()
        if len(words) < 4:
            return query.strip()
        for size in range(len(words) // 2, 1, -1):
            if words[-size:] == words[-2 * size:-size]:
                return " ".join(words[:-size]).strip()
        return query.strip()

    def _adjust_volume(
        self,
        delta: Optional[int] = None,
        set_to: Optional[int] = None,
    ) -> str:
        """Raise/lower or absolutely set master volume via pycaw; returns spoken result."""
        from friday.tools.builtin.os_control import _get_endpoint_volume

        vol = _get_endpoint_volume()
        current = int(round(float(vol.GetMasterVolumeLevelScalar()) * 100))
        if set_to is not None:
            target = max(0, min(100, int(set_to)))
        else:
            target = max(0, min(100, current + int(delta or 10)))
        if target == current:
            return f"Volume is already at {current}%."
        vol.SetMasterVolumeLevelScalar(target / 100.0, None)
        direction = "raised" if target > current else "lowered"
        return f"Volume {direction} from {current}% to {target}%."

    def _read_battery_status(self) -> str:
        """Read battery level/charging state via Win32 GetSystemPowerStatus."""
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("Reserved1", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return "I could not read the battery status on this machine."
        pct = status.BatteryLifePercent
        charging = status.ACLineStatus == 1
        if pct == 255:
            base = "This machine has no battery reported (desktop or missing sensor)."
            return base
        state = "charging" if charging else "on battery"
        remaining = ""
        if status.BatteryLifeTime > 0 and not charging:
            mins = status.BatteryLifeTime // 60
            remaining = f" About {mins} minute{'s' if mins != 1 else ''} remaining."
        return f"Battery is at {pct}% and {state}.{remaining}"

    def _complete_fast_path(
        self,
        clean_input: str,
        start_time: float,
        action_key: str,
        planning_reason: str,
        executing_reason: str,
        action: Callable[[], str],
        verifying_reason: str = "Checking direct action result",
    ) -> AgentResponse:
        """Run a local deterministic fast-path action and build the final response."""
        self.memory.add_message(Message(role=Role.USER, content=clean_input))
        self.state_machine.transition_to(TaskState.PLANNING, reason=planning_reason)
        self.state_machine.transition_to(TaskState.EXECUTING, reason=executing_reason)
        try:
            content = action()
            success = True
        except Exception as e:
            logger.warning(f"Fast-path '{action_key}' failed: {e}")
            content = f"I could not complete that: {type(e).__name__}."
            success = False
        self.state_machine.transition_to(TaskState.VERIFYING, reason=verifying_reason)
        self.state_machine.transition_to(
            TaskState.COMPLETED if success else TaskState.FAILED, reason=content
        )
        self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
        return AgentResponse(
            content=content,
            is_done=True,
            metadata={
                "fast_path": True,
                "direct_desktop_action": action_key,
                "success": success,
                "duration_seconds": time.perf_counter() - start_time,
                "task_state": self.state_machine.current_state.value,
            },
        )

    def _format_local_specs(self) -> str:
        """Return concise laptop specs for spoken responses."""
        import os as _os
        import platform
        import sys as _sys

        bits = [
            f"{platform.system()} {platform.release()}",
            platform.machine(),
            f"{_os.cpu_count() or 1} logical CPU cores",
        ]
        processor = platform.processor()
        if processor:
            bits.insert(2, processor)
        try:
            if _sys.platform == "win32":
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    bits.append(f"{round(stat.ullTotalPhys / (1024**3), 1)} GB RAM")
        except Exception:
            pass
        return "This laptop is running " + ", ".join(bits) + "."

    def _direct_desktop_action_fast_path(self, clean_input: str, start_time: float) -> Optional[AgentResponse]:
        """Execute common laptop-control commands deterministically.

        This avoids routing simple desktop actions through a general model,
        which can otherwise summarize, search the web, or mix previous turns
        instead of performing the concrete Windows sequence.
        """
        notepad_match = self._NOTEPAD_TYPE_PATTERN.match(clean_input)
        if notepad_match:
            payload = notepad_match.group("text").strip()
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct Notepad typing command")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Opening Notepad and typing text")
            try:
                self._launch_process("notepad.exe")
                self._focus_window_for_direct_action("Notepad")
                typed = WindowsNativeInputDriver().type_text(payload)
            except Exception as e:
                typed = False
                logger.warning(f"Direct Notepad typing failed: {e}")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking direct Notepad action result")
            content = "Done." if typed else "I opened Notepad, but I could not reliably type into it."
            self.state_machine.transition_to(TaskState.COMPLETED if typed else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "notepad_type",
                    "success": typed,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        chrome_match = self._CHROME_SEARCH_PATTERN.match(clean_input)
        if chrome_match:
            query = self._dedupe_repeated_query_tail(
                chrome_match.group("query") or chrome_match.group("query2") or ""
            )
            if not query:
                return None
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct Chrome search command")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Opening Chrome search URL")
            ok = False
            try:
                self._launch_process("chrome.exe", f"https://www.google.com/search?q={quote_plus(query)}")
                ok = True
            except Exception as e:
                logger.warning(f"Chrome direct URL launch failed; trying focus/type fallback: {e}")
                try:
                    self._launch_process("chrome.exe")
                    self._focus_window_for_direct_action("Chrome")
                    driver = WindowsNativeInputDriver()
                    ok = (
                        driver.hotkey(["ctrl", "l"])
                        and driver.type_text(query)
                        and driver.press_key("enter")
                    )
                except Exception as fallback_error:
                    logger.warning(f"Chrome search fallback failed: {fallback_error}")
                    ok = False
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking direct Chrome search result")
            content = "Done." if ok else "I could not reliably complete the Chrome search."
            self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "chrome_search",
                    "query": query,
                    "success": ok,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._CLOSE_CHROME_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct close Chrome command")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Closing Chrome")
            ok = False
            try:
                result = subprocess.run(
                    ["taskkill.exe", "/IM", "chrome.exe", "/T"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                combined = f"{result.stdout}\n{result.stderr}".lower()
                ok = result.returncode == 0 or "not found" in combined
            except Exception as e:
                logger.warning(f"Closing Chrome failed: {e}")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking Chrome close request")
            content = "Done." if ok else "I could not close Chrome."
            self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "close_chrome",
                    "success": ok,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        open_app_match = self._OPEN_APP_PATTERN.match(clean_input)
        if open_app_match:
            app_raw = open_app_match.group("app").strip().lower()
            if app_raw in IntentDetector.APP_LAUNCH_MAP:
                exe = IntentDetector.APP_LAUNCH_MAP[app_raw]
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.state_machine.transition_to(TaskState.PLANNING, reason=f"Direct launch command for {app_raw}")
                self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Opening {app_raw}")
                ok = False
                try:
                    if exe.startswith("ms-"):
                        self._launch_process("explorer.exe", exe)
                    else:
                        self._launch_process(exe)
                    ok = True
                except Exception as e:
                    logger.warning(f"Opening '{app_raw}' failed: {e}")
                self.state_machine.transition_to(TaskState.VERIFYING, reason=f"Checking {app_raw} launch")
                content = "Done." if ok else f"I could not open {app_raw}."
                self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
                self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                return AgentResponse(
                    content=content,
                    is_done=True,
                    metadata={
                        "fast_path": True,
                        "direct_desktop_action": f"open_{app_raw}",
                        "success": ok,
                        "duration_seconds": time.perf_counter() - start_time,
                        "task_state": self.state_machine.current_state.value,
                    },
                )

        if self._SETTINGS_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct Settings command")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Opening Windows Settings")
            ok = False
            try:
                self._launch_process("explorer.exe", "ms-settings:")
                ok = True
            except Exception as e:
                logger.warning(f"Opening Settings failed: {e}")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking Settings launch")
            content = "Done." if ok else "I could not open Settings."
            self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "open_settings",
                    "success": ok,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._WINDOWS_UPDATE_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct Windows Update command")
            self.state_machine.transition_to(TaskState.EXECUTING, reason="Opening Windows Update")
            ok = False
            try:
                self._launch_process("explorer.exe", "ms-settings:windowsupdate")
                ok = True
            except Exception as e:
                logger.warning(f"Opening Windows Update failed: {e}")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking Windows Update launch")
            content = "Done." if ok else "I could not open Windows Update."
            self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "open_windows_update",
                    "success": ok,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._TIME_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct time query")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Formatting local time")
            time_format = "It is %#I:%M %p." if os.name == "nt" else "It is %-I:%M %p."
            content = datetime.now().astimezone().strftime(time_format)
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Time answered")
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "time",
                    "success": True,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._LISTENING_CHECK_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct listening check")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Confirming voice readiness")
            content = "Yes. I am listening."
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Listening confirmed")
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "listening_check",
                    "success": True,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._LAPTOP_IDENTITY_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct laptop identity query")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Reading local laptop identity")
            content = "This is your local Windows laptop. " + self._format_local_specs()
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Laptop identity answered")
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "laptop_identity",
                    "success": True,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        if self._LAPTOP_SPECS_PATTERN.match(clean_input):
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Direct laptop specs query")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Reading local specs")
            content = self._format_local_specs()
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Specs answered")
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "direct_desktop_action": "laptop_specs",
                    "success": True,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

        volume_up_match = self._VOLUME_UP_PATTERN.match(clean_input)
        if volume_up_match:
            step = int(volume_up_match.group("step") or 10)
            return self._complete_fast_path(
                clean_input, start_time, "volume_up",
                "Direct volume up command", f"Raising volume by {step}%",
                lambda: self._adjust_volume(delta=step),
            )

        volume_down_match = self._VOLUME_DOWN_PATTERN.match(clean_input)
        if volume_down_match:
            step = int(volume_down_match.group("step") or 10)
            return self._complete_fast_path(
                clean_input, start_time, "volume_down",
                "Direct volume down command", f"Lowering volume by {step}%",
                lambda: self._adjust_volume(delta=-step),
            )

        set_volume_match = self._SET_VOLUME_PATTERN.match(clean_input)
        if set_volume_match:
            level = int(set_volume_match.group("level"))
            return self._complete_fast_path(
                clean_input, start_time, "set_volume",
                "Direct set-volume command", f"Setting volume to {level}%",
                lambda: self._adjust_volume(set_to=level),
            )

        mute_match = self._MUTE_PATTERN.match(clean_input)
        if mute_match:
            action = mute_match.group("action").lower()

            def _mute_toggle() -> str:
                from friday.tools.builtin.os_control import ManageVolumeTool

                res = ManageVolumeTool().execute(action=action)
                if res.is_error:
                    raise RuntimeError(res.content)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, f"volume_{action}",
                f"Direct {action} command", f"{action.capitalize()}ing master volume",
                _mute_toggle,
            )

        if self._BATTERY_PATTERN.match(clean_input):
            return self._complete_fast_path(
                clean_input, start_time, "battery_status",
                "Direct battery query", "Reading battery status",
                self._read_battery_status,
                verifying_reason="Formatting battery report",
            )

        if self._SCREEN_DESCRIBE_PATTERN.match(clean_input):
            def _describe_screen() -> str:
                res = ScreenSnapshotTool().execute(query="Describe what is on my screen concisely.")
                if res.is_error:
                    raise RuntimeError(res.content)
                raw = res.content
                marker = "):\n"
                return raw.split(marker, 1)[1].strip() if marker in raw else raw

            return self._complete_fast_path(
                clean_input, start_time, "screen_describe",
                "Direct screen description query", "Capturing and analyzing screen",
                _describe_screen,
                verifying_reason="Validating screen analysis",
            )

        active_type_match = self._ACTIVE_WINDOW_TYPE_PATTERN.match(clean_input)
        if active_type_match:
            payload = active_type_match.group("text").strip()
            # If payload ends with "here" or similar, clean it
            payload = re.sub(r"\s+(?:here|in\s+this|at\s+the\s+cursor|where\s+the\s+mouse\s+pointer\s+is(?:\s+there)?|where\s+i\s+am)$", "", payload, flags=re.IGNORECASE).strip()

            def _type_at_focus() -> str:
                typed = WindowsNativeInputDriver().type_text(payload)
                if not typed:
                    raise RuntimeError("Failed to send keystrokes to active window.")
                return "Typed."

            return self._complete_fast_path(
                clean_input, start_time, "active_window_type",
                "Direct active window typing command", f"Typing '{payload}' into active window",
                _type_at_focus,
                verifying_reason="Validating text typed into active focus",
            )

        light_match = self._CONTROL_LIGHT_PATTERN.match(clean_input)
        if light_match:
            action_raw = (light_match.group("action") or "").lower()
            dim_b = light_match.group("dim_brightness")
            bright_val = light_match.group("brightness") or dim_b
            
            if "off" in action_raw:
                state_val = False
                b_int = None
            elif "to" in action_raw and bright_val:
                state_val = True
                b_int = int(bright_val)
            elif dim_b:
                state_val = True
                b_int = int(dim_b)
            elif "dim" in clean_input.lower():
                state_val = True
                b_int = 50
            else:
                state_val = True
                b_int = None

            def _toggle_light() -> str:
                from friday.tools.builtin.smart_home import ControlLightTool
                res = ControlLightTool().execute(state=state_val, brightness=b_int)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, "control_light",
                "Direct smart home light command", "Sending command to local smart light",
                _toggle_light,
                verifying_reason="Validating smart light response",
            )

        plug_match = self._CONTROL_PLUG_PATTERN.match(clean_input)
        if plug_match:
            action_val = plug_match.group("action") or plug_match.group("action2") or "on"
            dev_id = plug_match.group("device_id") or plug_match.group("device_id2") or "plug_1"
            state_val = (action_val.lower() == "on")

            def _toggle_plug() -> str:
                from friday.tools.builtin.smart_home import ControlPlugTool
                res = ControlPlugTool().execute(device_id=dev_id, state=state_val)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, "control_plug",
                "Direct smart plug command", f"Sending {action_val} command to smart plug '{dev_id}'",
                _toggle_plug,
                verifying_reason="Validating smart plug response",
            )

        dark_mode_match = self._TOGGLE_DARK_MODE_PATTERN.match(clean_input)
        if dark_mode_match:
            mode_raw = (dark_mode_match.group("mode") or "").lower()
            is_dark = "dark" in mode_raw or "turn on" in clean_input.lower() or "enable" in clean_input.lower()
            if "turn off dark mode" in clean_input.lower() or "disable dark mode" in clean_input.lower() or "light" in mode_raw:
                is_dark = False

            def _toggle_dark() -> str:
                from friday.tools.builtin.os_settings import ToggleDarkModeTool
                res = ToggleDarkModeTool().execute(state=is_dark)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, "toggle_dark_mode",
                "Direct dark mode command", f"Setting Windows theme to {'Dark Mode' if is_dark else 'Light Mode'}",
                _toggle_dark,
                verifying_reason="Validating theme registry change",
            )

        bt_match = self._TOGGLE_BLUETOOTH_PATTERN.match(clean_input)
        if bt_match:
            action_raw = bt_match.group("action") or bt_match.group("action2") or "on"
            state_val = (action_raw.lower() == "on")

            def _toggle_bt() -> str:
                from friday.tools.builtin.os_settings import ToggleBluetoothTool
                res = ToggleBluetoothTool().execute(state=state_val)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, "toggle_bluetooth",
                "Direct bluetooth command", f"Turning Bluetooth {action_raw.lower()}",
                _toggle_bt,
                verifying_reason="Validating Bluetooth radio state",
            )

        wifi_match = self._TOGGLE_WIFI_PATTERN.match(clean_input)
        if wifi_match:
            action_raw = wifi_match.group("action") or wifi_match.group("action2") or "on"
            state_val = (action_raw.lower() == "on")

            def _toggle_wifi_func() -> str:
                from friday.tools.builtin.os_settings import ToggleWifiTool
                res = ToggleWifiTool().execute(state=state_val)
                return res.content

            return self._complete_fast_path(
                clean_input, start_time, "toggle_wifi",
                "Direct Wi-Fi command", f"Turning Wi-Fi {action_raw.lower()}",
                _toggle_wifi_func,
                verifying_reason="Validating Wi-Fi network interface state",
            )

        return None

    def classify_instant_command(self, text: str) -> Optional[str]:
        """Return an instant-command key when this utterance must be executed
        locally (deterministically) instead of being answered by the voice model.

        Mirrors the ordering of _direct_desktop_action_fast_path so voice mode
        routes exactly the same utterances to the same deterministic handlers.
        """
        clean = (text or "").strip()
        if not clean:
            return None
        if self._NOTEPAD_TYPE_PATTERN.match(clean):
            return "notepad_type"
        if self._CHROME_SEARCH_PATTERN.match(clean):
            return "chrome_search"
        if self._CLOSE_CHROME_PATTERN.match(clean):
            return "close_chrome"
        open_app_match = self._OPEN_APP_PATTERN.match(clean)
        if open_app_match:
            app_raw = open_app_match.group("app").strip().lower()
            if app_raw in IntentDetector.APP_LAUNCH_MAP:
                return f"open_{app_raw}"
        if self._SETTINGS_PATTERN.match(clean):
            return "open_settings"
        if self._WINDOWS_UPDATE_PATTERN.match(clean):
            return "open_windows_update"
        if self._TIME_PATTERN.match(clean):
            return "time"
        if self._LISTENING_CHECK_PATTERN.match(clean):
            return "listening_check"
        if self._LAPTOP_IDENTITY_PATTERN.match(clean):
            return "laptop_identity"
        if self._LAPTOP_SPECS_PATTERN.match(clean):
            return "laptop_specs"
        if self._VOLUME_UP_PATTERN.match(clean):
            return "volume_up"
        if self._VOLUME_DOWN_PATTERN.match(clean):
            return "volume_down"
        if self._SET_VOLUME_PATTERN.match(clean):
            return "set_volume"
        if self._MUTE_PATTERN.match(clean):
            return "volume_mute"
        if self._BATTERY_PATTERN.match(clean):
            return "battery_status"
        if self._SCREEN_DESCRIBE_PATTERN.match(clean):
            return "screen_describe"
        if self._ACTIVE_WINDOW_TYPE_PATTERN.match(clean):
            return "active_window_type"
        if self._CONTROL_LIGHT_PATTERN.match(clean):
            return "control_light"
        if self._CONTROL_PLUG_PATTERN.match(clean):
            return "control_plug"
        if self._TOGGLE_DARK_MODE_PATTERN.match(clean):
            return "toggle_dark_mode"
        if self._TOGGLE_BLUETOOTH_PATTERN.match(clean):
            return "toggle_bluetooth"
        if self._TOGGLE_WIFI_PATTERN.match(clean):
            return "toggle_wifi"
        try:
            det_intent = DeterministicActionDetector.detect(clean)
            if det_intent and det_intent.confidence >= 0.95:
                return "deterministic"
        except Exception:
            pass
        try:
            intent_result = IntentDetector.detect(clean)
            if intent_result.intent.name == "SEMANTIC_UI_ACTION" and intent_result.confidence >= 0.90:
                return "semantic_ui"
        except Exception:
            pass
        return None

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
        registry.register(ScreenPredictionTool())
        return registry

    def _init_default_agent_registry(self) -> AgentRegistry:
        """Instantiate default specialist agent pool for Phase 13 Multi-Agent architecture."""
        from friday.agents.specialists.developer_agent import DeveloperAgent
        from friday.agents.specialists.research_agent import ResearchAgent
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
        subtask_summaries: List[str] = []
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

        # Universe Orchestration fast-path (Phases 20-21)
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

        # Autonomous Dev Workflow fast-path (Phase 26)
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
            try:
                loop = asyncio.get_running_loop()
                dev_res = loop.run_until_complete(self._dev_workflow.execute_issue_fix(clean_input))
            except RuntimeError:
                dev_res = asyncio.run(self._dev_workflow.execute_issue_fix(clean_input))

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

        # Morning Briefing Workflow fast-path (Phase 29)
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

        # Email Drafting Workflow fast-path (Phase 30)
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

        # Multi-Agent Complex Workflow Routing (Phase 13)
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
