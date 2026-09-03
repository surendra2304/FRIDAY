"""Face biometrics and identity verification for FRIDAY.

Provides enrollment, verification, and multi-profile identity management.
Enrolls face features into local profiles with configurable thresholds.
Integrates with FRIDAY's authentication state without bypassing safety gates:
dangerous actions still require explicit FRIDAY authorization.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from friday.core.config import get_settings
from friday.core.logging import get_logger

logger = get_logger("security.face_biometrics")

DEFAULT_PROFILE_DIR = Path("data/face_profiles")
DEFAULT_THRESHOLD = 0.70


@dataclass
class FaceProfile:
    """Represents an enrolled user identity profile."""

    user_id: str
    name: str
    enrolled_at: float
    samples_count: int
    feature_vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaceProfile:
        return cls(
            user_id=data["user_id"],
            name=data["name"],
            enrolled_at=data.get("enrolled_at", time.time()),
            samples_count=data.get("samples_count", 1),
            feature_vector=data.get("feature_vector", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class FaceVerificationResult:
    """Outcome of a facial identity verification attempt."""

    is_matched: bool
    user_id: str | None = None
    user_name: str | None = None
    confidence: float = 0.0
    bounding_box: tuple[int, int, int, int] | None = None
    error_message: str | None = None


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two feature vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


class FaceProfileManager:
    """Manage local face profiles and evaluate camera frames for biometric identity."""

    def __init__(
        self,
        profile_dir: Path | str = DEFAULT_PROFILE_DIR,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.threshold = threshold
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._profiles_cache: dict[str, FaceProfile] = {}
        self._load_all_profiles()

    def _load_all_profiles(self) -> None:
        """Load all saved profiles from the profile directory."""
        self._profiles_cache.clear()
        if not self.profile_dir.exists():
            return
        for file in self.profile_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = FaceProfile.from_dict(data)
                self._profiles_cache[profile.user_id] = profile
            except Exception as e:
                logger.warning(f"Failed to load face profile '{file}': {e}")

    def list_profiles(self) -> list[dict[str, Any]]:
        """Return summary of all currently enrolled profiles."""
        self._load_all_profiles()
        return [
            {
                "user_id": p.user_id,
                "name": p.name,
                "enrolled_at": p.enrolled_at,
                "samples_count": p.samples_count,
            }
            for p in self._profiles_cache.values()
        ]

    def delete_profile(self, user_id: str) -> bool:
        """Delete an enrolled face profile."""
        profile_file = self.profile_dir / f"{user_id}.json"
        if profile_file.exists():
            try:
                profile_file.unlink()
                self._profiles_cache.pop(user_id, None)
                logger.info(f"Face profile for user '{user_id}' deleted.")
                return True
            except Exception as e:
                logger.error(f"Error deleting profile '{user_id}': {e}")
                return False
        return False

    def extract_features(self, image: Any) -> list[float] | None:
        """Extract a normalized 128-dimensional feature representation from a face crop."""
        try:
            import cv2
            import numpy as np

            # If input is a path or bytes, load image
            if isinstance(image, (str, Path)):
                img = cv2.imread(str(image))
            elif isinstance(image, bytes):
                nparr = np.frombuffer(image, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                img = image

            if img is None:
                return None

            # Resize to standard size (64x64) and convert to grayscale
            resized = cv2.resize(img, (64, 64))
            if len(resized.shape) == 3 and resized.shape[2] == 3:
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            else:
                gray = resized

            # Normalize intensity
            normalized = cv2.equalizeHist(gray)

            # Compute block spatial gradients and cell histograms (128 dimensions)
            gx = cv2.Sobel(normalized, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(normalized, cv2.CV_32F, 0, 1, ksize=3)
            mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)

            # 4x4 spatial grid with 8 orientation bins each = 16 * 8 = 128-dim vector
            hist = []
            for i in range(4):
                for j in range(4):
                    cell_mag = mag[i * 16 : (i + 1) * 16, j * 16 : (j + 1) * 16]
                    cell_ang = ang[i * 16 : (i + 1) * 16, j * 16 : (j + 1) * 16]
                    cell_hist, _ = np.histogram(cell_ang, bins=8, range=(0, 360), weights=cell_mag)
                    hist.extend(cell_hist.tolist())

            # L2 normalize
            norm = math.sqrt(sum(x * x for x in hist))
            if norm == 0.0:
                # Fallback to downsampled spatial luminance
                sub = cv2.resize(normalized, (16, 8)).astype(np.float32).flatten()
                norm = float(np.linalg.norm(sub)) or 1.0
                hist = (sub / norm).tolist()
                norm = 1.0

            return [round(x / norm, 6) for x in hist]

        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}")
            return None

    def enroll_face(
        self,
        user_id: str,
        name: str,
        frames: list[Any] | None = None,
        camera_index: int = 0,
        max_samples: int = 5,
    ) -> tuple[bool, str]:
        """Enroll a user profile from given frames or by capturing from camera."""
        collected_features: list[list[float]] = []

        if frames:
            for frame in frames:
                feat = self.extract_features(frame)
                if feat:
                    collected_features.append(feat)
        else:
            # Capture from webcam
            try:
                import cv2

                cap = cv2.VideoCapture(camera_index)
                if not cap.isOpened():
                    return False, f"Could not access camera at index {camera_index}."

                for _ in range(max_samples * 2):
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    feat = self.extract_features(frame)
                    if feat:
                        collected_features.append(feat)
                        if len(collected_features) >= max_samples:
                            break
                    time.sleep(0.1)

                cap.release()
            except ImportError:
                return False, "OpenCV (cv2) is required for camera capture."
            except Exception as e:
                return False, f"Camera error during enrollment: {e}"

        if not collected_features:
            return False, "No valid facial features could be extracted."

        # Average feature vector
        num_feats = len(collected_features)
        dim = len(collected_features[0])
        avg_vector = [0.0] * dim
        for feat in collected_features:
            for i in range(dim):
                avg_vector[i] += feat[i] / num_feats

        norm = math.sqrt(sum(x * x for x in avg_vector)) or 1.0
        final_vector = [round(x / norm, 6) for x in avg_vector]

        profile = FaceProfile(
            user_id=user_id.strip(),
            name=name.strip(),
            enrolled_at=time.time(),
            samples_count=len(collected_features),
            feature_vector=final_vector,
        )

        profile_path = self.profile_dir / f"{profile.user_id}.json"
        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2)
            self._profiles_cache[profile.user_id] = profile
            logger.info(f"Successfully enrolled face profile for '{name}' (ID: {user_id}).")
            return True, f"Face profile successfully enrolled for '{name}'."
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")
            return False, f"Failed to save face profile: {e}"

    def verify_face(
        self,
        frame: Any = None,
        camera_index: int = 0,
        user_id: str | None = None,
    ) -> FaceVerificationResult:
        """Verify the user in front of the camera against enrolled profiles."""
        self._load_all_profiles()

        if not self._profiles_cache:
            return FaceVerificationResult(
                is_matched=False,
                error_message="No face profiles are currently enrolled in FRIDAY.",
            )

        captured_features = None

        if frame is not None:
            captured_features = self.extract_features(frame)
        else:
            try:
                import cv2

                cap = cv2.VideoCapture(camera_index)
                if not cap.isOpened():
                    return FaceVerificationResult(
                        is_matched=False,
                        error_message=f"Could not open camera at index {camera_index}.",
                    )

                ret, captured_frame = cap.read()
                cap.release()

                if not ret or captured_frame is None:
                    return FaceVerificationResult(
                        is_matched=False,
                        error_message="Failed to capture frame from camera.",
                    )

                captured_features = self.extract_features(captured_frame)
            except ImportError:
                return FaceVerificationResult(
                    is_matched=False,
                    error_message="OpenCV is required for camera verification.",
                )
            except Exception as e:
                return FaceVerificationResult(
                    is_matched=False,
                    error_message=f"Camera verification error: {e}",
                )

        if not captured_features:
            return FaceVerificationResult(
                is_matched=False,
                error_message="No face detected in the camera frame.",
            )

        # Target specific profile if requested, otherwise check best match across all
        target_profiles = (
            [self._profiles_cache[user_id]]
            if user_id and user_id in self._profiles_cache
            else list(self._profiles_cache.values())
        )

        best_match: FaceProfile | None = None
        best_score = 0.0

        for profile in target_profiles:
            sim = cosine_similarity(captured_features, profile.feature_vector)
            if sim > best_score:
                best_score = sim
                best_match = profile

        if best_match and best_score >= self.threshold:
            logger.info(
                f"Face identity verified: '{best_match.name}' (Confidence: {best_score:.2f} >= {self.threshold:.2f})"
            )
            return FaceVerificationResult(
                is_matched=True,
                user_id=best_match.user_id,
                user_name=best_match.name,
                confidence=round(best_score, 3),
            )

        logger.warning(f"Face verification failed. Best match confidence: {best_score:.2f} < {self.threshold:.2f}")
        return FaceVerificationResult(
            is_matched=False,
            confidence=round(best_score, 3),
            error_message=f"Identity not verified. Best match confidence ({best_score:.2f}) below threshold ({self.threshold:.2f}).",
        )
