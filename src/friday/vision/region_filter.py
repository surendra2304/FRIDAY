# -*- coding: utf-8 -*-
"""Local Text, Region-of-Interest (ROI) Slicing & Perceptual Pre-Filtering for Phase 8.4 (Quota Saver).

Provides offline, lightweight, deterministic image region slicing, perceptual ROI hashing,
text-density heuristic estimation, and feeding verified visual deltas into ActiveTaskContext.

Core Capabilities:
1. Region of Interest (ROI) Slicing & Cropping:
   Extracts rectangular sub-regions from raw PNG image bytes based on normalized BoundingBox or pixel coordinates.
2. Perceptual ROI Hashing & Change Evaluation:
   Tracks per-region hashes (e.g. active window, terminal, status bar) to identify localized visual changes
   without requiring full-screen cloud vision re-analysis.
3. Local Text-Density & Visual Complexity Estimation:
   Lightweight heuristic estimator analyzing byte variance, high-frequency transitions (edge/text proxy),
   and entropy to categorize screen regions into text-density levels (LOW, MEDIUM, HIGH, CODE_DENSE).
4. Visual Delta Task Context Feeder:
   Binds structured temporal environmental deltas and ROI changes directly into ActiveTaskContext
   as verified factual TaskObservations with secret redaction and zero raw screenshot persistence.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import io
import math
import struct
from typing import Any, Dict, List, Optional, Tuple, Union
import zlib

import numpy as np

from friday.core.logging import get_logger
from friday.memory.task_context import ActiveTaskContext
from friday.vision.change_detector import compute_image_difference_ratio
from friday.vision.temporal import EnvironmentalChange, EnvironmentalChangeType
from friday.vision.ui_elements import BoundingBox
from friday.vision.vision_memory import redact_sensitive_visual_text

logger = get_logger("vision.region_filter")


class TextDensityLevel(str, Enum):
    """Categorized local text density / visual complexity."""
    EMPTY_OR_SOLID = "EMPTY_OR_SOLID"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CODE_OR_DENSE_TEXT = "CODE_OR_DENSE_TEXT"


@dataclass
class ROIAnalysisResult:
    """Structured result of a localized region analysis."""
    roi_id: str
    bounding_box: BoundingBox
    pixel_rect: Tuple[int, int, int, int]  # (xmin, ymin, xmax, ymax)
    image_bytes: bytes
    image_sha256: str
    text_density: TextDensityLevel
    estimated_complexity: float  # 0.0 to 1.0
    has_changed: bool = False
    change_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "roi_id": self.roi_id,
            "bounding_box": self.bounding_box.to_dict(),
            "pixel_rect": list(self.pixel_rect),
            "image_sha256": self.image_sha256,
            "text_density": self.text_density.value,
            "estimated_complexity": round(self.estimated_complexity, 4),
            "has_changed": self.has_changed,
            "change_ratio": round(self.change_ratio, 4),
            "payload_bytes": len(self.image_bytes),
        }


def decode_png_to_rgba(png_bytes: bytes) -> Tuple[np.ndarray, int, int]:
    """Decode raw PNG image bytes to an RGBA numpy array without PIL or external heavy dependencies.
    
    Supports standard 8-bit RGBA (type 6) and RGB (type 2) uncompressed/compressed streams.
    Falls back to a synthetic array if stream format is non-standard.
    """
    if not png_bytes or len(png_bytes) < 8 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG header")

    offset = 8
    width = 0
    height = 0
    bit_depth = 8
    color_type = 6
    idat_chunks = []

    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_data = png_bytes[offset + 8 : offset + 8 + length]
        offset += 12 + length

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not idat_chunks or width == 0 or height == 0:
        raise ValueError("Malformed PNG data: missing IHDR or IDAT")

    decompressed = zlib.decompress(b"".join(idat_chunks))

    # Calculate scanline stride based on color type
    bpp = 4 if color_type == 6 else (3 if color_type == 2 else 1)
    stride = width * bpp
    raw_data = bytearray(height * stride)

    # De-filter scanlines (supporting Filter 0: None and basic row reconstruction)
    src_pos = 0
    dst_pos = 0
    prev_row = bytearray(stride)

    for _ in range(height):
        filter_type = decompressed[src_pos]
        src_pos += 1
        curr_row = decompressed[src_pos : src_pos + stride]
        src_pos += stride

        if filter_type == 0:  # None
            filtered_row = bytearray(curr_row)
        elif filter_type == 1:  # Sub
            filtered_row = bytearray(curr_row)
            for x in range(bpp, stride):
                filtered_row[x] = (filtered_row[x] + filtered_row[x - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            filtered_row = bytearray(curr_row)
            for x in range(stride):
                filtered_row[x] = (filtered_row[x] + prev_row[x]) & 0xFF
        elif filter_type == 3:  # Average
            filtered_row = bytearray(curr_row)
            for x in range(stride):
                left = filtered_row[x - bpp] if x >= bpp else 0
                up = prev_row[x]
                filtered_row[x] = (filtered_row[x] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:  # Paeth
            filtered_row = bytearray(curr_row)
            for x in range(stride):
                a = filtered_row[x - bpp] if x >= bpp else 0
                b = prev_row[x]
                c = prev_row[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                filtered_row[x] = (filtered_row[x] + pr) & 0xFF
        else:
            filtered_row = bytearray(curr_row)

        raw_data[dst_pos : dst_pos + stride] = filtered_row
        prev_row = filtered_row
        dst_pos += stride

    img_arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, bpp))
    if bpp == 3:
        # Convert RGB to RGBA
        alpha = np.full((height, width, 1), 255, dtype=np.uint8)
        img_arr = np.concatenate([img_arr, alpha], axis=2)
    elif bpp == 1:
        # Grayscale to RGBA
        img_arr = np.repeat(img_arr, 3, axis=2)
        alpha = np.full((height, width, 1), 255, dtype=np.uint8)
        img_arr = np.concatenate([img_arr, alpha], axis=2)

    return img_arr, width, height


def encode_rgba_to_png(img_arr: np.ndarray) -> bytes:
    """Encode an RGBA numpy array to valid PNG bytes in memory."""
    height, width, channels = img_arr.shape
    if channels != 4:
        raise ValueError("Image array must have 4 channels (RGBA)")

    raw_rows = []
    for y in range(height):
        row = bytearray([0])  # Filter 0 (None)
        row.extend(img_arr[y, :, :].tobytes())
        raw_rows.append(bytes(row))

    compressed = zlib.compress(b"".join(raw_rows), level=1)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png.extend(struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF))
    png.extend(struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF))
    png.extend(struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF))
    return bytes(png)


def crop_image_region(
    png_bytes: bytes,
    bounding_box: BoundingBox,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
) -> Tuple[bytes, Tuple[int, int, int, int]]:
    """Crop a sub-region from PNG bytes using normalized coordinates (0-1000).
    
    Returns:
        Tuple of (cropped_png_bytes, (xmin, ymin, xmax, ymax) pixel bounds).
    """
    img_arr, w, h = decode_png_to_rgba(png_bytes)
    target_w = image_width or w
    target_h = image_height or h

    xmin, ymin, xmax, ymax = bounding_box.to_pixel_coordinates(target_w, target_h)

    # Clamp coordinates
    xmin = max(0, min(xmin, w - 1))
    ymin = max(0, min(ymin, h - 1))
    xmax = max(xmin + 1, min(xmax, w))
    ymax = max(ymin + 1, min(ymax, h))

    cropped_arr = img_arr[ymin:ymax, xmin:xmax, :]
    cropped_png = encode_rgba_to_png(cropped_arr)
    return cropped_png, (xmin, ymin, xmax, ymax)


def estimate_local_text_density(img_arr: np.ndarray) -> Tuple[TextDensityLevel, float]:
    """Estimate local text density and visual complexity using spatial gradient & variance heuristics.
    
    Returns:
        Tuple of (TextDensityLevel, complexity_score: float 0.0 - 1.0).
    """
    if img_arr.size == 0:
        return TextDensityLevel.EMPTY_OR_SOLID, 0.0

    # Convert RGBA to grayscale luminance
    gray = (
        0.299 * img_arr[:, :, 0].astype(float)
        + 0.587 * img_arr[:, :, 1].astype(float)
        + 0.114 * img_arr[:, :, 2].astype(float)
    )

    std_dev = float(np.std(gray))
    if std_dev < 1.0:
        return TextDensityLevel.EMPTY_OR_SOLID, 0.0

    # High frequency horizontal transitions (typical text lines have frequent edge crossings)
    diff_x = np.abs(np.diff(gray, axis=1))
    edge_transitions = np.count_nonzero(diff_x > 25)
    total_pixels = gray.size

    edge_density = float(edge_transitions / max(1, total_pixels))

    # Normalized complexity heuristic combining variance and edge density
    complexity = min(1.0, (std_dev / 80.0) * 0.4 + (edge_density / 0.25) * 0.6)

    if complexity < 0.05:
        density = TextDensityLevel.EMPTY_OR_SOLID
    elif complexity < 0.20:
        density = TextDensityLevel.LOW
    elif complexity < 0.45:
        density = TextDensityLevel.MEDIUM
    elif complexity < 0.70:
        density = TextDensityLevel.HIGH
    else:
        density = TextDensityLevel.CODE_OR_DENSE_TEXT

    return density, complexity


class LocalRegionPreFilter:
    """Perceptual ROI pre-filtering engine for quota saving in Phase 8.4."""

    def __init__(self, change_threshold: float = 0.05) -> None:
        self.change_threshold = change_threshold
        self._roi_hashes: Dict[str, str] = {}
        self._roi_last_bytes: Dict[str, bytes] = {}

    def slice_and_evaluate_roi(
        self,
        png_bytes: bytes,
        bounding_box: BoundingBox,
        roi_id: str,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
    ) -> ROIAnalysisResult:
        """Slice an ROI, evaluate its perceptual difference against prior state, and estimate text density."""
        cropped_bytes, pixel_rect = crop_image_region(
            png_bytes=png_bytes,
            bounding_box=bounding_box,
            image_width=image_width,
            image_height=image_height,
        )

        cropped_arr, _, _ = decode_png_to_rgba(cropped_bytes)
        density_level, complexity = estimate_local_text_density(cropped_arr)

        roi_sha = hashlib.sha256(cropped_bytes).hexdigest()
        prev_sha = self._roi_hashes.get(roi_id)
        prev_bytes = self._roi_last_bytes.get(roi_id)

        has_changed = True
        diff_ratio = 1.0

        if prev_sha == roi_sha:
            has_changed = False
            diff_ratio = 0.0
        elif prev_bytes is not None:
            diff_ratio = compute_image_difference_ratio(prev_bytes, cropped_bytes)
            has_changed = diff_ratio >= self.change_threshold
        else:
            has_changed = True
            diff_ratio = 1.0

        # Update cache
        self._roi_hashes[roi_id] = roi_sha
        self._roi_last_bytes[roi_id] = cropped_bytes

        return ROIAnalysisResult(
            roi_id=roi_id,
            bounding_box=bounding_box,
            pixel_rect=pixel_rect,
            image_bytes=cropped_bytes,
            image_sha256=roi_sha,
            text_density=density_level,
            estimated_complexity=complexity,
            has_changed=has_changed,
            change_ratio=diff_ratio,
        )

    def evaluate_multiple_rois(
        self,
        png_bytes: bytes,
        rois: Dict[str, BoundingBox],
    ) -> Dict[str, ROIAnalysisResult]:
        """Evaluate a dictionary of labelled ROIs across the screen."""
        results = {}
        for roi_id, bbox in rois.items():
            results[roi_id] = self.slice_and_evaluate_roi(png_bytes, bbox, roi_id)
        return results

    def reset(self) -> None:
        """Clear historical ROI cache state."""
        self._roi_hashes.clear()
        self._roi_last_bytes.clear()


class VisualDeltaTaskContextFeeder:
    """Feeds verified temporal and visual deltas directly into ActiveTaskContext."""

    @staticmethod
    def feed_environmental_delta(
        task_context: ActiveTaskContext,
        step_id: str,
        changes: List[EnvironmentalChange],
        source_tool: str = "visual_perception",
    ) -> int:
        """Record verified environmental state changes as TaskObservations in ActiveTaskContext.
        
        Returns:
            Number of meaningful observations recorded.
        """
        if not task_context or not changes:
            return 0

        recorded_count = 0
        for chg in changes:
            if not chg.is_meaningful:
                continue

            clean_desc = redact_sensitive_visual_text(chg.description)
            obs_content = f"[Visual Delta: {chg.change_type.value}] {clean_desc} (confidence: {chg.confidence:.2f})"
            task_context.add_observation(
                step_id=step_id,
                content=obs_content,
                source_tool=source_tool,
            )
            recorded_count += 1

        return recorded_count

    @staticmethod
    def feed_roi_delta(
        task_context: ActiveTaskContext,
        step_id: str,
        roi_result: ROIAnalysisResult,
        source_tool: str = "roi_filter",
    ) -> bool:
        """Record a verified ROI change as a TaskObservation in ActiveTaskContext."""
        if not task_context or not roi_result.has_changed:
            return False

        obs_content = (
            f"[ROI Changed: {roi_result.roi_id}] text_density={roi_result.text_density.value}, "
            f"complexity={roi_result.estimated_complexity:.2f}, diff_ratio={roi_result.change_ratio:.2f}"
        )
        task_context.add_observation(
            step_id=step_id,
            content=obs_content,
            source_tool=source_tool,
        )
        return True
