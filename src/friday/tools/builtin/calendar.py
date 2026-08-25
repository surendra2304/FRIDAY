# -*- coding: utf-8 -*-
"""Calendar and schedule management tools using .ics format.

Provides tools to fetch, parse, and list upcoming events for today using icalendar
and recurring-ical-events libraries.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, date, time, timezone
import os
import httpx

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.calendar")

_FETCH_TIMEOUT = 10.0


def _parse_ics_content(ics_text: str, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Parse raw iCalendar text and return list of meetings occurring on target_date."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics_text)
    day = target_date or datetime.now().astimezone().date()

    # Query events for the single target day (start of day to end of day)
    start_dt = datetime.combine(day, time.min).astimezone()
    end_dt = datetime.combine(day, time.max).astimezone()

    events_for_day = recurring_ical_events.of(cal).between(start_dt, end_dt)

    results = []
    for ev in events_for_day:
        summary = str(ev.get("SUMMARY", "Untitled Meeting"))
        dtstart = ev.get("DTSTART")
        dtend = ev.get("DTEND")
        loc = str(ev.get("LOCATION", "")).strip()

        start_str = "All Day"
        end_str = ""

        if dtstart:
            dt_val = dtstart.dt
            if isinstance(dt_val, datetime):
                start_str = dt_val.astimezone().strftime("%I:%M %p")
            elif isinstance(dt_val, date):
                start_str = "All Day"

        if dtend:
            dt_val = dtend.dt
            if isinstance(dt_val, datetime):
                end_str = dt_val.astimezone().strftime("%I:%M %p")

        time_range = f"{start_str} - {end_str}" if end_str and start_str != "All Day" else start_str
        results.append({
            "title": summary,
            "start": start_str,
            "end": end_str,
            "time_range": time_range,
            "location": loc,
        })

    return results


class GetTodaysEventsTool(BaseTool):
    """Fetch and list today's calendar events from configured .ics feed."""

    name = "get_todays_events"
    description = (
        "Retrieve a list of today's scheduled calendar meetings and events "
        "(Title, Start Time, End Time, and Location) from the configured calendar feed."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "calendar_url": {
                "type": "string",
                "description": "Optional .ics URL override. If omitted, uses FRIDAY_CALENDAR_ICS_URL from settings.",
            },
        },
        "required": [],
    }

    def execute(self, calendar_url: Optional[str] = None, **kwargs: Any) -> ToolResult:
        settings = get_settings()
        url = calendar_url or getattr(settings, "calendar_ics_url", None) or os.getenv("FRIDAY_CALENDAR_ICS_URL")

        if not url:
            return ToolResult(
                name=self.name,
                content="No calendar feed configured. Set FRIDAY_CALENDAR_ICS_URL in your .env file.",
                is_error=False,
                safety_level=self.safety_level,
            )

        target_url = url.strip()

        # Support file:// or direct local paths for testing/offline feeds
        if os.path.exists(target_url):
            try:
                with open(target_url, "r", encoding="utf-8") as f:
                    ics_data = f.read()
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    content=f"Failed to read local calendar file: {e}",
                    is_error=True,
                    safety_level=self.safety_level,
                )
        else:
            try:
                with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                    resp = client.get(target_url)
                resp.raise_for_status()
                ics_data = resp.text
            except Exception as e:
                logger.warning(f"Failed to fetch calendar from '{target_url}': {e}")
                return ToolResult(
                    name=self.name,
                    content=f"Failed to fetch calendar feed: {str(e)}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        try:
            events = _parse_ics_content(ics_data)
        except Exception as e:
            logger.error(f"Failed to parse calendar .ics: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to parse calendar events: {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not events:
            return ToolResult(
                name=self.name,
                content="You have no meetings scheduled for today.",
                is_error=False,
                safety_level=self.safety_level,
            )

        lines = [f"You have {len(events)} meeting{'s' if len(events) != 1 else ''} scheduled today:"]
        for i, ev in enumerate(events, 1):
            loc_info = f" ({ev['location']})" if ev.get("location") else ""
            lines.append(f"{i}. {ev['title']} at {ev['time_range']}{loc_info}")

        return ToolResult(
            name=self.name,
            content="\n".join(lines),
            is_error=False,
            safety_level=self.safety_level,
        )
