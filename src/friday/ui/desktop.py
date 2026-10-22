"""Native FRIDAY desktop overlay.

A dependency-light Windows/macOS/Linux desktop shell inspired by the compact,
always-available voice assistant experience: a small floating pill/orb that can
expand into a transcript and command panel without replacing FRIDAY's existing
agent, memory, security, vision, tools, or Gemini Live voice stack.

The UI is deliberately a shell. All real actions still flow through
``FridayAgent`` and ``GeminiLiveVoiceSession`` so the existing authorization and
tool execution paths remain authoritative.
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import Any

from friday.agent.agent import FridayAgent
from friday.auth.credential_pool import credential_pool
from friday.cli.auth import CLIAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger, setup_logging
from friday.voice.gemini_live_session import GeminiLiveVoiceSession

logger = get_logger("ui.desktop")


@dataclass
class Transcript:
    speaker: str
    text: str


class DesktopVoiceRuntime:
    """Own the asyncio event loop used by Gemini Live on a worker thread."""

    def __init__(self, agent: FridayAgent):
        self.agent = agent
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session: GeminiLiveVoiceSession | None = None
        self.thread: threading.Thread | None = None
        self.stop_event: asyncio.Event | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._starting = threading.Lock()

    def start(self) -> None:
        with self._starting:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._thread_main, name="friday-desktop-voice", daemon=True)
            self.thread.start()

    def _thread_main(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run())
        except Exception as exc:  # pragma: no cover - platform/API dependent
            logger.exception("Desktop voice runtime failed")
            self.events.put(("error", str(exc)))
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    async def _run(self) -> None:
        self.stop_event = asyncio.Event()
        try:
            self.session = GeminiLiveVoiceSession(
                agent=self.agent,
                credential_pool=credential_pool,
                # Gemini's server-side VAD remains authoritative. The desktop
                # shell should never invent a second speech detector.
                local_barge_in_during_playback=False,
            )
            self.events.put(("state", "CONNECTING"))
            await self.session.run_live_loop(
                stop_event=self.stop_event,
                on_turn_complete=self._on_turn_complete,
                on_server_content=self._on_server_content,
            )
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("state", "STOPPED"))

    def _on_turn_complete(self, user_text: str, assistant_text: str) -> None:
        if user_text:
            self.events.put(("transcript", Transcript("You", user_text)))
        if assistant_text:
            self.events.put(("transcript", Transcript("FRIDAY", assistant_text)))

    def _on_server_content(self, _content: Any) -> None:
        # State is polled by the UI; this callback intentionally does no work
        # that could delay audio playback.
        return

    def send_text(self, text: str) -> None:
        if not self.loop or not self.session:
            self.events.put(("error", "Voice session is not connected yet."))
            return
        future = asyncio.run_coroutine_threadsafe(self.session.process_typed_input(text), self.loop)
        future.add_done_callback(self._future_error)

    @staticmethod
    def _future_error(future: Any) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.exception("Desktop typed input failed")

    def stop(self) -> None:
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def state(self) -> str:
        if self.session is None:
            return "IDLE"
        return self.session.state.value


class FridayDesktop:
    """Floating desktop shell for FRIDAY's existing intelligence stack."""

    BG = "#07080c"
    PANEL = "#0d1017"
    TEXT = "#f5f7fb"
    MUTED = "#7f899b"
    ACCENT = "#7c8cff"
    BORDER = "#242938"

    def __init__(self, agent: FridayAgent | None = None):
        self.settings = get_settings()
        self.agent = agent or FridayAgent(settings=self.settings, authorizer=CLIAuthorizer())
        self.runtime = DesktopVoiceRuntime(self.agent)
        self.transcripts: list[Transcript] = []
        self.expanded = False
        self.drag_offset = (0, 0)
        self.root = tk.Tk()
        self._configure_root()
        self._build_compact()
        self._build_expanded()
        self._show_compact()
        self._install_hotkey()
        self.root.after(100, self._poll)

    def _configure_root(self) -> None:
        self.root.title("FRIDAY")
        self.root.configure(bg=self.BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        width, height = 430, 76
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = (sw - width) // 2
        y = 24
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _rounded_frame(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.PANEL, highlightthickness=1, highlightbackground=self.BORDER)
        return frame

    def _build_compact(self) -> None:
        self.compact = self._rounded_frame(self.root)
        self.compact.pack(fill="both", expand=True)
        self.orb = tk.Canvas(self.compact, width=54, height=54, bg=self.PANEL, highlightthickness=0)
        self.orb.pack(side="left", padx=(10, 4), pady=10)
        self.orb.bind("<Button-1>", lambda _e: self.toggle_expanded())
        self.orb.bind("<Double-Button-1>", lambda _e: self.toggle_voice())
        self._draw_orb("IDLE")

        body = tk.Frame(self.compact, bg=self.PANEL)
        body.pack(side="left", fill="both", expand=True, pady=10)
        self.state_label = tk.Label(body, text="FRIDAY", bg=self.PANEL, fg=self.TEXT, font=("Segoe UI", 12, "bold"))
        self.state_label.pack(anchor="w")
        self.hint_label = tk.Label(body, text="Click to open  •  Double-click to listen", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8))
        self.hint_label.pack(anchor="w", pady=(2, 0))

        close = tk.Label(self.compact, text="×", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 16), cursor="hand2")
        close.pack(side="right", padx=10)
        close.bind("<Button-1>", lambda _e: self.close())
        self._bind_drag(self.compact)

    def _build_expanded(self) -> None:
        self.expanded_panel = self._rounded_frame(self.root)

        header = tk.Frame(self.expanded_panel, bg=self.PANEL)
        header.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(header, text="FRIDAY", bg=self.PANEL, fg=self.TEXT, font=("Segoe UI", 14, "bold")).pack(side="left")
        self.expanded_state = tk.Label(header, text="READY", bg=self.PANEL, fg=self.ACCENT, font=("Segoe UI", 8, "bold"))
        self.expanded_state.pack(side="left", padx=10)
        tk.Button(header, text="Listen", command=self.toggle_voice, bg=self.BORDER, fg=self.TEXT, relief="flat", padx=10).pack(side="right")
        tk.Button(header, text="−", command=self._show_compact, bg=self.PANEL, fg=self.MUTED, relief="flat", font=("Segoe UI", 12)).pack(side="right", padx=2)

        self.transcript_box = tk.Text(
            self.expanded_panel, height=16, wrap="word", bg=self.BG, fg=self.TEXT,
            insertbackground=self.TEXT, relief="flat", padx=12, pady=10,
            font=("Segoe UI", 10), state="disabled",
        )
        self.transcript_box.pack(fill="both", expand=True, padx=10, pady=4)
        self.transcript_box.tag_configure("speaker", foreground=self.ACCENT, font=("Segoe UI", 8, "bold"))

        footer = tk.Frame(self.expanded_panel, bg=self.PANEL)
        footer.pack(fill="x", padx=10, pady=10)
        self.entry = tk.Entry(footer, bg="#121722", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(2, 8))
        self.entry.bind("<Return>", lambda _e: self.send_typed())
        tk.Button(footer, text="Send", command=self.send_typed, bg=self.ACCENT, fg="#ffffff", relief="flat", padx=14, pady=6).pack(side="right")
        self._bind_drag(header)

    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, event: Any) -> None:
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event: Any) -> None:
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        self.root.geometry(f"{self.root.winfo_width()}x{self.root.winfo_height()}+{x}+{y}")

    def _draw_orb(self, state: str) -> None:
        self.orb.delete("all")
        cx = cy = 27
        radius = 18
        pulse = {"FRIDAY_SPEAKING": 21, "USER_SPEAKING": 20, "TOOL_CALL": 22, "CONNECTING": 16}.get(state, radius)
        self.orb.create_oval(cx-pulse, cy-pulse, cx+pulse, cy+pulse, outline=self.ACCENT, width=2)
        self.orb.create_oval(cx-8, cy-8, cx+8, cy+8, fill=self.ACCENT, outline="")
        self.orb.create_oval(cx-3, cy-3, cx+3, cy+3, fill=self.TEXT, outline="")

    def _show_compact(self) -> None:
        self.expanded = False
        self.expanded_panel.pack_forget()
        self.root.geometry(f"430x76+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.compact.pack(fill="both", expand=True)

    def _show_expanded(self) -> None:
        self.expanded = True
        self.compact.pack_forget()
        self.expanded_panel.pack(fill="both", expand=True)
        self.root.geometry(f"620x620+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.entry.focus_set()

    def toggle_expanded(self) -> None:
        self._show_compact() if self.expanded else self._show_expanded()

    def toggle_voice(self) -> None:
        if self.runtime.thread and self.runtime.thread.is_alive():
            self.runtime.stop()
            return
        self.runtime.start()

    def send_typed(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self._append_transcript(Transcript("You", text))
        self.entry.delete(0, "end")
        if self.runtime.thread and self.runtime.thread.is_alive():
            self.runtime.send_text(text)
            return
        # Keep the desktop shell useful even before voice is connected. This
        # uses the exact same agent/tool/security path as the CLI.
        def worker() -> None:
            try:
                response = self.agent.process_message(text)
                self.runtime.events.put(("transcript", Transcript("FRIDAY", response.content)))
            except Exception as exc:
                self.runtime.events.put(("error", str(exc)))
        threading.Thread(target=worker, name="friday-desktop-text", daemon=True).start()

    def _append_transcript(self, item: Transcript) -> None:
        self.transcripts.append(item)
        self.transcripts = self.transcripts[-50:]
        if not hasattr(self, "transcript_box"):
            return
        self.transcript_box.configure(state="normal")
        self.transcript_box.insert("end", f"{item.speaker}\n", "speaker")
        self.transcript_box.insert("end", f"{item.text}\n\n")
        self.transcript_box.see("end")
        self.transcript_box.configure(state="disabled")

    def _poll(self) -> None:
        state = self.runtime.state()
        self._draw_orb(state)
        self.state_label.configure(text="FRIDAY  •  " + state.replace("_", " "))
        self.expanded_state.configure(text=state.replace("_", " "))
        try:
            while True:
                kind, value = self.runtime.events.get_nowait()
                if kind == "transcript":
                    self._append_transcript(value)
                elif kind == "state":
                    pass
                elif kind == "error":
                    logger.warning("Desktop runtime: %s", value)
                    if self.expanded:
                        self._append_transcript(Transcript("FRIDAY", f"I could not start the voice session: {value}"))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _install_hotkey(self) -> None:
        # Native global shortcut on Windows. Tk does not receive WM_HOTKEY
        # directly, so use a tiny polling thread with GetAsyncKeyState.
        if os.name != "nt":
            return

        def watcher() -> None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                VK_CONTROL, VK_SHIFT, VK_SPACE = 0x11, 0x10, 0x20
                was_down = False
                while True:
                    down = bool(
                        user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                        and user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
                        and user32.GetAsyncKeyState(VK_SPACE) & 0x8000
                    )
                    if down and not was_down:
                        self.root.after(0, self.toggle_expanded)
                    was_down = down
                    import time
                    time.sleep(0.05)
            except Exception:
                logger.debug("Global hotkey watcher unavailable", exc_info=True)

        threading.Thread(target=watcher, name="friday-global-hotkey", daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.runtime.stop()
        finally:
            self.root.destroy()


def main() -> None:
    """Launch FRIDAY as a floating desktop assistant."""
    setup_logging(level=get_settings().log_level, log_file=get_settings().log_file, console_level="CRITICAL")
    try:
        credential_pool.preflight_check(model=get_settings().llm_model)
        FridayDesktop().run()
    except Exception as exc:
        logger.exception("Unable to start FRIDAY desktop shell")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("FRIDAY", str(exc))
            root.destroy()
        except Exception:
            raise


__all__ = ["FridayDesktop", "DesktopVoiceRuntime", "main"]
