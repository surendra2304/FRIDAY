"""Live transcript printing for Gemini Live sessions.

Renders the conversation live in the terminal as it streams:
  - "You: ..."    from input_transcription fragments, while the user speaks
  - "FRIDAY: ..." from output_transcription (or model-turn text), as spoken
Turn boundaries close open lines; fallbacks print only content the live
streams missed. Shared by the CLI voice mode and the interactive diagnostic.
"""

from collections.abc import Callable
from typing import Any
import re


def speakable_action_receipt(text: str) -> str:
    """Reduce a controller result to a short, user-facing spoken receipt."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return ""
    if "always-on-top" in clean.casefold() or "kept it in front" in clean.casefold():
        return "Chrome opened, but another window stayed in front."
    if "remained focused" in clean.casefold() or "confirmed its window remained focused" in clean.casefold():
        return "Chrome is open and in front." if "chrome" in clean.casefold() else "The app is open and in front."
    if any(token in clean.casefold() for token in ("could not", "couldn't", "failed", "did not", "didn't", "unable")):
        return clean[:220]
    return clean[:220]


class LiveTranscriptPrinter:
    """Prints user/FRIDAY transcripts live from serverContent callbacks."""

    def __init__(self, turn_log: list[tuple[float, str, str]] | None = None, clock: Callable[[], float] | None = None):
        import time as _time

        self._time = clock if clock is not None else _time.perf_counter
        self.turn_log = turn_log if turn_log is not None else []
        self._state: dict[str, bool] = {
            "user_streaming": False,
            "user_turn_streamed": False,
            "user_last": False,
            "friday_streaming": False,
            "friday_turn_streamed": False,
            "friday_last": False,
        }
        self._turn_started_at: float | None = None
        self._last_latency_ms: float | None = None

    # -- internal helpers ---------------------------------------------------

    def _print(self, text: str, **kwargs) -> None:
        print(text, **kwargs)

    def _close_user_line(self) -> None:
        if self._state["user_streaming"]:
            self._print("")
            self._state["user_streaming"] = False

    def _close_friday_line(self) -> None:
        if self._state["friday_streaming"]:
            self._print("")
            self._state["friday_streaming"] = False

    def _print_friday(self, text: str) -> None:
        self._close_user_line()  # FRIDAY starts speaking: finish the user's line
        if not text:
            return
        if not self._state["friday_streaming"]:
            self._print("FRIDAY: ", end="", flush=True)
        self._print(text, end="", flush=True)
        self._state["friday_streaming"] = True
        self._state["friday_turn_streamed"] = True

    # -- public callbacks ----------------------------------------------------

    def on_server_content(self, server_content: Any) -> None:
        """Live-stream both sides of the conversation from serverContent."""
        # 1. User speech (input transcription) — streams while the user talks
        in_tx = getattr(server_content, "input_transcription", None)
        if in_tx and getattr(in_tx, "text", None):
            if self._turn_started_at is None:
                self._turn_started_at = self._time()
            if not self._state["user_streaming"]:
                self._print("\nYou: ", end="", flush=True)
                self._state["user_streaming"] = True
            self._print(in_tx.text, end="", flush=True)
            self._state["user_turn_streamed"] = True

        # 2. FRIDAY's speech: output transcription (preferred)
        out_tx = getattr(server_content, "output_transcription", None)
        if out_tx and getattr(out_tx, "text", None):
            self._print_friday(out_tx.text)

        # 3. Fallback/complement: text parts of the model turn
        model_turn = getattr(server_content, "model_turn", None)
        if model_turn and getattr(model_turn, "parts", None):
            for part in model_turn.parts:
                if getattr(part, "text", None):
                    self._print_friday(part.text)

        # 4. Turn boundary: close open lines, latch what streamed
        if getattr(server_content, "turn_complete", False):
            self._close_user_line()
            self._close_friday_line()
            self._state["user_last"] = self._state["user_turn_streamed"]
            self._state["friday_last"] = self._state["friday_turn_streamed"]
            self._state["user_turn_streamed"] = False
            self._state["friday_turn_streamed"] = False

    def on_turn_complete(self, user_text: str, agent_text: str) -> None:
        """Log the turn and print fallbacks only for content the streams missed."""
        completed_at = self._time()
        self.turn_log.append((completed_at, user_text, agent_text))
        elapsed_ms = (completed_at - self._turn_started_at) * 1000 if self._turn_started_at is not None else None
        self._turn_started_at = None
        if elapsed_ms is not None:
            self._last_latency_ms = elapsed_ms
        if user_text and not self._state["user_last"]:
            self._print(f"\nYou: {user_text or '(untranscribed)'}")
        if agent_text and not self._state["friday_last"]:
            self._print(f"FRIDAY: {(agent_text or '').strip() or '(untranscribed)'}")
        self._state["user_last"] = False
        self._state["friday_last"] = False
        self._state["friday_streaming"] = False
        self._state["user_streaming"] = False
        if user_text or agent_text:
            try:
                from friday.cli.main import _console, render_status_panel
                from friday.observability.timeline import global_timeline
                global_timeline.update_status(
                    cognitive_phase="LIVE_VOICE",
                    active_agent="VoiceAgent",
                    selected_provider="GeminiLive",
                    last_latency_ms=self._last_latency_ms,
                )
                if _console is not None:
                    _console.print(render_status_panel())
            except Exception:
                pass
            self._print("")  # blank separator line between turns
