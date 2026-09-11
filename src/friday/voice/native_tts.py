"""High-clarity Windows Native SAPI Text-to-Speech engine for FRIDAY.

Provides:
- NativeTTS: Asynchronous, thread-safe speech synthesis using Windows SAPI.
- Auto-selection of Microsoft Zira Desktop (female English persona) or best available voice.
- Instant barge-in / speech purge on demand.
- Clean text preprocessing (strips markdown, code blocks, URLs, and JSON).
"""

from __future__ import annotations

import queue
import re
import threading
import time
from typing import Optional

from friday.core.logging import get_logger

logger = get_logger("voice.native_tts")

# SAPI 5 Flags
SVSFDefault = 0
SVSFlagsAsync = 1
SVSFPurgeBeforeSpeak = 2


def clean_text_for_speech(text: str) -> str:
    """Preprocess text to make it sound natural and clear when spoken aloud."""
    if not text:
        return ""
    # Strip markdown code blocks
    text = re.sub(r"```[\s\S]*?```", " [code snippet omitted] ", text)
    text = re.sub(r"`[^`]*`", "", text)
    # Strip URLs
    text = re.sub(r"https?://\S+", "web link", text)
    # Strip markdown symbols
    text = re.sub(r"[#*_~>]+", " ", text)
    # Strip JSON-like braces and brackets
    text = re.sub(r"[{}[\]\\]", " ", text)
    # Collapse multiple spaces and trim
    text = re.sub(r"\s+", " ", text).strip()
    return text


class NativeTTS:
    """Thread-safe, non-blocking Windows SAPI Text-to-Speech engine."""

    _instance: Optional[NativeTTS] = None
    _lock = threading.Lock()

    def __new__(cls) -> NativeTTS:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_tts()
            return cls._instance

    def _init_tts(self) -> None:
        self.enabled = False
        self._speech_queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._speech_worker, name="FRIDAY_NativeTTS_Worker", daemon=True
        )
        self._worker_thread.start()
        logger.info("FRIDAY Native SAPI TTS worker initialized.")

    def _speech_worker(self) -> None:
        """Worker thread executing SAPI calls with COM initialization."""
        speaker = None
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch("SAPI.SpVoice")

            # Configure voice: prefer Microsoft Zira or any female voice
            voices = speaker.GetVoices()
            selected_voice = None
            for v in voices:
                desc = v.GetDescription().lower()
                if "zira" in desc or "female" in desc or "eva" in desc or "hazel" in desc:
                    selected_voice = v
                    break
            if selected_voice is not None:
                speaker.Voice = selected_voice
                logger.info(f"Native TTS selected voice: {selected_voice.GetDescription()}")

            # Rate: 0 is normal speed (-10 to 10), Volume: 100 (0 to 100)
            speaker.Rate = 0
            speaker.Volume = 100
        except Exception as e:
            logger.warning(f"Native SAPI TTS could not initialize COM speaker: {e}")
            speaker = None

        while not self._stop_event.is_set():
            try:
                item = self._speech_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            text, purge = item
            if not self.enabled or not speaker:
                self._speech_queue.task_done()
                continue

            try:
                flags = SVSFlagsAsync
                if purge:
                    flags |= SVSFPurgeBeforeSpeak
                clean_text = clean_text_for_speech(text)
                if clean_text:
                    speaker.Speak(clean_text, flags)
            except Exception as e:
                logger.warning(f"Error speaking text with SAPI: {e}")
            finally:
                self._speech_queue.task_done()

    def speak(self, text: str, interrupt: bool = False) -> None:
        """Enqueue text to be spoken asynchronously.

        Args:
            text: The text string to speak.
            interrupt: If True, purges any queued/currently speaking audio first.
        """
        if not self.enabled or not text or not text.strip():
            return
        if interrupt:
            self.stop()
        self._speech_queue.put((text.strip(), interrupt))

    def stop(self) -> None:
        """Immediately stop speaking and clear any queued utterances."""
        try:
            while not self._speech_queue.empty():
                try:
                    self._speech_queue.get_nowait()
                    self._speech_queue.task_done()
                except Exception:
                    break
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            spk = win32com.client.Dispatch("SAPI.SpVoice")
            spk.Speak("", SVSFlagsAsync | SVSFPurgeBeforeSpeak)
        except Exception:
            pass


# Global singleton instance
native_tts = NativeTTS()
