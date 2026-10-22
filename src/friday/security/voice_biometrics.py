"""Voice biometrics (speaker recognition) for FRIDAY.

Enrolls the owner's voice into a 256-dimensional embedding (resemblyzer)
and verifies incoming audio against it with cosine similarity. When no
profile exists (or the library is unavailable) ALL voices are allowed —
biometrics never locks the owner out of a fresh install.

Security note: this is convenience gating for a personal assistant, not
cryptographic authentication — the Gemini API key itself remains the
secret. Toggled by FRIDAY_VOICE_BIOMETRICS_ENABLED (default false).
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("security.voice_biometrics")

PROFILE_PATH = Path("data/voice_profile.npy")
SIMILARITY_THRESHOLD = 0.75
EMBEDDING_DIM = 256
# Verification window: resemblyzer needs ~1s+ of speech; 2s is reliable
_VERIFICATION_WINDOW_FRAMES = 50  # 50 x 40ms = 2s


def _get_encoder():
    """Lazily load the resemblyzer VoiceEncoder (CPU, ~150ms per embedding)."""
    from resemblyzer import VoiceEncoder

    return VoiceEncoder(verbose=False)


def pcm_to_float(pcm_bytes: bytes) -> Any:
    """Convert int16 PCM to float32 in [-1, 1] as expected by resemblyzer."""
    import numpy as np

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


class VoiceProfileManager:
    """Enroll and verify a single speaker's voice profile."""

    def __init__(
        self,
        profile_path: Path = PROFILE_PATH,
        threshold: float = SIMILARITY_THRESHOLD,
    ):
        self.profile_path = Path(profile_path)
        self.threshold = threshold
        self._encoder = None
        self._profile: Any = None

    # -- internals -----------------------------------------------------------

    def _ensure_encoder(self):
        if self._encoder is None:
            self._encoder = _get_encoder()
        return self._encoder

    def _embed(self, wav: Any) -> Any:
        import numpy as np

        if len(wav) < 16000:  # pad sub-second audio to the encoder minimum
            wav = np.pad(wav, (0, 16000 - len(wav)))
        return self._ensure_encoder().embed_utterance(wav)

    def _load_profile(self) -> Any | None:
        if self._profile is not None:
            return self._profile
        try:
            if self.profile_path.is_file():
                import numpy as np

                self._profile = np.load(self.profile_path)
        except Exception as e:
            logger.warning(f"Could not load voice profile: {e}")
        return self._profile

    # -- public API ------------------------------------------------------------

    def is_enrolled(self) -> bool:
        return self._load_profile() is not None

    @property
    def verification_window_frames(self) -> int:
        return _VERIFICATION_WINDOW_FRAMES

    def enroll_from_frames(self, frames, sample_rate: int = 16000) -> bool:
        """Process recorded PCM frames into an embedding and save the profile."""
        try:
            import numpy as np

            wav = np.concatenate([pcm_to_float(f) for f in frames if f])
            if sample_rate != 16000:
                ratio = sample_rate / 16000
                indices = np.arange(0, len(wav), ratio).astype(int)
                wav = wav[indices]
            embedding = self._embed(wav)
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(self.profile_path, embedding)
            self._profile = embedding
            logger.info(
                f"Voice profile enrolled ({EMBEDDING_DIM}-dim embedding, "
                f"{len(wav)/16000:.1f}s audio) -> {self.profile_path}"
            )
            return True
        except Exception as e:
            logger.error(f"Voice enrollment failed: {e}")
            return False

    async def enroll_voice(self, duration: float = 5.0, sample_rate: int = 16000) -> bool:
        """Record `duration` seconds from the microphone and enroll the speaker."""
        print(f"Please speak for {duration:.0f} seconds to enroll your voice...")
        from friday.voice.audio_io import MicrophoneStream

        mic = MicrophoneStream(sample_rate=sample_rate)
        mic.start()  # inside a running loop: captures the loop automatically
        try:
            if not mic.is_active or mic.error:
                logger.error(f"Microphone unavailable for enrollment: {mic.error}")
                return False
            frames = []
            deadline = time.time() + duration
            while time.time() < deadline:
                chunk = await mic.read_chunk()  # async: mic queue consumption
                if chunk:
                    frames.append(chunk)
                else:
                    await asyncio.sleep(0.01)
        finally:
            mic.stop()

        if not frames:
            logger.error("No audio captured during enrollment.")
            return False
        return self.enroll_from_frames(frames, sample_rate)

    def verify_speaker(self, audio_chunk: bytes) -> bool:
        """True if the audio matches the enrolled profile.

        Backward compatible: with no enrolled profile (or a broken embedding
        pipeline) ALL voices are allowed.
        """
        profile = self._load_profile()
        if profile is None:
            return True
        try:
            import numpy as np

            wav = pcm_to_float(audio_chunk)
            embedding = self._embed(wav)
            similarity = float(np.dot(profile, embedding) /
                                (np.linalg.norm(profile) * np.linalg.norm(embedding) + 1e-9))
            return similarity >= self.threshold
        except Exception as e:
            logger.warning(f"Speaker verification error (allowing): {e}")
            return True

    def similarity(self, audio_chunk: bytes) -> float | None:
        """Cosine similarity against the profile, or None if not enrolled."""
        profile = self._load_profile()
        if profile is None:
            return None
        try:
            import numpy as np

            embedding = self._embed(pcm_to_float(audio_chunk))
            return float(np.dot(profile, embedding) /
                         (np.linalg.norm(profile) * np.linalg.norm(embedding) + 1e-9))
        except Exception:
            return None
