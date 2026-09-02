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

class FastPathMixin:
    def _greeting_fast_path(self, clean_input: str) -> AgentResponse | None:
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
                elif app_raw in IntentDetector.APP_LAUNCH_MAP.values():
                    exe = app_raw

                if exe:
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

