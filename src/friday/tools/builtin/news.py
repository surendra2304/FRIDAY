"""News Tool for fetching real-time top headlines and category news via RSS."""

from __future__ import annotations

import re
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.news")

_FETCH_TIMEOUT = 12.0
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Topic mappings for Google News RSS
TOPIC_MAP = {
    "technology": "TECHNOLOGY",
    "tech": "TECHNOLOGY",
    "business": "BUSINESS",
    "science": "SCIENCE",
    "entertainment": "ENTERTAINMENT",
    "sports": "SPORTS",
    "health": "HEALTH",
    "world": "WORLD",
}


class NewsTool(BaseTool):
    """Fetch current top news headlines and topic summaries."""

    name = "get_news"
    description = (
        "Retrieve today's latest news headlines and summaries by category (e.g. 'technology', 'business', 'science', 'world', 'general'). "
        "Optionally opens the full article in the browser."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["general", "technology", "business", "science", "world", "sports", "entertainment", "health"],
                "description": "News topic category (default: 'general').",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of news stories to return (default: 5, max: 10).",
            },
            "open_in_browser": {
                "type": "boolean",
                "description": "Whether to open the first headline article directly in the user's web browser.",
            },
        },
        "required": [],
    }

    def execute(
        self,
        category: str = "general",
        limit: int = 5,
        open_in_browser: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        cat = (category or "general").lower().strip()
        topic_code = TOPIC_MAP.get(cat)

        if topic_code:
            url = f"https://news.google.com/rss/headlines/section/topic/{topic_code}?hl=en-US&gl=US&ceid=US:en"
        else:
            url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"

        articles: list[dict[str, str]] = []
        try:
            with httpx.Client(
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                xml_text = resp.text

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item"):
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    pub_elem = item.find("pubDate")
                    desc_elem = item.find("description")
                    source_elem = item.find("source")

                    title = title_elem.text if title_elem is not None and title_elem.text else "Untitled"
                    link = link_elem.text if link_elem is not None and link_elem.text else ""
                    pub = pub_elem.text if pub_elem is not None and pub_elem.text else ""
                    source = source_elem.text if source_elem is not None and source_elem.text else ""

                    # Clean title of trailing source if duplicate
                    if source and title.endswith(f" - {source}"):
                        title = title[: -len(f" - {source}")].strip()

                    articles.append({
                        "title": title,
                        "link": link,
                        "source": source or "News Source",
                        "pub_date": pub,
                    })
                    if len(articles) >= max(1, min(limit, 10)):
                        break

        except Exception as e:
            logger.warning(f"Failed to fetch news feed: {e}")
            return ToolResult(
                name=self.name,
                content=f"Could not retrieve news at this time: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not articles:
            return ToolResult(
                name=self.name,
                content=f"No recent news articles found for category '{cat}'.",
                is_error=False,
                safety_level=self.safety_level,
            )

        # Open in browser if requested
        if open_in_browser and articles[0].get("link"):
            try:
                webbrowser.open(articles[0]["link"])
            except Exception as e:
                logger.debug(f"Could not open browser: {e}")

        lines = [f"Top {len(articles)} {cat.title()} News Headlines:"]
        for i, a in enumerate(articles, 1):
            src_str = f" [{a['source']}]" if a.get("source") else ""
            lines.append(f"{i}. {a['title']}{src_str}")
            if a.get("link"):
                lines.append(f"   URL: {a['link']}")

        return ToolResult(
            name=self.name,
            content="\n".join(lines),
            is_error=False,
            safety_level=self.safety_level,
        )
