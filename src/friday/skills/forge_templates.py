"""FORGE Task Templates Library for FRIDAY.

Provides parameterized templates for common software engineering project types:
- WEBSITE: Responsive HTML5/CSS3/JS with modern UX, accessibility, and dark mode
- CLI_TOOL: Robust Python command-line utility with argparse, error handling, and help docs
- API_SERVICE: Production FastAPI microservice with Pydantic schemas, health checks, and pytest suite
- DASHBOARD: Real-time interactive dashboard with WebSocket telemetry and responsive UI
- SCRIPT: Python automation script with logging, robust exception handling, and documentation
"""

from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("skills.forge_templates")


class TaskTemplateType(str, Enum):
    """Categorization of standard FORGE build templates."""
    WEBSITE = "WEBSITE"
    CLI_TOOL = "CLI_TOOL"
    API_SERVICE = "API_SERVICE"
    DASHBOARD = "DASHBOARD"
    SCRIPT = "SCRIPT"
    CUSTOM = "CUSTOM"


class ForgeTemplateLibrary:
    """Expands high-level user software requests into structured FORGE build specifications."""

    TEMPLATES = {
        TaskTemplateType.WEBSITE: (
            "Build a responsive {type} website with {features}. "
            "Include: index.html semantic HTML5, style.css modern CSS flexbox/grid, "
            "app.js vanilla JavaScript. Mobile-responsive, accessible ARIA, dark mode toggle."
        ),
        TaskTemplateType.CLI_TOOL: (
            "Create a robust CLI {name} utility with {features}. "
            "Python argparse, JSON persistence, error handling, help text."
        ),
        TaskTemplateType.API_SERVICE: (
            "Build a FastAPI service with {endpoints}. "
            "Pydantic models, error handling, health endpoint, OpenAPI docs, pytest suite."
        ),
        TaskTemplateType.DASHBOARD: (
            "Build a real-time dashboard with {panels}. "
            "HTML/CSS/JS, WebSocket updates, responsive."
        ),
        TaskTemplateType.SCRIPT: (
            "Write a Python script that {functionality}. "
            "argparse CLI, logging, error handling, documentation."
        ),
    }

    @classmethod
    def detect_template_type(cls, user_goal: str) -> TaskTemplateType:
        """Identifies the software project type from the natural language prompt."""
        clean = user_goal.lower()
        if "website" in clean or "web page" in clean or "landing page" in clean or "portfolio" in clean:
            return TaskTemplateType.WEBSITE
        if "cli" in clean or "command line" in clean or "terminal tool" in clean:
            return TaskTemplateType.CLI_TOOL
        if "api" in clean or "fastapi" in clean or "rest service" in clean or "endpoint" in clean:
            return TaskTemplateType.API_SERVICE
        if "dashboard" in clean or "monitoring panel" in clean:
            return TaskTemplateType.DASHBOARD
        if "script" in clean or "automation" in clean:
            return TaskTemplateType.SCRIPT
        return TaskTemplateType.CUSTOM

    @classmethod
    def expand_goal(
        cls,
        user_goal: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Expands a short goal into a full engineering specification using templates."""
        ctx = context or {}
        template_type = cls.detect_template_type(user_goal)

        if template_type == TaskTemplateType.WEBSITE:
            site_type = ctx.get("type", "portfolio" if "portfolio" in user_goal.lower() else "modern")
            features = ctx.get("features", user_goal)
            return cls.TEMPLATES[TaskTemplateType.WEBSITE].format(type=site_type, features=features)

        elif template_type == TaskTemplateType.CLI_TOOL:
            name = ctx.get("name", "tool")
            features = ctx.get("features", user_goal)
            return cls.TEMPLATES[TaskTemplateType.CLI_TOOL].format(name=name, features=features)

        elif template_type == TaskTemplateType.API_SERVICE:
            endpoints = ctx.get("endpoints", user_goal)
            return cls.TEMPLATES[TaskTemplateType.API_SERVICE].format(endpoints=endpoints)

        elif template_type == TaskTemplateType.DASHBOARD:
            panels = ctx.get("panels", user_goal)
            return cls.TEMPLATES[TaskTemplateType.DASHBOARD].format(panels=panels)

        elif template_type == TaskTemplateType.SCRIPT:
            functionality = ctx.get("functionality", user_goal)
            return cls.TEMPLATES[TaskTemplateType.SCRIPT].format(functionality=functionality)

        # Custom fallback -> return goal directly with standard engineering requirements
        return (
            f"{user_goal.strip()}. "
            f"Include comprehensive error handling, unit tests with pytest, and full documentation."
        )
