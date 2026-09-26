"""YouTube tool for opening the site or search results without selecting or playing media."""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.youtube")


class YouTubeTool(BaseTool):
    """Open YouTube or YouTube search results without claiming playback."""

    name = "youtube"
    description = (
        "Use only when the user explicitly requests YouTube. Open YouTube or search for a video/music query. "
        "This tool does not select a result, start playback, or verify that playback started. "
        "For another named service, use that service instead; never substitute YouTube."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Literal video or song search terms. If omitted, opens YouTube home.",
            },
        },
        "required": [],
    }

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        q = (query or "").strip()
        if not q:
            url = "https://www.youtube.com"
            msg = "Opened YouTube home. No video was selected or played."
        else:
            encoded_query = urllib.parse.quote_plus(q)
            url = f"https://www.youtube.com/results?search_query={encoded_query}"
            msg = f"Opened YouTube search results for '{q}'. No video was selected or played."

        try:
            opened = webbrowser.open(url)
            if not opened:
                return ToolResult(
                    name=self.name,
                    content="Could not open YouTube page: the system browser did not confirm launch.",
                    is_error=True,
                    safety_level=self.safety_level,
                    metadata={"url": url, "opened": False, "playback_started": False},
                )
            logger.info(f"Navigating to YouTube URL: {url}")
            return ToolResult(
                name=self.name,
                content=msg,
                is_error=False,
                safety_level=self.safety_level,
                metadata={"url": url, "opened": True, "playback_started": False},
            )
        except Exception as e:
            logger.error(f"Failed to open YouTube: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to open YouTube: {e}",
                is_error=True,
                safety_level=self.safety_level,
                metadata={"url": url, "opened": False, "playback_started": False},
            )
