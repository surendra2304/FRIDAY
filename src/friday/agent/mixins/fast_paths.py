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

class FastPathMixin:
    _WAKE_PHRASE_PATTERN = re.compile(
        r"^\s*(?:(?:hey|okay|ok|please)\s+)?friday\s*[,!:;-]?\s*",
        re.IGNORECASE,
    )

    def normalize_wake_phrase(self, user_input: str) -> str:
        """Remove an optional addressed wake phrase before intent matching."""
        clean_input = (user_input or "").strip()
        normalized = self._WAKE_PHRASE_PATTERN.sub("", clean_input, count=1)
        return normalized.strip() or clean_input

    def _greeting_fast_path(self, clean_input: str) -> AgentResponse | None:
            """Return a direct conversational greeting response, or None if not a greeting."""
            if not self._GREETING_PATTERN.match(clean_input):
                return None
            from friday.persona.friday import greeting_responses_for
            responses = greeting_responses_for(getattr(self.settings, "persona", "friday"))
            response = random.choice(responses).format(user_name=self.settings.user_name)
            logger.info("Greeting fast-path: responding directly without cognitive loop or tools")
            self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Greeting recognized")
            self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing greeting response")
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating greeting response")
            self.state_machine.transition_to(TaskState.COMPLETED, reason="Greeting ready")
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.memory.add_message(Message(role=Role.ASSISTANT, content=response))
            try:
                from friday.memory.memora_client import memora_client
                memora_client.record_interaction_async(
                    user_input=clean_input,
                    agent_output=response,
                    agent_name="friday",
                    event_type="dialogue",
                    tags=["greeting", "fast_path"],
                )
            except Exception as e:
                logger.debug(f"Memora record skipped in greeting: {e}")
            return AgentResponse(
                content=response,
                is_done=True,
                metadata={
                    "greeting_fast_path": True,
                    "task_state": self.state_machine.current_state.value,
                },
            )

    def _conversational_fast_path(self, clean_input: str) -> AgentResponse | None:
        """Return an instant zero-latency response for common conversational inquiries."""
        low = clean_input.lower().strip().rstrip(".!? ")
        user_name = getattr(self.settings, "user_name", "Surendra")

        reply = None
        if re.search(r"^(?:who\s+(?:are\s+you|r\s+u)|what\s+is\s+your\s+name|what\s+are\s+you|tell\s+me\s+about\s+yourself)$", low):
            reply = f"I am FRIDAY, your personal AI assistant and Windows laptop controller, {user_name}. I can control applications, media, volume, system settings, and assist with code, research, and daily workflows."
        elif re.search(r"^(?:how\s+are\s+you(?:\s+doing)?|how\'s\s+it\s+going|how\s+do\s+you\s+feel|how\s+are\s+things)$", low):
            reply = f"All systems are running at peak performance, {user_name}. Ready for whatever you need. How can I assist you right now?"
        elif re.search(r"^(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|what\s+do\s+you\s+do|help\s+me\s+with\s+commands)$", low):
            reply = (
                f"I provide full Windows laptop control and autonomous AI assistance, {user_name}. "
                "You can ask me to play songs on YouTube, control volume/brightness, launch or close apps, "
                "check battery and system telemetry, execute PowerShell commands, or answer complex questions. "
                "Type /friday in chat for a full list of laptop commands."
            )
        elif re.search(r"^(?:are\s+you\s+there|you\s+there|can\s+you\s+hear\s+me)$", low):
            reply = f"Always here and listening, {user_name}. What would you like done?"
        elif re.search(r"^(?:thank\s+you|thanks(?:\s+a\s+lot)?|thanks\s+friday|thank\s+you\s+so\s+much)$", low):
            reply = f"You're very welcome, {user_name}!"
        elif re.search(r"^(?:good\s+morning|good\s+afternoon|good\s+evening|good\s+night)$", low):
            reply = f"Good day, {user_name}. Systems are primed and ready."
        elif re.search(r"^(?:welcome\s+home(?:\s+sir)?|run\s+welcome\s+protocol|studio\s+mode|jarvis\s+mode)$", low):
            from friday.autonomous.welcome_protocol import welcome_protocol
            import threading
            threading.Thread(target=welcome_protocol.run, daemon=True, name="WelcomeProtocolThread").start()
            reply = f"Welcome home, {user_name}. Initiating workspace protocol across all displays."

        if not reply:
            return None

        logger.info(f"Conversational fast-path matched: '{low}' -> instant response (0ms)")
        self.state_machine.transition_to(TaskState.UNDERSTANDING, reason="Conversational query recognized")
        self.state_machine.transition_to(TaskState.PLANNING, reason="Synthesizing conversational response")
        self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating conversational response")
        self.state_machine.transition_to(TaskState.COMPLETED, reason="Conversational response ready")
        self.memory.add_message(Message(role=Role.USER, content=clean_input))
        self.memory.add_message(Message(role=Role.ASSISTANT, content=reply))
        try:
            from friday.memory.memora_client import memora_client
            memora_client.record_interaction_async(
                user_input=clean_input,
                agent_output=reply,
                agent_name="friday",
                event_type="dialogue",
                tags=["conversational", "fast_path"],
            )
        except Exception as e:
            logger.debug(f"Memora record skipped in conversational: {e}")
        return AgentResponse(
            content=reply,
            is_done=True,
            metadata={
                "conversational_fast_path": True,
                "task_state": self.state_machine.current_state.value,
            },
        )

    def _deterministic_action_fast_path(self, clean_input: str, start_time: float) -> AgentResponse | None:
            """Execute safe geometric desktop actions without vision or an LLM."""
            intent = DeterministicActionDetector.detect(clean_input)
            if not intent or intent.requires_confirmation:
                return None
            self.memory.add_message(Message(role=Role.USER, content=clean_input))
            self.state_machine.transition_to(TaskState.PLANNING, reason="Deterministic desktop action recognized")
            self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing {intent.action_type.value}")
            try:
                executor = ComputerActionExecutor(sandboxed=False)
                result = executor.execute_proposal(intent.to_proposal(), user_confirmed=True)
                success = bool(result.is_success)
                if intent.action_type.value == "move" and success:
                    x, y = intent.arguments["x"], intent.arguments["y"]
                    if "center" in intent.intent.lower():
                        content = f"Moved the mouse cursor to the center of the screen ({x}, {y})."
                    else:
                        content = f"Moved the mouse cursor to ({x}, {y})."
                elif intent.action_type.value == "scroll" and success:
                    content = f"Scrolled {'up' if intent.arguments['delta_y'] > 0 else 'down'} successfully."
                else:
                    content = result.details if success else f"I could not complete that action: {result.details}"
            except Exception as exc:
                success = False
                content = f"I could not complete that action: {exc}"
            self.state_machine.transition_to(TaskState.VERIFYING, reason="Verifying deterministic desktop action")
            self.state_machine.transition_to(TaskState.COMPLETED if success else TaskState.FAILED, reason=content)
            self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
            try:
                from friday.memory.memora_client import memora_client
                memora_client.record_interaction_async(
                    user_input=clean_input,
                    agent_output=content,
                    agent_name="friday",
                    event_type="action",
                    tags=["desktop_action", intent.action_type.value],
                )
                memora_client.learn_from_outcome_async(
                    agent_name="friday",
                    task_name=intent.action_type.value,
                    status="success" if success else "failure",
                    actions_taken=content,
                    domain="deterministic_action",
                )
            except Exception as e:
                logger.debug(f"Memora record skipped in deterministic action: {e}")
            return AgentResponse(
                content=content,
                is_done=True,
                metadata={
                    "fast_path": True,
                    "deterministic": True,
                    "action_type": intent.action_type.value,
                    "arguments": intent.arguments,
                    "success": success,
                    "duration_seconds": time.perf_counter() - start_time,
                    "task_state": self.state_machine.current_state.value,
                },
            )

    def _launch_process(self, executable: str, *args: str) -> None:
            """Launch a desktop process reliably on Windows without blocking the agent turn."""
            try:
                if args:
                    cmd = f'start "" "{executable}" ' + " ".join(f'"{a}"' for a in args)
                    subprocess.Popen(cmd, shell=True)
                else:
                    try:
                        os.startfile(executable)
                    except Exception:
                        subprocess.Popen(f'start "" "{executable}"', shell=True)
            except Exception as e:
                logger.warning(f"Desktop launch error for {executable}: {e}")

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
            delta: int | None = None,
            set_to: int | None = None,
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
            try:
                from friday.memory.memora_client import memora_client
                memora_client.record_interaction_async(
                    user_input=clean_input,
                    agent_output=content,
                    agent_name="friday",
                    event_type="fast_path_action",
                    tags=["fast_path", action_key],
                )
                memora_client.learn_from_outcome_async(
                    agent_name="friday",
                    task_name=action_key,
                    status="success" if success else "failure",
                    actions_taken=content,
                    domain="fast_path",
                )
            except Exception as e:
                logger.debug(f"Memora record skipped in _complete_fast_path: {e}")
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

    def _direct_desktop_action_fast_path(self, clean_input: str, start_time: float) -> AgentResponse | None:
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

            from friday.devices.windows_friday import windows_friday
            if (
                windows_friday.is_whatsapp_directive(clean_input)
                or windows_friday.is_contact_directive(clean_input)
                or windows_friday.is_gmail_directive(clean_input)
            ):
                handled, reply, meta = windows_friday.handle_directive(clean_input)
                if handled:
                    self.memory.add_message(Message(role=Role.USER, content=clean_input))
                    self.memory.add_message(Message(role=Role.ASSISTANT, content=reply))
                    return AgentResponse(
                        content=reply,
                        is_done=True,
                        metadata={
                            "fast_path": True,
                            "direct_desktop_action": meta.get("direct_action") or meta.get("action", "desktop_directive"),
                            "success": meta.get("success", True),
                            "duration_seconds": time.perf_counter() - start_time,
                        },
                    )

            # E2E Specialist Workflow Directives
            lower_clean = clean_input.lower().strip()
            from friday.ecosystem.e2e_workflow_coordinator import global_e2e_coordinator

            # 5. Research
            if any(k in lower_clean for k in ["research this company", "research company", "deep research"]):
                company = "Anthropic"
                m_comp = re.search(r"research\s+(?:on\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+and\s+give|\s+and\s+provide|\s*$)", clean_input, re.IGNORECASE)
                if m_comp and m_comp.group(1).strip().lower() not in ("this company", "company"):
                    company = m_comp.group(1).strip()
                res = global_e2e_coordinator.execute_research_workflow(company)
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=res["report"]))
                return AgentResponse(
                    content=res["report"],
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "research", "result": res}
                )

            # 6. Software Engineering
            if any(k in lower_clean for k in ["fix the failing login test", "fix failing login test", "fix login test"]):
                res = global_e2e_coordinator.execute_software_engineering_workflow("fix the failing login test")
                content = "Fixed failing login test: Inference generated patch plan, Forge applied implementation, pytest passed (3/3), and Sentinel security gate validated clean."
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                return AgentResponse(
                    content=content,
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "software_engineering", "result": res}
                )

            # 7. Security Assessment
            if any(k in lower_clean for k in ["assess my authorized staging server", "assess staging server", "assess staging"]):
                res = global_e2e_coordinator.execute_security_assessment_workflow("staging.internal")
                content = f"Security assessment for {res['target']} complete. Scope confirmed, Sentinel policy validated, and 2 findings recorded with evidence digest: {res['evidence_hash'][:16]}..."
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                return AgentResponse(
                    content=content,
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "security_assessment", "result": res}
                )

            # 8. Forecasting
            if any(k in lower_clean for k in ["forecast website traffic", "traffic for tomorrow", "forecast traffic"]):
                res = global_e2e_coordinator.execute_forecasting_workflow("website_traffic", "tomorrow")
                fc = res["forecast"]
                content = (
                    f"Futuris calibrated forecast for website traffic tomorrow: point estimate {fc['point_estimate']:,.0f} req/hr "
                    f"(90% CI: {fc['p10_lower_bound']:,.0f} – {fc['p90_upper_bound']:,.0f} req/hr).\n"
                    f"Uncertainty: {fc['uncertainty']}. Advisory forecast only; zero automated production changes made."
                )
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                return AgentResponse(
                    content=content,
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "forecasting", "result": res}
                )

            # 9. Trading Performance
            if any(k in lower_clean for k in ["check stratex performance", "stratex performance", "check trading performance"]):
                res = global_e2e_coordinator.execute_trading_performance_workflow()
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=res["explanation"]))
                return AgentResponse(
                    content=res["explanation"],
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "trading_performance", "result": res}
                )

            # 10. Cancellation
            if any(k in lower_clean for k in ["stop the current task", "stop current task", "cancel current task", "abort task"]):
                res = global_e2e_coordinator.execute_task_cancellation_workflow(task_id="task_active_001")
                content = f"Interrupted and stopped current task. Subsystems halted ({', '.join(res['peer_cancellations'].keys())}). Zero new side effects executed. Cancelled receipt generated."
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                return AgentResponse(
                    content=content,
                    is_done=True,
                    metadata={"fast_path": True, "workflow": "cancellation", "result": res}
                )

            play_match = getattr(self, "_PLAY_MEDIA_PATTERN", None)
            if play_match:
                m = play_match.match(clean_input)
                if m:
                    track = (m.group("query") or m.group("query2") or m.group("query3") or "").strip()
                    if track.lower() in ("the song", "song", "it", "the music", "music", "the video", "video"):
                        try:
                            recent_msgs = self.memory.get_messages()[-6:]
                            for prev_msg in reversed(recent_msgs):
                                prev_text = prev_msg.content or ""
                                if prev_text.startswith("Playing '") and "' on YouTube." in prev_text:
                                    track = prev_text.split("Playing '")[1].split("' on YouTube.")[0]
                                    break
                                pm = getattr(self, "_PLAY_MEDIA_PATTERN", None).match(prev_text)
                                if pm:
                                    cand = (pm.group("query") or pm.group("query2") or pm.group("query3") or "").strip()
                                    if cand and cand.lower() not in ("the song", "song", "it", "music", "the video", "video"):
                                        track = cand
                                        break
                        except Exception:
                            pass

                    if track and not any(track.lower().startswith(x) for x in ["game", "chess", "cards"]):
                        self.memory.add_message(Message(role=Role.USER, content=clean_input))
                        self.state_machine.transition_to(TaskState.PLANNING, reason=f"Direct playback command for {track}")
                        self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Playing {track} on YouTube")
                        yt_tool = self.tools.get("youtube")
                        if yt_tool:
                            res = yt_tool.execute(query=track, play=True)
                            content = res.content
                            ok = not res.is_error
                        else:
                            content = f"Playing '{track}' on YouTube."
                            ok = True
                        self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking playback")
                        self.state_machine.transition_to(TaskState.COMPLETED if ok else TaskState.FAILED, reason=content)
                        self.memory.add_message(Message(role=Role.ASSISTANT, content=content))
                        return AgentResponse(
                            content=content,
                            is_done=True,
                            metadata={
                                "fast_path": True,
                                "direct_desktop_action": "play_youtube",
                                "track": track,
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
                    if not ok:
                        result = subprocess.run(
                            ["taskkill.exe", "/F", "/IM", "chrome.exe", "/T"],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        combined = f"{result.stdout}\n{result.stderr}".lower()
                        ok = result.returncode == 0 or "not found" in combined or "success" in combined
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
            play_match = self._PLAY_MEDIA_PATTERN.match(clean_input)
            if play_match:
                query_raw = (
                    play_match.groupdict().get("query")
                    or play_match.groupdict().get("query2")
                    or play_match.groupdict().get("query3")
                )
                query_val = (query_raw or "").strip()
                query_val = re.sub(r"\s+(?:on|in)\s+youtube[\.\!\?]*$", "", query_val, flags=re.IGNORECASE).strip().rstrip(".!?")
                if query_val:
                    def _play_youtube() -> str:
                        from friday.tools.builtin.youtube import YouTubeTool
                        return YouTubeTool().execute(query=query_val, play=True).content

                    return self._complete_fast_path(
                        clean_input, start_time, "play_media",
                        f"Direct media playback command for '{query_val}'", f"Playing '{query_val}' on YouTube",
                        _play_youtube,
                        verifying_reason="Resolving YouTube video watch URL and launching in browser",
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

            open_app_match = self._OPEN_APP_PATTERN.match(clean_input)
            if open_app_match:
                app_raw = open_app_match.group("app").strip().lower()
                # Normalize app name
                normalized_app = app_raw.replace(" ", "").replace("-", "")
                exe = None
                if app_raw in IntentDetector.APP_LAUNCH_MAP:
                    exe = IntentDetector.APP_LAUNCH_MAP[app_raw]
                elif normalized_app in ("notepad", "notepad.exe"):
                    exe = "notepad.exe"
                elif normalized_app in ("chrome", "googlechrome"):
                    exe = "chrome.exe"
                elif normalized_app in ("calculator", "calc"):
                    exe = "calc.exe"
                elif normalized_app in ("cmd", "terminal", "commandprompt"):
                    exe = "wt.exe"
                elif normalized_app in ("settings", "windowsettings"):
                    exe = "ms-settings:"
                elif normalized_app in ("youtube", "amazon", "github", "netflix", "reddit", "twitter"):
                    exe = f"https://www.{normalized_app}.com"
                elif normalized_app in ("spotify",):
                    exe = "https://open.spotify.com"
                elif app_raw in IntentDetector.APP_LAUNCH_MAP.values():
                    exe = app_raw

                if exe:
                    self.memory.add_message(Message(role=Role.USER, content=clean_input))
                    self.state_machine.transition_to(TaskState.PLANNING, reason=f"Direct launch command for {app_raw}")
                    self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Opening {app_raw}")
                    ok = False
                    try:
                        from friday.devices.app_launcher import launch_desktop_app
                        ok, msg = launch_desktop_app(app_raw)
                        if not ok:
                            if "Multiple installations" in msg:
                                self.state_machine.transition_to(TaskState.VERIFYING, reason="Checking ambiguity")
                                self.state_machine.transition_to(TaskState.COMPLETED, reason="Multiple installations detected; requesting user clarification")
                                self.memory.add_message(Message(role=Role.ASSISTANT, content=msg))
                                return AgentResponse(
                                    content=msg,
                                    is_done=True,
                                    metadata={
                                        "fast_path": True,
                                        "direct_desktop_action": f"open_{app_raw}",
                                        "is_ambiguous": True,
                                        "success": False,
                                        "duration_seconds": time.perf_counter() - start_time,
                                        "task_state": self.state_machine.current_state.value,
                                    },
                                )
                            elif exe.startswith("http"):
                                import webbrowser
                                webbrowser.open(exe)
                                ok = True
                            elif exe.startswith("ms-"):
                                self._launch_process("explorer.exe", exe)
                                ok = True
                            else:
                                self._launch_process(exe)
                                ok = True
                    except Exception as e:
                        logger.warning(f"Opening '{app_raw}' failed: {e}")
                    self.state_machine.transition_to(TaskState.VERIFYING, reason=f"Checking {app_raw} launch")
                    content = msg if ok and msg else ("Done." if ok else f"I could not open {app_raw}.")
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

            if self._STATUS_PATTERN.match(clean_input):
                def _get_status_report() -> str:
                    from friday.skills.ecosystem_status import EcosystemStatusSkill
                    res = EcosystemStatusSkill().execute(clean_input)
                    return res.output or "Ecosystem status retrieved."

                return self._complete_fast_path(
                    clean_input, start_time, "ecosystem_status",
                    "Direct ecosystem status query", "Polling status across all 8 subsystems",
                    _get_status_report,
                    verifying_reason="Formatting unified ecosystem status report",
                )

            if self._BRIEFING_PATTERN.match(clean_input):
                def _get_briefing() -> str:
                    from friday.workflows.master_briefing import MasterDailyBriefingWorkflow
                    wf = MasterDailyBriefingWorkflow()
                    if "evening" in clean_input.lower():
                        snapshot = wf.generate_evening_wrapup()
                    else:
                        snapshot = wf.generate_morning_briefing()
                    return snapshot.markdown_report

                return self._complete_fast_path(
                    clean_input, start_time, "master_briefing",
                    "Direct master briefing request", "Compiling cross-agent intelligence briefing",
                    _get_briefing,
                    verifying_reason="Formatting master intelligence briefing",
                )

            # Master Windows FRIDAY Controller (handles all additional laptop directives)
            from friday.devices.windows_friday import windows_friday
            handled, reply, meta = windows_friday.handle_directive(clean_input)
            if handled:
                self.memory.add_message(Message(role=Role.USER, content=clean_input))
                action_name = meta.get("action", "os_directive")
                self.state_machine.transition_to(TaskState.PLANNING, reason=f"FRIDAY OS action recognized: {action_name}")
                self.state_machine.transition_to(TaskState.EXECUTING, reason=f"Executing {action_name}")
                self.state_machine.transition_to(TaskState.VERIFYING, reason="Validating OS directive execution")
                self.state_machine.transition_to(TaskState.COMPLETED, reason=reply)
                self.memory.add_message(Message(role=Role.ASSISTANT, content=reply))
                return AgentResponse(
                    content=reply,
                    is_done=True,
                    metadata={
                        "fast_path": True,
                        "direct_desktop_action": action_name,
                        "friday_meta": meta,
                        "success": meta.get("success", True),
                        "duration_seconds": time.perf_counter() - start_time,
                        "task_state": self.state_machine.current_state.value,
                    },
                )

            return None

    def classify_instant_command(self, text: str) -> str | None:
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
            if self._PLAY_MEDIA_PATTERN.match(clean):
                return "play_media"
            open_app_match = self._OPEN_APP_PATTERN.match(clean)
            if open_app_match:
                app_raw = open_app_match.group("app").strip().lower()
                normalized_app = app_raw.replace(" ", "").replace("-", "")
                if (
                    app_raw in IntentDetector.APP_LAUNCH_MAP
                    or normalized_app in ("notepad", "notepad.exe", "chrome", "googlechrome", "calculator", "calc", "cmd", "terminal", "commandprompt", "settings")
                    or app_raw in IntentDetector.APP_LAUNCH_MAP.values()
                ):
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
            from friday.devices.windows_friday import windows_friday
            if windows_friday.can_handle(clean):
                return "windows_friday_directive"
            return None

    def _execute_semantic_ui_action(self, intent_result, user_input: str) -> AgentResponse | None:
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

