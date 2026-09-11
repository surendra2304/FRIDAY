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


def _focus_window(title_substring: str) -> bool:
    """Focus a top-level window whose title contains the given substring.

    Uses UI Automation to find the window (e.g. 'Notepad' matches
    'Untitled - Notepad'), brings it to the foreground via set_focus(), and
    waits 0.5s for the focus to settle before keystrokes are sent. Returns
    True when a window was focused; callers proceed regardless (best effort).
    """
    import time as _time

    from pywinauto import Desktop

    needle = (title_substring or "").strip().lower()
    if not needle or len(needle) < 2:
        logger.warning(f"Window title '{title_substring}' is too short or ambiguous to safely target.")
        return False
    try:
        windows = Desktop(backend="uia").windows()
        matches = [w for w in windows if needle in (w.window_text() or "").lower()]
        if not matches:
            logger.warning(f"No window found matching '{title_substring}' to focus.")
            return False
        matches[0].set_focus()
        _time.sleep(0.5)  # let the OS settle focus before typing
        logger.info(f"Focused window '{matches[0].window_text()}' for typing.")
        return True
    except Exception as e:
        logger.warning(f"Window focus for '{title_substring}' failed: {e}")
        return False


class TypeTextTool(BaseTool):
    """Type text into a specified application window after verifying target focus."""

    name = "type_text"
    description = (
        "Type a piece of text into a specific application window, character by character, "
        "exactly as provided. Requires an explicit window_title to ensure keystrokes are "
        "only dispatched to the intended application window."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The exact text to type.",
            },
            "window_title": {
                "type": "string",
                "description": (
                    "Required substring of the target window's title (e.g. 'Notepad' matches "
                    "'Untitled - Notepad'). Keystrokes will be aborted if the window cannot be focused."
                ),
            },
        },
        "required": ["text", "window_title"],
    }

    def execute(self, text: str = "", window_title: str = "", **kwargs: Any) -> ToolResult:
        payload = text or ""
        if not payload.strip():
            return ToolResult(
                name=self.name,
                content="No text provided to type.",
                is_error=True,
                safety_level=self.safety_level,
            )

        target = (window_title or "").strip()
        if not target or len(target) < 2:
            return ToolResult(
                name=self.name,
                content="Explicit window_title is required (at least 2 characters) for typing automation to ensure typing occurs only in the intended window.",
                is_error=True,
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

        focused = _focus_window(target)
        if not focused:
            return ToolResult(
                name=self.name,
                content=f"Target window matching '{target}' could not be found or focused. Keystrokes were aborted for security.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            send_keys(_escape_literal(payload), with_spaces=True, pause=0.005)
            logger.info(f"Typed {len(payload)} characters into window '{target}'.")
            return ToolResult(
                name=self.name,
                content=f"Successfully typed {len(payload)} characters into window '{target}'.",
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"type_text failed: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to type text into window '{target}': {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
