"""YouTube tool for searching videos and controlling video playback in the browser."""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.youtube")


class YouTubeTool(BaseTool):
    """Search and open YouTube videos or channels in the default web browser."""

    name = "youtube"
    description = (
        "Open YouTube or search for videos, music, tutorials, and channels on YouTube. "
        "Supports opening YouTube homepage or directly launching search results."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Video search query (e.g. 'lofi hip hop', 'Iron Man theme', 'python tutorial'). If omitted, opens YouTube home.",
            },
        },
        "required": [],
    }

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        q = (query or "").strip()
        if not q:
            url = "https://www.youtube.com"
            msg = "Opened YouTube in your browser."
        else:
            encoded_query = urllib.parse.quote_plus(q)
            url = f"https://www.youtube.com/results?search_query={encoded_query}"
            msg = f"Searching YouTube for '{q}' in your browser."

        try:
            webbrowser.open(url)
            logger.info(f"Navigating to YouTube URL: {url}")
            return ToolResult(
                name=self.name,
                content=msg,
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"Failed to open YouTube: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to open YouTube: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
