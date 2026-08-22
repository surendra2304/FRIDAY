# -*- coding: utf-8 -*-
"""Type Text tool: type a literal string into the currently focused window.

Uses pywinauto.keyboard with FULL literal escaping — every pywinauto special
character is wrapped so the string is typed exactly as given. No hotkeys,
special keys, or key sequences can be injected through this tool, which is
what makes plain text typing SAFE by construction.
"""

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.type_text")

# pywinauto keyboard modifier/special characters that must be escaped to type literally
_SPECIAL_CHARS = set("+^%~(){}[]")


def _escape_literal(text: str) -> str:
    """Escape a string so pywinauto.keyboard types every character literally."""
    out = []
    for ch in text:
        if ch in _SPECIAL_CHARS:
            out.append(f"{{{ch}}}")
        else:
            out.append(ch)
    return "".join(out)


def _get_send_keys():
    """Lazily import pywinauto.keyboard (Windows-only, optional dependency)."""
    from pywinauto.keyboard import send_keys

    return send_keys


class TypeTextTool(BaseTool):
    """Type the given text into the currently focused window, exactly as provided."""

    name = "type_text"
    description = (
        "Type a piece of text into the currently focused window/application, character "
        "by character, exactly as provided (no hotkeys or special keys are possible). "
        "Use after opening an application when the user asks you to write or enter text."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The exact text to type into the focused window.",
            }
        },
        "required": ["text"],
    }

    def execute(self, text: str = "", **kwargs: Any) -> ToolResult:
        payload = text or ""
        if not payload.strip():
            return ToolResult(
                name=self.name, content="No text provided to type.", is_error=True,
                safety_level=self.safety_level,
            )
        try:
            send_keys = _get_send_keys()
        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Keyboard automation unavailable: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            send_keys(_escape_literal(payload), with_spaces=True, pause=0.005)
            logger.info(f"Typed {len(payload)} characters into the focused window.")
            return ToolResult(
                name=self.name,
                content=f"Typed: {payload[:80]}{'...' if len(payload) > 80 else ''}",
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"type_text failed: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to type text: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
