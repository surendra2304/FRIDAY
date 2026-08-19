"""Real-time audio I/O streaming pipeline for FRIDAY voice.

Provides:
- MicrophoneStream: Continuous 16 kHz 16-bit mono linear PCM microphone capture.
- SpeakerStream: Low-latency 24 kHz 16-bit mono linear PCM speaker playback with instant interruption purge.
- get_audio_diagnostics(): Hardware audio device discovery and diagnostics.
- MockMicrophoneStream / MockSpeakerStream: In-memory deterministic mock audio I/O for tests.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("voice.audio_io")

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore


def get_audio_diagnostics() -> Dict[str, Any]:
    """Retrieve diagnostic information for local audio hardware."""
    if sd is None:
        return {
            "driver_available": False,
            "error": "sounddevice library is not installed",
            "devices": [],
            "default_input": None,
            "default_output": None,
        }

    try:
        devices = sd.query_devices()
        default_in, default_out = sd.default.device
        dev_list = []
        for idx, d in enumerate(devices):
            dev_list.append({
                "index": idx,
                "name": d.get("name", "Unknown"),
                "max_input_channels": d.get("max_input_channels", 0),
                "max_output_channels": d.get("max_output_channels", 0),
                "default_samplerate": d.get("default_samplerate", 0),
                "is_default_input": idx == default_in,
                "is_default_output": idx == default_out,
            })
        return {
            "driver_available": True,
            "device_count": len(devices),
            "default_input": default_in,
            "default_output": default_out,
            "devices": dev_list,
        }
    except Exception as e:
        return {
            "driver_available": True,
            "error": f"Failed to query audio devices: {e}",
            "devices": [],
        }


class MicrophoneStream:
    """Continuous non-blocking microphone stream capturing 16kHz 16-bit mono PCM."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 100,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.block_size = int(self.sample_rate * (chunk_duration_ms / 1000.0))
        self._stream: Optional[Any] = None
        self._queue: Optional[asyncio.Queue[bytes]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active = False
        self._error: Optional[str] = None

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start capturing audio chunks from the microphone."""
        if self._active:
            return
        if sd is None:
            self._error = "sounddevice library unavailable"
            logger.warning(self._error)
            return

        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._queue = asyncio.Queue()
        self._active = True
        self._error = None

        def _callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                logger.debug("Microphone input buffer overflow")
            if self._active and self._queue is not None:
                pcm_bytes = bytes(indata)
                if self._loop is not None and not self._loop.is_closed():
                    try:
                        self._loop.call_soon_threadsafe(self._queue.put_nowait, pcm_bytes)
                    except Exception:
                        pass
                else:
                    try:
                        self._queue.put_nowait(pcm_bytes)
                    except Exception:
                        pass

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                device=self.device,
                channels=self.channels,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            logger.info(f"MicrophoneStream started ({self.sample_rate}Hz, block size: {self.block_size})")
        except Exception as e:
            self._error = f"Failed to start microphone stream: {e}"
            logger.warning(self._error)
            self._active = False
            self._stream = None

    def stop(self) -> None:
        """Stop microphone capture and close the input stream."""
        self._active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug(f"Error closing microphone stream: {e}")
            self._stream = None
        logger.debug("MicrophoneStream stopped")

    async def read_chunk(self) -> bytes:
        """Read the next captured 16kHz PCM chunk from the queue."""
        if not self._active or self._queue is None:
            await asyncio.sleep(0.05)
            return b""
        try:
            return await self._queue.get()
        except Exception:
            return b""

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        """Yield captured PCM audio chunks indefinitely while active."""
        while self._active:
            chunk = await self.read_chunk()
            if chunk:
                yield chunk

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def error(self) -> Optional[str]:
        return self._error


class SpeakerStream:
    """Low-latency raw PCM output stream with instant interruption/purge capabilities."""

    def __init__(
        self,
        sample_rate: int = 24000,
        channels: int = 1,
        device: Optional[int] = None,
        max_buffer_chunks: int = 100,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._stream: Optional[Any] = None
        self._active = False
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_buffer_chunks)
        self._lock = threading.Lock()
        self._error: Optional[str] = None

    def start(self) -> None:
        """Start the speaker audio output stream."""
        if self._active:
            return
        if sd is None:
            self._error = "sounddevice library unavailable"
            logger.warning(self._error)
            return

        self._active = True
        self._error = None

        def _callback(outdata, frames, time_info, status):
            bytes_needed = frames * 2 * self.channels  # 2 bytes per 16-bit sample
            out_chunk = bytearray()

            while len(out_chunk) < bytes_needed and self._active:
                try:
                    data = self._queue.get_nowait()
                    out_chunk.extend(data)
                except queue.Empty:
                    break

            if len(out_chunk) < bytes_needed:
                # Pad with silence if buffer is empty
                out_chunk.extend(b"\x00" * (bytes_needed - len(out_chunk)))
            elif len(out_chunk) > bytes_needed:
                # Put back excess bytes into front of queue
                excess = bytes(out_chunk[bytes_needed:])
                self._queue.put(excess)
                out_chunk = out_chunk[:bytes_needed]

            outdata[:] = bytes(out_chunk)

        try:
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                device=self.device,
                channels=self.channels,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            logger.info(f"SpeakerStream started ({self.sample_rate}Hz, 16-bit mono PCM)")
        except Exception as e:
            self._error = f"Failed to start speaker stream: {e}"
            logger.warning(self._error)
            self._active = False
            self._stream = None

    def play_chunk(self, pcm_bytes: bytes) -> None:
        """Enqueue a 24kHz 16-bit PCM chunk for immediate playback."""
        if not self._active or not pcm_bytes:
            return
        with self._lock:
            try:
                self._queue.put_nowait(pcm_bytes)
            except queue.Full:
                # Drop oldest chunk if buffer is overwhelmed
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                self._queue.put_nowait(pcm_bytes)

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

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def is_playing(self) -> bool:
        return self._active and self._queue.qsize() > 0


def compute_pcm_rms(pcm_bytes: bytes) -> float:
    """Compute Root Mean Square (RMS) energy for 16-bit linear PCM audio."""
    if not pcm_bytes:
        return 0.0
    import struct
    count = len(pcm_bytes) // 2
    if count == 0:
        return 0.0
    try:
        samples = struct.unpack(f"<{count}h", pcm_bytes[: count * 2])
        sum_sq = sum(s * s for s in samples)
        return (sum_sq / count) ** 0.5
    except Exception:
        return 0.0


class MockMicrophoneStream:
    """Mock microphone stream yielding predefined PCM audio chunks for unit tests."""

    def __init__(self, sample_rate: int = 16000, chunks: Optional[List[bytes]] = None):
        self.sample_rate = sample_rate
        self.chunks = list(chunks or [])
        self._active = False
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._active = True
        for c in self.chunks:
            self._queue.put_nowait(c)

    def stop(self) -> None:
        self._active = False

    async def read_chunk(self) -> bytes:
        if not self._active or self._queue.empty():
            await asyncio.sleep(0.01)
            return b""
        return await self._queue.get()

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        while self._active and not self._queue.empty():
            yield await self.read_chunk()

    @property
    def is_active(self) -> bool:
        return self._active


class MockSpeakerStream:
    """Mock speaker stream storing played chunks in an in-memory list for unit tests."""

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self.played_chunks: List[bytes] = []
        self._active = False
        self.interrupted_count = 0

    def start(self) -> None:
        self._active = True

    def play_chunk(self, pcm_bytes: bytes) -> None:
        if self._active and pcm_bytes:
            self.played_chunks.append(pcm_bytes)

    def stop(self) -> None:
        self.interrupted_count += 1
        self.played_chunks.clear()

    def close(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active
