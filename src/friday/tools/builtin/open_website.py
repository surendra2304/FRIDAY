"""Open Website Tool for launching web pages and online services in the default browser."""

from __future__ import annotations

import webbrowser
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.open_website")

POPULAR_SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "amazon": "https://www.amazon.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "maps": "https://maps.google.com",
    "wikipedia": "https://www.wikipedia.org",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
}


class OpenWebsiteTool(BaseTool):
    """Open a website or web application in the user's default browser."""

    name = "open_website"
    description = (
        "Open any website or web service in the user's default web browser. "
        "Supports popular site names (e.g. 'youtube', 'google', 'github', 'amazon', 'spotify') "
        "or full URLs (e.g. 'https://example.com')."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Website name (e.g. 'youtube', 'github') or full URL (e.g. 'https://news.ycombinator.com').",
            },
        },
        "required": ["target"],
    }

    def execute(self, target: str, **kwargs: Any) -> ToolResult:
        tgt = (target or "").strip().lower()
        if not tgt:
            return ToolResult(
                name=self.name,
                content="Error: Target website or URL is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # Resolve URL
        if tgt in POPULAR_SITES:
            url = POPULAR_SITES[tgt]
        elif tgt.startswith(("http://", "https://")):
            url = target.strip()
        elif "." in tgt and " " not in tgt:
            url = f"https://{tgt}"
        else:
            # Check if any popular site is mentioned inside query ("open the youtube website")
            found = None
            for name, site_url in POPULAR_SITES.items():
                if name in tgt:
                    found = site_url
                    break
            if found:
                url = found
            else:
                # Default to a Google Search if not a recognized domain
                url = f"https://www.google.com/search?q={urllib_quote(target)}"

        try:
            webbrowser.open(url)
            logger.info(f"Opened website '{url}' in default browser.")
            return ToolResult(
                name=self.name,
                content=f"Opened {url} in your web browser.",
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"Failed to open website '{url}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to open {url}: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )


def urllib_quote(text: str) -> str:
    import urllib.parse
    return urllib.parse.quote_plus(text)
