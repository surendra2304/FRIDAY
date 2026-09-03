"""Desktop companion application runtime for FRIDAY.

Bridges the 9-state PyQt6 DesktopOverlay with the core FridayAgent,
GeminiLiveVoiceSession, and desktop authorization system.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from friday.agent.agent import FridayAgent
from friday.core.auth import BaseAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.desktop.window import DesktopOverlay

logger = get_logger("desktop.app")


class DesktopAuthorizer(BaseAuthorizer):
    """Authorizer bridging sensitive tool calls to the desktop confirmation prompt."""

    def __init__(self, request_signal: pyqtSignal, response_event: threading.Event) -> None:
        self.request_signal = request_signal
        self.response_event = response_event
        self.last_decision = False

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        # Safe tools execute automatically
        if request.safety_level == SafetyLevel.SAFE:
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Safe tool auto-approved",
            )

        # Sensitive or dangerous tools require user confirmation
        prompt = (
            f"Action Authorization Required:\n"
            f"Tool: {request.tool_name}\n"
            f"Classification: {request.safety_level.value.upper()}\n"
            f"Arguments: {request.arguments}"
        )
        self.response_event.clear()
        self.request_signal.emit(prompt)

        # Wait for user input on UI (30-second timeout)
        confirmed = self.response_event.wait(timeout=30.0)
        if confirmed and self.last_decision:
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Authorized by user on desktop overlay",
            )

        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason="Action cancelled or timed out by user",
        )


class BackendWorker(QObject):
    """Background engine connecting FridayAgent and voice session to the UI."""

    response_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str, str)  # (status_text, state_key)
    confirm_request_signal = pyqtSignal(str)
    task_progress_signal = pyqtSignal(str, str, str)  # (task_id, description, status)
    clear_tasks_signal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()

        self._confirm_event = threading.Event()
        self.authorizer = DesktopAuthorizer(
            request_signal=self.confirm_request_signal,
            response_event=self._confirm_event,
        )

        self.agent = FridayAgent(
            settings=self.settings,
            authorizer=self.authorizer,
            tool_callback=self._on_tool_call,
        )

        # Connect planning event bus for HUD task checklist
        try:
            from friday.planning.events import (
                TaskEventType,
                TaskProgressEvent,
                global_task_event_bus,
            )

            def _on_event(ev: TaskProgressEvent) -> None:
                if ev.event_type == TaskEventType.PLAN_CREATED:
                    self.clear_tasks_signal.emit()
                    self.status_signal.emit("Planning Workflow...", "thinking")
                elif ev.event_type == TaskEventType.TASK_STARTED:
                    t_id = ev.task_id or "task"
                    self.task_progress_signal.emit(t_id, ev.message, "running")
                    self.status_signal.emit(f"Executing: {t_id}", "executing")
                elif ev.event_type == TaskEventType.TASK_COMPLETED:
                    t_id = ev.task_id or "task"
                    self.task_progress_signal.emit(t_id, ev.message, "completed")
                elif ev.event_type == TaskEventType.TASK_FAILED:
                    t_id = ev.task_id or "task"
                    self.task_progress_signal.emit(t_id, ev.message, "failed")
                    self.status_signal.emit("Task Failed", "error")
                elif ev.event_type == TaskEventType.WORKFLOW_COMPLETED:
                    self.status_signal.emit("Workflow Complete", "idle")

            global_task_event_bus.subscribe(_on_event)
        except Exception as e:
            logger.debug(f"Task event bus subscription: {e}")

        # Asyncio event loop running in a background thread
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.voice_session: Any = None
        self.voice_task: Any = None
        self.voice_stop_event: asyncio.Event | None = None

        # Check audio capabilities
        try:
            import sounddevice as sd

            self.audio_available = True
        except ImportError:
            self.audio_available = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _on_tool_call(self, tool_call: ToolCall, tool_result: ToolResult | None) -> None:
        """Invoked by FridayAgent during cognitive loop tool execution."""
        if tool_result is None:
            self.status_signal.emit(f"Executing: {tool_call.name}...", "executing")
        else:
            self.status_signal.emit("Analyzing outcome...", "thinking")

    def handle_confirmation_response(self, approved: bool) -> None:
        self.authorizer.last_decision = approved
        self._confirm_event.set()

    def handle_text_command(self, text: str) -> None:
        self.status_signal.emit("THINKING...", "thinking")

        async def _process():
            try:
                # Fast path execution where appropriate
                res = await self.loop.run_in_executor(None, self.agent.process_message, text)
                self.response_signal.emit(res.content)
                self.status_signal.emit("SYSTEM IDLE", "idle")
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                self.response_signal.emit(f"Error: {e}")
                self.status_signal.emit("ERROR", "error")

        asyncio.run_coroutine_threadsafe(_process(), self.loop)

    def _on_voice_state_change(self, old_state: Any, new_state: Any) -> None:
        """Map voice session states to the 9 UI overlay states."""
        state_str = str(new_state.name if hasattr(new_state, "name") else new_state).upper()
        state_map = {
            "IDLE": ("SYSTEM IDLE", "idle"),
            "CONNECTING": ("CONNECTING TO VOICE...", "listening"),
            "LISTENING": ("LISTENING...", "listening"),
            "THINKING": ("PROCESSING...", "thinking"),
            "PLANNING": ("PREPARING PLAN...", "planning"),
            "SPEAKING": ("SPEAKING...", "speaking"),
            "TOOL_EXECUTION": ("EXECUTING TOOL...", "executing"),
            "CONFIRMATION": ("CONFIRMATION REQUIRED", "confirmation"),
            "ERROR": ("VOICE ERROR", "error"),
            "DISCONNECTED": ("DISCONNECTED", "disconnected"),
        }
        text, ui_state = state_map.get(state_str, ("PROCESSING...", "thinking"))
        self.status_signal.emit(text, ui_state)

    def _on_voice_transcript(self, speaker: str, text: str) -> None:
        self.response_signal.emit(f"[{speaker}] {text}")

    def toggle_voice(self) -> None:
        if not self.audio_available:
            self.response_signal.emit("Voice interface unavailable: missing sounddevice.")
            self.status_signal.emit("AUDIO ERROR", "error")
            return

        if self.voice_session and getattr(self.voice_session, "is_active", False):
            # Graceful voice session shutdown
            self.response_signal.emit("Disconnecting voice interface...")

            async def _stop():
                if self.voice_stop_event:
                    self.voice_stop_event.set()
                if self.voice_task:
                    self.voice_task.cancel()
                self.voice_session = None
                self.status_signal.emit("SYSTEM IDLE", "idle")

            asyncio.run_coroutine_threadsafe(_stop(), self.loop)
        else:
            self.response_signal.emit("Connecting to Gemini Live Voice...")
            self.status_signal.emit("CONNECTING...", "listening")

            async def _start():
                try:
                    from friday.auth.credential_pool import credential_pool
                    from friday.voice.gemini_live_session import GeminiLiveVoiceSession

                    self.voice_session = GeminiLiveVoiceSession(
                        agent=self.agent,
                        credential_pool=credential_pool,
                        on_state_change=self._on_voice_state_change,
                    )
                    self.voice_stop_event = asyncio.Event()
                    self.voice_task = self.loop.create_task(
                        self.voice_session.run_live_loop(
                            on_turn_complete=self._on_voice_transcript,
                            stop_event=self.voice_stop_event,
                        )
                    )
                    await self.voice_session._connected_event.wait()
                    self.response_signal.emit("FRIDAY Live Voice session connected. Listening...")
                    self.status_signal.emit("LISTENING...", "listening")
                except Exception as e:
                    logger.error(f"Voice startup failure: {e}")
                    self.response_signal.emit(f"Voice Connection Error: {e}")
                    self.status_signal.emit("VOICE ERROR", "error")
                    self.voice_session = None

            asyncio.run_coroutine_threadsafe(_start(), self.loop)

    def shutdown(self) -> None:
        if self.voice_stop_event:
            self.voice_stop_event.set()
        if self.voice_task:
            self.loop.call_soon_threadsafe(self.voice_task.cancel)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=1.0)


def run_desktop_app() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    overlay = DesktopOverlay()
    worker = BackendWorker()

    # Wire UI signals to backend
    overlay.send_text_signal.connect(worker.handle_text_command)
    overlay.toggle_voice_signal.connect(worker.toggle_voice)
    overlay.confirmation_response_signal.connect(worker.handle_confirmation_response)
    overlay.close_signal.connect(app.quit)

    # Wire backend telemetry to UI
    worker.response_signal.connect(lambda text: overlay.append_transcript("FRIDAY", text))
    worker.status_signal.connect(overlay.set_status)
    worker.confirm_request_signal.connect(overlay.request_confirmation)
    worker.task_progress_signal.connect(overlay.update_task_progress)
    worker.clear_tasks_signal.connect(overlay.clear_task_progress)

    # Global Hotkey hook via keyboard library if available
    try:
        import keyboard

        keyboard.add_hotkey("ctrl+shift+space", overlay.toggle_visibility_or_focus)
    except Exception as e:
        logger.debug(f"keyboard library hotkey registration: {e}")

    overlay.show()
    res = app.exec()
    worker.shutdown()
    return res


if __name__ == "__main__":
    sys.exit(run_desktop_app())
