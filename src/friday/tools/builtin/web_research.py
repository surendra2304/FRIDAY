# -*- coding: utf-8 -*-
"""Web Browsing & Autonomous Research Tools.

Provides tools for fetching full webpage content with HTML clean-up via BeautifulSoup4,
and synthesizing large blocks of text into concise, structured answers using LLM inference
with prompt injection sanitization.
"""

from typing import Any, Dict, Optional
import httpx

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, ToolResult
from friday.security.prompt_injection import InjectionRisk, SourceType, guard_content
from friday.tools.base import BaseTool

logger = get_logger("tools.web_research")

_FETCH_TIMEOUT = 15.0
_MAX_PAGE_CHARS = 12000


class FetchWebpageContentTool(BaseTool):
    """Fetch HTML from a URL and extract clean, readable text stripping scripts, styles, and navbars."""

    name = "fetch_webpage_content"
    description = (
        "Fetch a web page and return its clean text content (HTML tags, scripts, "
        "styles, ads, headers, and navigation bars stripped) for reading and research."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch (must include http:// or https://).",
            },
        },
        "required": ["url"],
    }

    def execute(self, url: str = "", **kwargs: Any) -> ToolResult:
        target = (url or "").strip()
        if not target.startswith(("http://", "https://")):
            return ToolResult(
                name=self.name,
                content="Error: URL must start with http:// or https://.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            with httpx.Client(
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "FRIDAY_Assistant/1.0 (contact: surendra@example.com)"},
            ) as client:
                response = client.get(target)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch webpage '{target}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to fetch webpage '{target}': {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            # Strip non-content elements
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "svg", "form"]):
                tag.decompose()

            raw_text = soup.get_text(separator="\n")
            # Clean extra blank lines and spaces
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            cleaned_text = "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to parse HTML from '{target}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to parse HTML from '{target}': {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not cleaned_text:
            return ToolResult(
                name=self.name,
                content=f"Webpage returned no readable text: {target}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # Sanitize via prompt injection guard
        guard_res = guard_content(SourceType.WEB, cleaned_text)
        if guard_res.risk == InjectionRisk.BLOCKED:
            logger.warning(f"Web content from '{target}' was blocked by prompt injection guard.")
            return ToolResult(
                name=self.name,
                content="[WEBPAGE CONTENT BLOCKED BY SECURITY GUARD: POTENTIAL INJECTION DETECTED]",
                is_error=True,
                safety_level=self.safety_level,
            )

        safe_text = guard_res.sanitized
        truncated = safe_text[:_MAX_PAGE_CHARS] + ("\n... [content truncated for length]" if len(safe_text) > _MAX_PAGE_CHARS else "")

        return ToolResult(
            name=self.name,
            content=truncated,
            is_error=False,
            safety_level=self.safety_level,
            metadata={"url": target, "length": len(truncated)},
        )


class SynthesizeInformationTool(BaseTool):
    """Synthesize large blocks of fetched web text into a structured 3-bullet-point answer."""

    name = "synthesize_information"
    description = (
        "Synthesize a large block of text against a research query into a concise, accurate 3-bullet-point summary."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The raw or extracted text content to synthesize.",
            },
            "query": {
                "type": "string",
                "description": "The user's original research question or topic.",
            },
        },
        "required": ["text", "query"],
    }

    def execute(self, text: str = "", query: str = "", **kwargs: Any) -> ToolResult:
        clean_text = (text or "").strip()
        clean_query = (query or "").strip()

        if not clean_text:
            return ToolResult(
                name=self.name,
                content="Error: No text content provided for synthesis.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # Sanitize input text with prompt injection guard
        guard_res = guard_content(SourceType.WEB, clean_text)
        if guard_res.risk == InjectionRisk.BLOCKED:
            return ToolResult(
                name=self.name,
                content="Error: Input text contains unsafe prompt injection patterns.",
                is_error=True,
                safety_level=self.safety_level,
            )

        safe_text = guard_res.sanitized[:8000]

        prompt = (
            "You are FRIDAY's Research Synthesis Engine.\n"
            "Analyze the provided text in the context of the user's research query.\n"
            "Synthesize the key findings into exactly 3 clear, informative, and factual bullet points.\n\n"
            f"User Research Query: {clean_query or 'General Summary'}\n\n"
            f"Content:\n{safe_text}\n\n"
            "Output formatting requirements:\n"
            "• Bullet 1\n"
            "• Bullet 2\n"
            "• Bullet 3"
        )

        messages = [
            Message(role=Role.SYSTEM, content="You are a precise research synthesis assistant. Respond in 3 bullet points."),
            Message(role=Role.USER, content=prompt),
        ]

        try:
            settings = get_settings()
            from friday.llm.factory import create_llm_provider
            provider = create_llm_provider(settings)
            resp = provider.generate(messages=messages)
            summary = (resp.content or "").strip()
            
            return ToolResult(
                name=self.name,
                content=summary,
                is_error=False,
                safety_level=self.safety_level,
                metadata={"query": clean_query, "provider": getattr(provider, "provider_name", "llm")},
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return ToolResult(
                name=self.name,
                content=f"Synthesis failed: {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )
