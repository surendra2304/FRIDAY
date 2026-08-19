"""Real-time audio I/O streams for Gemini Live.

Implements:
- MicrophoneStream: Continuous 16 kHz 16-bit mono PCM capture.
- SpeakerStream: Low-latency 24 kHz 16-bit mono PCM playback with instant barge-in purge.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncIterator, Optional

from friday.core.logging import get_logger

logger = get_logger("voice.audio_io")

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore


class MicrophoneStream:
    """Continuous non-blocking microphone stream capturing 16kHz 16-bit PCM."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 100,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = int(self.sample_rate * (chunk_duration_ms / 1000.0))
        self._stream: Optional[Any] = None
        self._queue: Optional[asyncio.Queue[bytes]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active = False

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start recording from the default input device."""
        if self._active:
            return
        if sd is None:
            logger.warning("sounddevice is not installed; microphone stream unavailable")
            return

        self._loop = loop or asyncio.get_event_loop()
        self._queue = asyncio.Queue()
        self._active = True

        def _callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                logger.debug("Microphone input overflow")
            if self._active and self._queue is not None and self._loop is not None:
                pcm_bytes = indata.tobytes()
                self._loop.call_soon_threadsafe(self._queue.put_nowait, pcm_bytes)

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=self.channels,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            logger.debug(f"MicrophoneStream started ({self.sample_rate}Hz, block size: {self.block_size})")
        except Exception as e:
            logger.warning(f"Failed to open microphone audio stream: {e}")
            self._active = False

    def stop(self) -> None:
        """Stop microphone capture and release resources."""
        self._active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug(f"Error closing microphone stream: {e}")
            self._stream = None

    async def read_chunk(self) -> bytes:
        """Read the next PCM chunk from the capture queue."""
        if not self._active or self._queue is None:
            await asyncio.sleep(0.05)
            return b""
        try:
            return await self._queue.get()
        except Exception:
            return b""

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        """Yield captured PCM chunks indefinitely while active."""
        while self._active:
            chunk = await self.read_chunk()
            if chunk:
                yield chunk

    @property
    def is_active(self) -> bool:
        return self._active


class SpeakerStream:
    """Low-latency raw PCM output stream with instant interruption/purge capabilities."""

    def __init__(
        self,
        sample_rate: int = 24000,
        channels: int = 1,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream: Optional[Any] = None
        self._active = False
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Initialize the audio output stream."""
        if self._active:
            return
        if sd is None:
            logger.warning("sounddevice is not installed; speaker stream unavailable")
            return

        self._active = True

        def _callback(outdata, frames, time_info, status):
            if status and status.output_underflow:
                pass
            bytes_needed = frames * 2 * self.channels  # 2 bytes per int16 sample
            out_chunk = bytearray()
            
            while len(out_chunk) < bytes_needed and self._active:
                try:
                    data = self._queue.get_nowait()
                    out_chunk.extend(data)
                except queue.Empty:
                    break

            if len(out_chunk) < bytes_needed:
                out_chunk.extend(b"\x00" * (bytes_needed - len(out_chunk)))
            elif len(out_chunk) > bytes_needed:
                # Put back excess
                excess = bytes(out_chunk[bytes_needed:])
                self._queue.put(excess)
                out_chunk = out_chunk[:bytes_needed]

            outdata[:] = bytes(out_chunk)

        try:
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            logger.debug(f"SpeakerStream started ({self.sample_rate}Hz, 16-bit PCM)")
        except Exception as e:
            logger.warning(f"Failed to open speaker audio stream: {e}")
            self._active = False

    def play_chunk(self, pcm_bytes: bytes) -> None:
        """Enqueue a 24kHz 16-bit PCM chunk for immediate playback."""
        if not self._active or not pcm_bytes:
            return
        with self._lock:
            self._queue.put(pcm_bytes)

    def stop(self) -> None:
        """Instantly purge all buffered playback chunks (barge-in interruption)."""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        logger.debug("SpeakerStream playback queue purged (barge-in)")

    def close(self) -> None:
        """Shut down the speaker stream completely."""
        self.stop()
        self._active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug(f"Error closing speaker stream: {e}")
            self._stream = None

    @property
    def is_active(self) -> bool:
        return self._active
