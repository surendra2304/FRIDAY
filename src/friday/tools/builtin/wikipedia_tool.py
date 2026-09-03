"""Wikipedia Tool for encyclopedic knowledge and biographical summaries."""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.wikipedia")

_TIMEOUT = 10.0
_USER_AGENT = "FRIDAY-Assistant/2.0 (Contact: surendra@example.com)"


class WikipediaTool(BaseTool):
    """Retrieve concise encyclopedic summaries and facts from Wikipedia."""

    name = "wikipedia_summary"
    description = (
        "Look up factual, historical, scientific, or biographical summaries on Wikipedia. "
        "Use for 'who is...', 'what is...', or encyclopedic knowledge queries."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The person, concept, invention, place, or topic to search on Wikipedia (e.g. 'Alan Turing', 'Quantum computing').",
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        q = (query or "").strip()
        if not q:
            return ToolResult(
                name=self.name,
                content="Error: Query is required for Wikipedia search.",
                is_error=True,
                safety_level=self.safety_level,
            )

        headers = {"User-Agent": _USER_AGENT}

        # Step 1: Try Opensearch to resolve the most accurate Wikipedia page title
        resolved_title = q
        try:
            search_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote_plus(q)}&limit=3&format=json"
            with httpx.Client(timeout=_TIMEOUT, headers=headers) as client:
                resp = client.get(search_url)
                if resp.status_code == 200:
                    data = resp.json()
                    if len(data) > 1 and data[1]:
                        resolved_title = data[1][0]
        except Exception as e:
            logger.debug(f"Wikipedia opensearch lookup failed: {e}")

        # Step 2: Fetch REST summary for the resolved title
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(resolved_title.replace(' ', '_'))}"
        try:
            with httpx.Client(timeout=_TIMEOUT, headers=headers, follow_redirects=True) as client:
                resp = client.get(summary_url)
                if resp.status_code == 200:
                    data = resp.json()
                    title = data.get("title", resolved_title)
                    extract = data.get("extract", "")
                    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

                    if extract:
                        content = f"Wikipedia: {title}\n\n{extract}"
                        if page_url:
                            content += f"\n\nSource: {page_url}"
                        return ToolResult(
                            name=self.name,
                            content=content,
                            is_error=False,
                            safety_level=self.safety_level,
                        )

            return ToolResult(
                name=self.name,
                content=f"No Wikipedia article found matching '{q}'.",
                is_error=True,
                safety_level=self.safety_level,
            )

        except Exception as e:
            logger.error(f"Wikipedia query failed for '{q}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Error querying Wikipedia: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
