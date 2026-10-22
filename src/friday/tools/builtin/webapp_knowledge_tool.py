"""Web Application Knowledge & Navigation Guide Tool for FRIDAY.

Allows the agent to retrieve exact operational rules, selectors, shortcuts,
and interaction guidelines for popular web applications.
"""

from __future__ import annotations

from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.integrations.webapp_templates.registry import webapp_templates
from friday.tools.base import BaseTool


class LookupWebAppTemplateTool(BaseTool):
    """Tool to look up interaction rules, shortcuts, and URL patterns for webapps."""

    name = "lookup_webapp_template"
    description = (
        "Look up deterministic rules, shortcuts, URL patterns, and navigation instructions "
        "for popular web applications (e.g. WhatsApp, Gmail, GitHub, YouTube, Spotify, Notion, Google Docs)."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "app_name_or_url": {
                "type": "string",
                "description": "Name of the web application or the target URL/query.",
            },
        },
        "required": ["app_name_or_url"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import json
        query = str(kwargs.get("app_name_or_url", "")).strip()
        if not query:
            return ToolResult(
                name=self.name,
                content="Error: app_name_or_url parameter is required.",
                is_error=True,
            )

        tmpl = webapp_templates.get_template(query)
        if not tmpl:
            tmpl = webapp_templates.find_by_url(query)
        if not tmpl:
            tmpl = webapp_templates.find_by_query(query)

        if not tmpl:
            available = [t["app_name"] for t in webapp_templates.list_templates()]
            return ToolResult(
                name=self.name,
                content=f"Error: No template found for '{query}'. Available templates: {', '.join(available)}",
                is_error=True,
            )

        payload = {
            "app_name": tmpl.app_name,
            "description": tmpl.description,
            "url": tmpl.url,
            "rules": tmpl.rules,
            "url_patterns": tmpl.url_patterns,
            "instructions": tmpl.instructions,
        }
        return ToolResult(
            name=self.name,
            content=json.dumps(payload, indent=2),
            is_error=False,
            metadata=payload,
        )
