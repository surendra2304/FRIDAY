# -*- coding: utf-8 -*-
"""Unit tests for Calendar Tool & Morning Briefing Workflow."""

from datetime import datetime, date
from unittest import mock
import pytest

from friday.core.types import SafetyLevel
from friday.tools.builtin.calendar import GetTodaysEventsTool, _parse_ics_content
from friday.workflows.briefing_workflow import MorningBriefingWorkflow


SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//FRIDAY Test//EN
BEGIN:VEVENT
UID:event-1@friday
SUMMARY:Daily Standup Meeting
DTSTART:20260825T093000Z
DTEND:20260825T100000Z
LOCATION:Zoom Room 1
END:VEVENT
BEGIN:VEVENT
UID:event-2@friday
SUMMARY:Product Roadmap Sync
DTSTART:20260825T140000Z
DTEND:20260825T150000Z
LOCATION:HQ Boardroom
END:VEVENT
BEGIN:VEVENT
UID:event-3@friday
SUMMARY:1-on-1 with Lead Architect
DTSTART:20260825T163000Z
DTEND:20260825T170000Z
LOCATION:Office
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_content():
    """_parse_ics_content parses meetings for the specified target date."""
    target_d = date(2026, 8, 25)
    events = _parse_ics_content(SAMPLE_ICS, target_date=target_d)
    assert len(events) == 3
    assert events[0]["title"] == "Daily Standup Meeting"
    assert "Zoom Room 1" in events[0]["location"]
    assert events[1]["title"] == "Product Roadmap Sync"
    assert events[2]["title"] == "1-on-1 with Lead Architect"


def test_calendar_tool_execution_with_mock_ics(tmp_path):
    """GetTodaysEventsTool loads and formats calendar entries from a file path."""
    ics_file = tmp_path / "calendar.ics"
    ics_file.write_text(SAMPLE_ICS, encoding="utf-8")

    tool = GetTodaysEventsTool()
    assert tool.safety_level == SafetyLevel.SAFE
    assert tool.name == "get_todays_events"

    with mock.patch("friday.tools.builtin.calendar._parse_ics_content") as mock_parse:
        mock_parse.return_value = [
            {"title": "Daily Standup", "time_range": "09:30 AM - 10:00 AM", "location": "Zoom"},
            {"title": "Architecture Review", "time_range": "02:00 PM - 03:00 PM", "location": ""},
        ]
        res = tool.execute(calendar_url=str(ics_file))
        assert not res.is_error
        assert "You have 2 meetings scheduled today:" in res.content
        assert "Daily Standup" in res.content
        assert "Architecture Review" in res.content


def test_calendar_tool_no_url_configured():
    """GetTodaysEventsTool handles unconfigured .ics gracefully."""
    tool = GetTodaysEventsTool()
    with mock.patch("friday.tools.builtin.calendar.get_settings") as mock_set:
        mock_set.return_value = mock.MagicMock(calendar_ics_url=None)
        with mock.patch.dict("os.environ", {}, clear=True):
            res = tool.execute()
            assert not res.is_error
            assert "No calendar feed configured" in res.content


def test_morning_briefing_workflow_generation():
    """MorningBriefingWorkflow constructs spoken briefing with meetings and weather."""
    import asyncio

    mock_cal = mock.MagicMock()
    mock_cal.execute.return_value = mock.MagicMock(
        is_error=False,
        content="You have 3 meetings scheduled today:\n1. Standup at 09:30 AM\n2. Sync at 02:00 PM\n3. Review at 04:30 PM",
    )

    mock_search = mock.MagicMock()
    mock_search.execute.return_value = mock.MagicMock(
        is_error=False,
        content="The current weather forecast is sunny and clear with a high of 75F.",
    )

    workflow = MorningBriefingWorkflow(calendar_tool=mock_cal, search_tool=mock_search)
    assert workflow.can_handle("Give me my morning briefing")
    assert workflow.can_handle("today's agenda")

    briefing = asyncio.run(workflow.generate_briefing(user_name="Surendra"))
    assert briefing["user_name"] == "Surendra"
    assert briefing["meeting_count"] == 3
    assert "sunny" in briefing["weather"]
    assert "Surendra" in briefing["spoken_text"]
    assert "You have 3 meetings today" in briefing["spoken_text"]

