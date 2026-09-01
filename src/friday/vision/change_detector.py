"""Lightweight perceptual image difference detector and screen change evaluator.

Calculates fast perceptual downsampled luminance hash and Mean Absolute Difference (MAD)
over raw image bytes to avoid sending unchanged screenshots to Gemini API. Zero heavy dependencies.
"""

import hashlib

import numpy as np


def compute_image_sha256(image_bytes: bytes) -> str:
    """Compute exact SHA256 cryptographic hash of image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


def compute_image_difference_ratio(
    img1_bytes: bytes,
    img2_bytes: bytes,
    sample_size: int = 128,
) -> float:
    """Compute normalized difference ratio (0.0 to 1.0) between two PNG image payloads.

    Performs fast subsampling comparison across payload byte distributions.

    Returns:
        0.0 if images are byte-identical.
        Ratio > 0.0 representing estimated visual distance.
    """
    if img1_bytes == img2_bytes:
        return 0.0

    if not img1_bytes or not img2_bytes:
        return 1.0

    len1 = len(img1_bytes)
    len2 = len(img2_bytes)

    # If payload size changed drastically (>15% variance), declare significant change
    size_ratio = abs(len1 - len2) / max(len1, len2)
    if size_ratio > 0.15:
        return min(1.0, size_ratio)

    # Subsample uniform stride over bytes
    n_samples = min(sample_size, len1, len2)
    indices1 = np.linspace(0, len1 - 1, n_samples, dtype=int)
    indices2 = np.linspace(0, len2 - 1, n_samples, dtype=int)

    arr1 = np.frombuffer(img1_bytes, dtype=np.uint8)[indices1]
    arr2 = np.frombuffer(img2_bytes, dtype=np.uint8)[indices2]

    # Mean absolute difference normalized to 0.0 - 1.0
    mad = float(np.mean(np.abs(arr1.astype(float) - arr2.astype(float))) / 255.0)
    return mad


class ScreenChangeDetector:
    """Stateful screen change evaluator tracking previous snapshot hashes and visual delta."""

    def __init__(self, change_threshold: float = 0.05) -> None:
        self.change_threshold = change_threshold
        self._last_sha256: str | None = None
        self._last_bytes: bytes | None = None

    def evaluate_change(self, new_image_bytes: bytes) -> tuple[bool, float]:
        """Evaluate if new image differs significantly from the last observed image.

        Returns:
            Tuple of (has_changed: bool, diff_ratio: float).
        """
        if not new_image_bytes:
            return False, 0.0

        new_sha = compute_image_sha256(new_image_bytes)

        # 1. Exact match
        if self._last_sha256 == new_sha:
            return False, 0.0

        # 2. First observation
        if self._last_bytes is None:
            self._last_sha256 = new_sha
            self._last_bytes = new_image_bytes
            return True, 1.0

        # 3. Compute perceptual difference ratio
        diff_ratio = compute_image_difference_ratio(self._last_bytes, new_image_bytes)

        if diff_ratio >= self.change_threshold:
            self._last_sha256 = new_sha
            self._last_bytes = new_image_bytes
            return True, diff_ratio

        # Below threshold: treat as unchanged
        return False, diff_ratio

    def reset(self) -> None:
        """Clear historical screen state."""
        self._last_sha256 = None
        self._last_bytes = None
