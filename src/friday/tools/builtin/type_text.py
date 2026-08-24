# -*- coding: utf-8 -*-
"""Type Text tool: type a literal string into the currently focused window.

Uses pywinauto.keyboard with FULL literal escaping — every pywinauto special
character is wrapped so the string is typed exactly as given. No hotkeys,
special keys, or key sequences can be injected through this tool, which is
what makes plain text typing SAFE by construction.
"""

from typing import Any, Tuple

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
    if not needle:
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


def _auto_focus_top_window() -> Tuple[bool, str]:
    """Find the most recently opened top-level window (excluding the terminal) and focus it.

    Returns (focused: bool, window_title: str).
    """
    import time as _time

    from pywinauto import Desktop

    terminal_needles = {
        "powershell",
        "command prompt",
        "cmd.exe",
        "terminal",
        "windows terminal",
        "friday",
        "python",
    }
    try:
        windows = Desktop(backend="uia").windows()
        for w in windows:
            title = (w.window_text() or "").strip()
            if not title:
                continue
            title_lower = title.lower()
            if any(term in title_lower for term in terminal_needles):
                continue
            # Found candidate top-level application window
            try:
                w.set_focus()
                _time.sleep(0.5)
                logger.info(f"Auto-focused top-level window '{title}' for typing.")
                return True, title
            except Exception as fe:
                logger.warning(f"Failed to focus top-level window '{title}': {fe}")
                continue
    except Exception as e:
        logger.warning(f"Auto-focus scan failed: {e}")
    return False, ""


class TypeTextTool(BaseTool):
    """Type text into a window (optionally focusing it first), exactly as provided."""

    name = "type_text"
    description = (
        "Type a piece of text into an application window, character by character, exactly "
        "as provided (no hotkeys or special keys are possible). ALWAYS pass window_title "
        "when the text belongs in a specific application you just opened (e.g. "
        "window_title='Notepad') so the tool focuses that window before typing; if not provided, "
        "the tool will automatically focus the most recently opened application window."
    )
    safety_level = SafetyLevel.SAFE
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
                    "Substring of the target window's title (e.g. 'Notepad' matches "
                    "'Untitled - Notepad'). The window is focused before typing."
                ),
            },
        },
        "required": ["text"],
    }

    def execute(self, text: str = "", window_title: str = "", **kwargs: Any) -> ToolResult:
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

        focused = False
        target_name = ""
        if window_title and window_title.strip():
            focused = _focus_window(window_title)
            target_name = f"window '{window_title}'" if focused else "current focus"
        else:
            focused, auto_title = _auto_focus_top_window()
            target_name = f"window '{auto_title}'" if (focused and auto_title) else "current focus"

        try:
            send_keys(_escape_literal(payload), with_spaces=True, pause=0.005)
            logger.info(f"Typed {len(payload)} characters into {target_name}.")
            return ToolResult(
                name=self.name,
                content=(
                    f"Typed into {target_name}: {payload[:80]}{'...' if len(payload) > 80 else ''}"
                    + ("" if focused else " (note: target window not found; typed into current focus)")
                    if window_title
                    else f"Typed into {target_name}: {payload[:80]}{'...' if len(payload) > 80 else ''}"
                ),
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
