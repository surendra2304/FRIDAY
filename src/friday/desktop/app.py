import sys
import threading
import asyncio
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

import keyboard

from friday.desktop.window import DesktopOverlay
from friday.agent.agent import FridayAgent
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.cli.auth import CLIAuthorizer

logger = get_logger("desktop.app")

class BackendWorker(QObject):
    response_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str, str)
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.agent = FridayAgent(settings=self.settings, authorizer=CLIAuthorizer())
        
        # Asyncio event loop running in a background thread
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.voice_session = None
        self.voice_task = None
        
        # Audio stream detection
        try:
            import sounddevice as sd
            self.audio_available = True
        except ImportError:
            self.audio_available = False

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def handle_text_command(self, text: str):
        self.status_signal.emit("THINKING...", "thinking")
        
        async def _process():
            try:
                # Fast paths
                if "swipe left" in text.lower():
                    from friday.tools.builtin.open_application import OpenApplicationTool
                    res = OpenApplicationTool().execute(application="notepad")
                    self.response_signal.emit(f"Executed PC Action: {res.content}")
                    self.status_signal.emit("SYSTEM IDLE", "idle")
                    return
                elif "swipe right" in text.lower():
                    from friday.tools.builtin.open_application import OpenApplicationTool
                    res = OpenApplicationTool().execute(application="calc")
                    self.response_signal.emit(f"Executed PC Action: {res.content}")
                    self.status_signal.emit("SYSTEM IDLE", "idle")
                    return

                res = await self.agent.process_message(text)
                self.response_signal.emit(res.content)
                self.status_signal.emit("SYSTEM IDLE", "idle")
            except Exception as e:
                self.response_signal.emit(f"Error: {e}")
                self.status_signal.emit("ERROR", "error")

        asyncio.run_coroutine_threadsafe(_process(), self.loop)

    def _on_voice_state_change(self, old_state: str, new_state: str):
        # Maps voice state to UI state
        # Voice states: IDLE, CONNECTING, LISTENING, SPEAKING, TOOL_EXECUTION, ERROR, DISCONNECTED
        state_map = {
            "IDLE": "idle",
            "CONNECTING": "listening",
            "LISTENING": "listening",
            "SPEAKING": "speaking",
            "TOOL_EXECUTION": "thinking",
            "ERROR": "error",
            "DISCONNECTED": "error"
        }
        ui_state = state_map.get(new_state.name if hasattr(new_state, 'name') else str(new_state), "idle")
        
        label = new_state.name if hasattr(new_state, 'name') else str(new_state)
        self.status_signal.emit(label, ui_state)

    def _on_voice_transcript(self, speaker: str, text: str):
        self.response_signal.emit(f"[{speaker}] {text}")

    def toggle_voice(self):
        if not self.audio_available:
            self.response_signal.emit("Voice interface unavailable. Install sounddevice and PyAudio.")
            self.status_signal.emit("AUDIO ERROR", "error")
            return

        if self.voice_session and self.voice_session.is_active():
            # Stop the session
            self.response_signal.emit("Disconnecting voice interface...")
            async def _stop():
                if self.voice_task:
                    self.voice_task.cancel()
                self.voice_session = None
                self.status_signal.emit("SYSTEM IDLE", "idle")
            asyncio.run_coroutine_threadsafe(_stop(), self.loop)
        else:
            self.response_signal.emit("Voice interface connecting to Gemini Live...")
            self.status_signal.emit("CONNECTING...", "listening")
            
            async def _start():
                try:
                    from friday.voice.gemini_live_session import GeminiLiveVoiceSession
                    self.voice_session = GeminiLiveVoiceSession(
                        agent=self.agent,
                        on_state_change=self._on_voice_state_change,
                    )
                    self.voice_task = self.loop.create_task(
                        self.voice_session.run_live_loop()
                    )
                    await self.voice_session._connected_event.wait()
                    await self.voice_session.send_text("Hello FRIDAY. I have activated your holographic desktop interface.")
                except Exception as e:
                    self.response_signal.emit(f"Voice Error: {e}")
                    self.status_signal.emit("ERROR", "error")
                    self.voice_session = None

            asyncio.run_coroutine_threadsafe(_start(), self.loop)

    def shutdown(self):
        if self.voice_task:
            self.loop.call_soon_threadsafe(self.voice_task.cancel)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=1.0)


def run_desktop_app():
    app = QApplication(sys.argv)
    
    overlay = DesktopOverlay()
    worker = BackendWorker()
    
    # Connect signals
    overlay.send_text_signal.connect(worker.handle_text_command)
    overlay.toggle_voice_signal.connect(worker.toggle_voice)
    overlay.close_signal.connect(app.quit)
    
    worker.response_signal.connect(lambda text: overlay.append_transcript("FRIDAY", text))
    worker.status_signal.connect(overlay.set_status)
    
    # Global Hotkey
    def toggle_visibility():
        if overlay.isVisible():
            if overlay.isActiveWindow():
                overlay.hide()
            else:
                overlay.activateWindow()
        else:
            overlay.show()
            overlay.activateWindow()
            
    keyboard.add_hotkey('ctrl+shift+space', toggle_visibility)
    
    overlay.show()
    
    res = app.exec()
    worker.shutdown()
    return res

if __name__ == "__main__":
    sys.exit(run_desktop_app())
