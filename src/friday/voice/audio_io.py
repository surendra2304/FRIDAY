"""Real-time audio I/O streaming pipeline for FRIDAY voice.

Provides:
- MicrophoneStream: Continuous non-blocking 16 kHz 16-bit mono linear PCM microphone capture.
- SpeakerStream: Low-latency 24 kHz 16-bit mono linear PCM speaker playback with instant interruption purge.
- get_audio_diagnostics(): Hardware audio device discovery and diagnostics.
- check_device_availability(): Fast verification of audio input and output device readiness.
- MockMicrophoneStream / MockSpeakerStream: In-memory deterministic mock audio I/O for tests.
"""

from __future__ import annotations

import asyncio
import queue
import struct
import threading
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

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


def check_device_availability(device_type: str = "input") -> Tuple[bool, Optional[str]]:
    """Check if the requested audio device type ('input' or 'output') is available and functional."""
    if sd is None:
        return False, "sounddevice library unavailable"
    try:
        devices = sd.query_devices()
        if not devices:
            return False, "No audio devices found on system"
        default_in, default_out = sd.default.device
        if device_type == "input":
            if default_in < 0 or default_in >= len(devices):
                return False, "No default audio input device configured"
            in_dev = devices[default_in]
            if in_dev.get("max_input_channels", 0) < 1:
                return False, f"Default input device '{in_dev.get('name')}' has no input channels"
            return True, None
        elif device_type == "output":
            if default_out < 0 or default_out >= len(devices):
                return False, "No default audio output device configured"
            out_dev = devices[default_out]
            if out_dev.get("max_output_channels", 0) < 1:
                return False, f"Default output device '{out_dev.get('name')}' has no output channels"
            return True, None
        else:
            return False, f"Unknown device type '{device_type}'"
    except Exception as e:
        return False, str(e)


class MicrophoneStream:
    """Continuous non-blocking microphone stream capturing 16kHz 16-bit mono PCM."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 40,
        device: Optional[int] = None,
        max_queue_size: int = 100,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.chunk_duration_ms = max(10, min(chunk_duration_ms, 500))
        self.block_size = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))
        self.max_queue_size = max_queue_size

        self._stream: Optional[Any] = None
        self._queue: Optional[asyncio.Queue[bytes]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active = False
        self._error: Optional[str] = None
        # Echo suppression: while muted, captured frames are dropped instead of
        # enqueued (e.g. while the speaker is playing FRIDAY's voice).
        self._muted = False
        self.muted_dropped_frames = 0

        self.overflow_count = 0
        self.captured_chunks = 0
        self.captured_bytes = 0

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

        self._queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._active = True
        self._error = None

        def _callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                self.overflow_count += 1
                logger.debug(f"Microphone input buffer overflow (count: {self.overflow_count})")
            if self._active and self._queue is not None:
                pcm_bytes = bytes(indata)
                self.captured_chunks += 1
                self.captured_bytes += len(pcm_bytes)
                if self._loop is not None and not self._loop.is_closed():
                    try:
                        self._loop.call_soon_threadsafe(self._safe_enqueue, pcm_bytes)
                    except Exception:
                        pass
                else:
                    self._safe_enqueue(pcm_bytes)

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
            logger.info(f"MicrophoneStream started ({self.sample_rate}Hz, chunk: {self.chunk_duration_ms}ms, block size: {self.block_size})")
        except Exception as e:
            self._error = f"Failed to start microphone stream: {e}"
            logger.warning(self._error)
            self._active = False
            self._stream = None

    def set_muted(self, muted: bool) -> None:
        """Mute/unmute capture: muted frames are dropped, not enqueued.

        Used for speaker-echo suppression (half-duplex): the speaker stream
        mutes the mic while it is playing and unmutes once playback drains.
        Cheap atomic bool flip — safe from audio callbacks and any thread.
        """
        self._muted = bool(muted)

    @property
    def is_muted(self) -> bool:
        return self._muted

    def _safe_enqueue(self, pcm_bytes: bytes) -> None:
        """Safely push chunk into queue, dropping oldest if full to avoid unbounded memory."""
        if self._muted:
            # Echo suppression: drop the frame entirely (never echo FRIDAY's
            # own speaker output back to the server as user input).
            self.muted_dropped_frames += 1
            return
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            self.overflow_count += 1
            try:
                self._queue.get_nowait()
            except Exception:
                pass
            try:
                self._queue.put_nowait(pcm_bytes)
            except Exception:
                pass

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
            await asyncio.sleep(0.02)
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

    @property
    def queue_size(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0


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
        self._remainder = bytearray()
        self._lock = threading.Lock()
        self._error: Optional[str] = None
        # Echo suppression: optionally mute a MicrophoneStream while playing
        self._mic_to_mute: Optional["MicrophoneStream"] = None
        self._playing = False
        self._drain_blocks = 0

        self.underflow_count = 0
        self.overflow_count = 0
        self.played_chunks = 0
        self.played_bytes = 0

    def set_echo_mute_target(self, mic: Optional["MicrophoneStream"]) -> None:
        """Wire a MicrophoneStream to be muted while this speaker is playing."""
        self._mic_to_mute = mic

    def _mute_mic(self) -> None:
        if self._mic_to_mute is not None:
            try:
                self._mic_to_mute.set_muted(True)
            except Exception:
                pass

    def _maybe_unmute(self) -> None:
        """Unmute the mic after playback fully drains.

        Requires a few consecutive empty output blocks (hardware buffer tail
        latency) so the speaker has physically finished sounding before the
        microphone resumes. Called from the audio callback — must stay cheap.
        """
        if self._mic_to_mute is None or not self._playing:
            return
        if not self._queue.empty() or self._remainder:
            self._drain_blocks = 0
            return
        self._drain_blocks += 1
        if self._drain_blocks >= 3:
            self._playing = False
            self._drain_blocks = 0
            try:
                self._mic_to_mute.set_muted(False)
            except Exception:
                pass

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
            if status and status.output_underflow:
                self.underflow_count += 1
            bytes_needed = frames * 2 * self.channels  # 2 bytes per 16-bit sample
            out_chunk = bytearray()

            with self._lock:
                # 1. Drain any leftover remainder from previous partial chunk
                if self._remainder:
                    if len(self._remainder) <= bytes_needed:
                        out_chunk.extend(self._remainder)
                        self._remainder.clear()
                    else:
                        out_chunk.extend(self._remainder[:bytes_needed])
                        del self._remainder[:bytes_needed]

                # 2. Pull queued chunks if more bytes needed
                while len(out_chunk) < bytes_needed and self._active:
                    try:
                        data = self._queue.get_nowait()
                        needed = bytes_needed - len(out_chunk)
                        if len(data) <= needed:
                            out_chunk.extend(data)
                        else:
                            out_chunk.extend(data[:needed])
                            self._remainder.extend(data[needed:])
                    except queue.Empty:
                        break

                # 2b. Echo suppression: unmute the mic once playback drains
                self._maybe_unmute()

            # 3. Pad with silence if underflow occurs
            if len(out_chunk) < bytes_needed:
                out_chunk.extend(b"\x00" * (bytes_needed - len(out_chunk)))

            outdata[:] = bytes(out_chunk)
            self.played_bytes += len(out_chunk)

        try:
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                blocksize=512,
                device=self.device,
                channels=self.channels,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            logger.info(f"SpeakerStream started ({self.sample_rate}Hz, 16-bit mono PCM, blocksize: 512)")
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
                self.played_chunks += 1
            except queue.Full:
                self.overflow_count += 1
                # Drop oldest chunk if buffer is overwhelmed
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                self._queue.put_nowait(pcm_bytes)
                self.played_chunks += 1
            # Echo suppression: mute the mic the moment playback begins
            if not self._playing:
                self._playing = True
                self._drain_blocks = 0
                self._mute_mic()

    def stop(self) -> None:
        """Instantly purge all buffered playback chunks and remainder (barge-in interruption)."""
        with self._lock:
            self._remainder.clear()
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        # Playback ceased (purged): the mic may resume immediately
        self._playing = False
        self._drain_blocks = 0
        if self._mic_to_mute is not None:
            try:
                self._mic_to_mute.set_muted(False)
            except Exception:
                pass
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
        with self._lock:
            return self._queue.qsize() + (1 if len(self._remainder) > 0 else 0)

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._active and (self._queue.qsize() > 0 or len(self._remainder) > 0)

    @property
    def error(self) -> Optional[str]:
        return self._error


def compute_pcm_rms(pcm_bytes: bytes) -> float:
    """Compute Root Mean Square (RMS) energy for 16-bit linear PCM audio."""
    if not pcm_bytes:
        return 0.0
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

    def __init__(
        self,
        sample_rate: int = 16000,
        chunks: Optional[List[bytes]] = None,
        simulate_error: Optional[str] = None,
    ):
        self.sample_rate = sample_rate
        self.chunks = list(chunks or [])
        self.simulate_error = simulate_error
        self._active = False
        self._error = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        if self.simulate_error:
            self._error = self.simulate_error
            self._active = False
            return
        self._active = True
        self._error = None
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

    @property
    def error(self) -> Optional[str]:
        return self._error


class MockSpeakerStream:
    """Mock speaker stream storing played chunks in an in-memory list for unit tests."""

    def __init__(
        self,
        sample_rate: int = 24000,
        simulate_error: Optional[str] = None,
    ):
        self.sample_rate = sample_rate
        self.played_chunks: List[bytes] = []
        self.simulate_error = simulate_error
        self._active = False
        self._error = None
        self.interrupted_count = 0

    def start(self) -> None:
        if self.simulate_error:
            self._error = self.simulate_error
            self._active = False
            return
        self._active = True
        self._error = None

    def play_chunk(self, pcm_bytes: bytes) -> None:
        if self._active and pcm_bytes:
            self.played_chunks.append(pcm_bytes)

    def stop(self) -> None:
        self.interrupted_count += 1
        self.played_chunks.clear()

    @property
    def is_playing(self) -> bool:
        return len(self.played_chunks) > 0

    @property
    def queue_size(self) -> int:
        return len(self.played_chunks)

    def close(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def error(self) -> Optional[str]:
        return self._error
