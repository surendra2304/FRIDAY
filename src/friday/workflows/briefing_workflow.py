# -*- coding: utf-8 -*-
"""Morning Briefing Workflow for Daily Intelligence.

Aggregates calendar meetings (.ics feed), real-time weather information (via web search),
and system status to provide a concise, spoken daily briefing:
"Good morning Surendra. You have X meetings today. The weather is Y."
"""

from typing import Any, Dict, Optional
import os
import re
from datetime import datetime

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.tools.builtin.calendar import GetTodaysEventsTool, _parse_ics_content
from friday.tools.builtin.web_tools import WebSearchTool

logger = get_logger("workflows.briefing")


class MorningBriefingWorkflow:
    """Orchestrates morning briefings combining schedule, weather, and reminders."""

    def __init__(
        self,
        calendar_tool: Optional[GetTodaysEventsTool] = None,
        search_tool: Optional[WebSearchTool] = None,
    ) -> None:
        self.calendar_tool = calendar_tool or GetTodaysEventsTool()
        self.search_tool = search_tool or WebSearchTool()

    def can_handle(self, user_prompt: str) -> bool:
        """Check if user prompt requests a daily or morning briefing (excluding trading-specific briefings)."""
        if not user_prompt:
            return False
        clean = user_prompt.strip().lower()
        if "trading" in clean:
            return False
        pattern = r"\b(?:morning\s+briefing|daily\s+briefing|give\s+me\s+(?:my\s+)?briefing|brief\s+me|my\s+schedule\s+today|today'?s?\s+agenda)\b"
        return bool(re.search(pattern, user_prompt, re.IGNORECASE))

    async def generate_briefing(self, user_name: Optional[str] = None) -> Dict[str, Any]:
        """Fetch today's schedule and weather to construct the spoken briefing."""
        settings = get_settings()
        name = user_name or getattr(settings, "user_name", "Surendra") or "Surendra"

        # 1. Fetch Calendar Events
        cal_res = self.calendar_tool.execute()
        meeting_count = 0
        meetings_detail = []

        if not cal_res.is_error and "have no meetings" not in cal_res.content and "No calendar feed configured" not in cal_res.content:
            # Parse number of lines with numbered meetings
            lines = [l for l in cal_res.content.splitlines() if re.match(r"^\d+\.", l.strip())]
            meeting_count = len(lines)
            meetings_detail = lines
        elif "No calendar feed configured" in cal_res.content:
            meeting_count = 0

        # 2. Fetch Weather via Search
        weather_summary = "clear"
        try:
            w_res = self.search_tool.execute(query="current weather forecast today")
            if not w_res.is_error and w_res.content:
                # Extract first brief summary or keyword
                first_snippet = w_res.content.split("\n")[0] if "\n" in w_res.content else w_res.content
                if any(w in w_res.content.lower() for w in ["rain", "shower", "thunderstorm"]):
                    weather_summary = "rainy with possible showers"
                elif any(w in w_res.content.lower() for w in ["cloud", "overcast"]):
                    weather_summary = "partly cloudy"
                elif any(w in w_res.content.lower() for w in ["snow", "flurries"]):
                    weather_summary = "cold with snow"
                else:
                    weather_summary = "sunny and clear"
        except Exception as e:
            logger.warning(f"Weather lookup fallback: {e}")
            weather_summary = "pleasant"

        # 3. Format Spoken Response
        now = datetime.now().astimezone()
        greeting = "Good morning" if now.hour < 12 else ("Good afternoon" if now.hour < 17 else "Good evening")

        if meeting_count == 0:
            schedule_phrase = "You have no meetings scheduled for today."
        elif meeting_count == 1:
            schedule_phrase = "You have 1 meeting scheduled today."
        else:
            schedule_phrase = f"You have {meeting_count} meetings today."

        spoken_briefing = f"{greeting} {name}. {schedule_phrase} The weather is {weather_summary}."

        if meetings_detail:
            spoken_briefing += "\n\nSchedule:\n" + "\n".join(meetings_detail)

        return {
            "greeting": greeting,
            "user_name": name,
            "meeting_count": meeting_count,
            "weather": weather_summary,
            "spoken_text": spoken_briefing,
            "timestamp": now.isoformat(),
        }
