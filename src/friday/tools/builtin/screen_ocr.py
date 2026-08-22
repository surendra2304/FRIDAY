# -*- coding: utf-8 -*-
"""Local screen OCR tools: read text directly from the screen without a cloud call.

Uses pytesseract (Tesseract OCR engine) over a local screen capture, so
reading UI text is fast and free. When the Tesseract binary is not installed
the tools degrade gracefully with an install hint. Requires the Tesseract
engine: https://github.com/UB-Mannheim/tesseract/wiki
"""

from typing import Any, List, Optional, Tuple

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.screen_ocr")


def _capture_screen(region: Optional[Tuple[int, int, int, int]] = None):
    """Capture the screen (or a region) as a PIL image via mss-style Win32 capture."""
    from PIL import ImageGrab

    if region:
        return ImageGrab.grab(bbox=tuple(region))
    return ImageGrab.grab()


def _run_ocr(image) -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """Run Tesseract OCR; return [(text, bounding_box)] for words/confident chunks."""
    import pytesseract

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    results: List[Tuple[str, Tuple[int, int, int, int]]] = []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if word and conf > 40:
            box = (data["left"][i], data["top"][i],
                   data["left"][i] + data["width"][i], data["top"][i] + data["height"][i])
            results.append((word, box))
    return results


def _ocr_unavailable_result(tool_name: str, exc: Exception) -> ToolResult:
    return ToolResult(
        name=tool_name,
        content=(
            f"Local OCR unavailable: {type(exc).__name__}. Install the Tesseract engine "
            "(https://github.com/UB-Mannheim/tesseract/wiki) and ensure it is on PATH."
        ),
        is_error=True,
        safety_level=SafetyLevel.SAFE,
    )


class ReadScreenTextTool(BaseTool):
    """Read visible text on the screen (optionally a region) via local OCR."""

    name = "read_screen_text"
    description = (
        "Read the text currently visible on the screen using fast local OCR — no cloud "
        "vision call. Optionally pass region as [left, top, right, bottom] pixel bounds "
        "to read only part of the screen."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [left, top, right, bottom] pixel bounds.",
            }
        },
        "required": [],
    }

    def execute(self, region=None, **kwargs: Any) -> ToolResult:
        try:
            image = _capture_screen(region)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Screen capture failed: {e}",
                              is_error=True, safety_level=self.safety_level)
        try:
            words = _run_ocr(image)
        except Exception as e:
            return _ocr_unavailable_result(self.name, e)

        if not words:
            return ToolResult(name=self.name, content="No readable text found on screen.",
                              is_error=False, safety_level=self.safety_level)
        # Reconstruct lines by grouping words on the same top coordinate
        lines: List[Tuple[int, List[str]]] = []
        for word, (l, t, r, b) in words:
            if lines and abs(lines[-1][0] - t) <= 6:
                lines[-1][1].append(word)
            else:
                lines.append((t, [word]))
        text = "\n".join(" ".join(ws) for _, ws in lines)
        trimmed = text[:8000] + ("... [truncated]" if len(text) > 8000 else "")
        return ToolResult(name=self.name, content=trimmed, is_error=False,
                          safety_level=self.safety_level)


class FindOnScreenTool(BaseTool):
    """Locate specific text on screen and return its pixel coordinates."""

    name = "find_on_screen"
    description = (
        "Find where a specific piece of text appears on the screen and return its pixel "
        "coordinates (center of the match). Combines local OCR with screen search — use "
        "before clicking precise UI elements."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to locate on screen."},
        },
        "required": ["text"],
    }

    def execute(self, text: str = "", **kwargs: Any) -> ToolResult:
        needle = (text or "").strip()
        if not needle:
            return ToolResult(name=self.name, content="No text provided.", is_error=True,
                              safety_level=self.safety_level)
        try:
            image = _capture_screen()
        except Exception as e:
            return ToolResult(name=self.name, content=f"Screen capture failed: {e}",
                              is_error=True, safety_level=self.safety_level)
        try:
            words = _run_ocr(image)
        except Exception as e:
            return _ocr_unavailable_result(self.name, e)

        needle_lower = needle.lower()
        # Single-word match
        for word, (l, t, r, b) in words:
            if word.lower() == needle_lower:
                cx, cy = (l + r) // 2, (t + b) // 2
                return ToolResult(
                    name=self.name,
                    content=f"Found '{word}' at center ({cx}, {cy}) "
                            f"[bbox: left={l}, top={t}, right={r}, bottom={b}].",
                    is_error=False, safety_level=self.safety_level,
                )
        # Substring / phrase match across consecutive words
        joined = " ".join(w for w, _ in words).lower()
        if needle_lower in joined:
            for i in range(len(words)):
                window = " ".join(w for w, _ in words[i:i + 12]).lower()
                if needle_lower in window:
                    l, t, r, b = words[i][1]
                    l2, t2, r2, b2 = words[min(i + 11, len(words) - 1)][1]
                    cx, cy = (l + max(r, r2)) // 2, (t + max(b, b2)) // 2
                    return ToolResult(
                        name=self.name,
                        content=f"Found phrase near ({cx}, {cy}) "
                                f"[bbox: left={l}, top={t}, right={max(r, r2)}, bottom={max(b, b2)}].",
                        is_error=False, safety_level=self.safety_level,
                    )
        return ToolResult(name=self.name, content=f"'{needle}' not found on screen.",
                          is_error=False, safety_level=self.safety_level)
