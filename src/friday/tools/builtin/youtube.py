"""YouTube tool for searching videos and controlling video playback in the browser."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.youtube")


class YouTubeTool(BaseTool):
    """Search and play YouTube videos or music in the default web browser."""

    name = "youtube"
    description = (
        "Open YouTube, search for videos/music, or directly play a requested song or video. "
        "When a song/music query is given, directly launches and plays the video."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Video or song search query (e.g. 'Starboy', 'lofi hip hop', 'python tutorial'). If omitted, opens YouTube home.",
            },
            "play": {
                "type": "boolean",
                "description": "If True, directly plays the first matching video instead of just showing search results.",
            },
        },
        "required": [],
    }

    def _get_first_video_url(self, query: str) -> str | None:
        """Extract the direct watch URL for the top search result."""
        try:
            encoded = urllib.parse.quote_plus(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded}"
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                matches = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html)
                if matches:
                    return f"https://www.youtube.com/watch?v={matches[0]}"
        except Exception as e:
            logger.warning(f"Could not resolve direct YouTube video for '{query}': {e}")
        return None

    def execute(self, query: str = "", play: bool = True, **kwargs: Any) -> ToolResult:
        q = (query or "").strip()
        if not q:
            url = "https://www.youtube.com"
            msg = "Opened YouTube in your browser."
        else:
            # Strip command prefixes
            clean_q = q
            for prefix in [
                "play the song", "play song", "play the", "play on youtube", "play",
            ]:
                if clean_q.lower().startswith(prefix):
                    clean_q = clean_q[len(prefix):].strip()
            if clean_q.lower().endswith("on youtube"):
                clean_q = clean_q[:-len("on youtube")].strip()
            if not clean_q:
                clean_q = q

            video_url = None
            if play:
                video_url = self._get_first_video_url(clean_q)

            if video_url:
                url = video_url
                msg = f"Playing '{clean_q}' on YouTube."
            else:
                encoded_query = urllib.parse.quote_plus(clean_q)
                url = f"https://www.youtube.com/results?search_query={encoded_query}"
                msg = f"Searching YouTube for '{clean_q}' in your browser."

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
