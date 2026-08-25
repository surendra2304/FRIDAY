# -*- coding: utf-8 -*-
"""Web research tools: DuckDuckGo search and clean webpage text extraction.

Fetched web content is UNTRUSTED external data. The voice pipeline's
injection guard and the text chain's TOOL-message sanitization both
scrub these results before they reach any model context.
"""

from typing import Any
import warnings

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.web")

_MAX_RESULTS = 5
_MAX_PAGE_CHARS = 6000
_FETCH_TIMEOUT = 15.0


class WebSearchTool(BaseTool):
    """Search the web via DuckDuckGo and return instant results/summaries."""

    name = "web_search"
    description = (
        "Search the web for current information. Returns the top results with "
        "titles, URLs, and snippet summaries. Use for facts, news, or anything "
        "outside your training data."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
        },
        "required": ["query"],
    }

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        q = (query or "").strip()
        if not q:
            return ToolResult(name=self.name, content="No search query provided.", is_error=True,
                              safety_level=self.safety_level)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*duckduckgo_search.*renamed to `ddgs`.*",
                    category=RuntimeWarning,
                )
                from duckduckgo_search import DDGS
        except Exception as e:
            return ToolResult(name=self.name, content=f"Search library unavailable: {e}",
                              is_error=True, safety_level=self.safety_level)

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*duckduckgo_search.*renamed to `ddgs`.*",
                    category=RuntimeWarning,
                )
                with DDGS() as ddgs:
                    results = list(ddgs.text(q, max_results=_MAX_RESULTS))
        except Exception as e:
            return ToolResult(name=self.name, content=f"Web search failed: {e}",
                              is_error=True, safety_level=self.safety_level)

        if not results:
            return ToolResult(name=self.name, content=f"No results found for '{q}'.",
                              is_error=False, safety_level=self.safety_level)

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("href", r.get("url", ""))
            body = (r.get("body") or r.get("snippet") or "").strip()
            lines.append(f"{i}. {title}\n   {url}\n   {body[:300]}")
        return ToolResult(name=self.name, content="\n".join(lines), is_error=False,
                          safety_level=self.safety_level)


class FetchWebpageTool(BaseTool):
    """Fetch a URL and extract clean readable text (tags/scripts stripped)."""

    name = "fetch_webpage"
    description = (
        "Fetch a web page and return its clean text content (HTML tags, scripts, "
        "and styles stripped) so it can be read and summarized. Use after a web "
        "search to open a promising result."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full URL to fetch (include https://)."},
        },
        "required": ["url"],
    }

    def execute(self, url: str = "", **kwargs: Any) -> ToolResult:
        target = (url or "").strip()
        if not target.startswith(("http://", "https://")):
            return ToolResult(name=self.name, content="URL must start with http:// or https://.",
                              is_error=True, safety_level=self.safety_level)
        try:
            with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": "FRIDAY_Assistant/1.0 (contact: surendra@example.com)"}) as client:
                response = client.get(target)
            response.raise_for_status()
        except Exception as e:
            return ToolResult(name=self.name, content=f"Failed to fetch {target}: {e}",
                              is_error=True, safety_level=self.safety_level)

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            text = " ".join(soup.get_text(separator=" ").split())
        except Exception as e:
            return ToolResult(name=self.name, content=f"Failed to parse page: {e}",
                              is_error=True, safety_level=self.safety_level)

        if not text:
            return ToolResult(name=self.name, content=f"Page returned no readable text: {target}",
                              is_error=True, safety_level=self.safety_level)

        truncated = text[:_MAX_PAGE_CHARS] + ("... [truncated]" if len(text) > _MAX_PAGE_CHARS else "")
        return ToolResult(name=self.name, content=truncated, is_error=False,
                          safety_level=self.safety_level)
