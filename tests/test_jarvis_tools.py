"""Unit tests for newly integrated J.A.R.V.I.S capability tools."""

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from friday.tools.builtin.dictionary_tool import DictionaryTool
from friday.tools.builtin.email_tools import DraftEmailTool
from friday.tools.builtin.location_maps import LocationMapsTool
from friday.tools.builtin.media_control import MediaControlTool
from friday.tools.builtin.news import NewsTool
from friday.tools.builtin.open_website import OpenWebsiteTool
from friday.tools.builtin.remember import RememberFactTool
from friday.tools.builtin.task_management import ManageTasksTool
from friday.tools.builtin.weather import WeatherTool
from friday.tools.builtin.wikipedia_tool import WikipediaTool
from friday.tools.builtin.youtube import YouTubeTool


def test_draft_email_tool():
    tool = DraftEmailTool()
    res = tool.execute(to_address="john@example.com", subject="Meeting", body="See you at 6.")
    assert res.is_error is False
    assert "john@example.com" in res.content
    assert "See you at 6" in res.content


def test_open_website_tool():
    tool = OpenWebsiteTool()
    with patch("webbrowser.open") as mock_open:
        res = tool.execute(target="youtube")
        assert res.is_error is False
        mock_open.assert_called_once_with("https://www.youtube.com")

        mock_open.reset_mock()
        res2 = tool.execute(target="https://github.com/trending")
        assert res2.is_error is False
        mock_open.assert_called_once_with("https://github.com/trending")


def test_youtube_tool():
    tool = YouTubeTool()
    with patch("webbrowser.open") as mock_open:
        res = tool.execute(query="lofi hip hop")
        assert res.is_error is False
        assert "Searching YouTube" in res.content
        mock_open.assert_called_once()
        assert "search_query=lofi+hip+hop" in mock_open.call_args[0][0]


def test_location_and_maps_tool():
    tool = LocationMapsTool()
    with patch("webbrowser.open") as mock_open:
        res = tool.execute(action="search_maps", query="restaurants near me", open_in_browser=True)
        assert res.is_error is False
        mock_open.assert_called_once()


def test_media_control_tool():
    tool = MediaControlTool()
    with patch("friday.tools.builtin.media_control._send_windows_media_key", return_value=True):
        res = tool.execute(action="play_pause")
        assert res.is_error is False
        assert "Play/Pause" in res.content

        res_next = tool.execute(action="next")
        assert res_next.is_error is False


def test_dictionary_tool():
    tool = DictionaryTool()
    # Test spelling check
    res_spell = tool.execute(word="accommodate", action="spell_check")
    assert res_spell.is_error is False

    # Mock dictionary API response
    fake_data = [
        {
            "word": "ephemeral",
            "phonetic": "/ɪˈfɛm(ə)rəl/",
            "meanings": [
                {
                    "partOfSpeech": "adjective",
                    "definitions": [
                        {"definition": "Lasting for a very short time.", "example": "fashions are ephemeral"}
                    ],
                }
            ],
        }
    ]
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: fake_data)
        res_def = tool.execute(word="ephemeral", action="define")
        assert res_def.is_error is False
        assert "Ephemeral" in res_def.content
        assert "Lasting for a very short time" in res_def.content


def test_weather_tool():
    tool = WeatherTool()
    fake_weather = {
        "current": {
            "temperature_2m": 26.5,
            "apparent_temperature": 27.2,
            "relative_humidity_2m": 65,
            "wind_speed_10m": 12.0,
            "weather_code": 0,
        },
        "daily": {
            "weather_code": [0],
            "temperature_2m_max": [30.0],
            "temperature_2m_min": [22.0],
            "precipitation_probability_max": [10],
        },
    }
    with patch("friday.tools.builtin.weather.geocode_city", return_value=(17.38, 78.48, "Hyderabad, India")):
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: fake_weather)
            res = tool.execute(city="Hyderabad")
            assert res.is_error is False
            assert "Hyderabad" in res.content
            assert "26.5°C" in res.content


def test_wikipedia_tool():
    tool = WikipediaTool()
    fake_opensearch = ["Alan Turing", ["Alan Turing"], ["English mathematician"], ["https://en.wikipedia.org/wiki/Alan_Turing"]]
    fake_summary = {
        "title": "Alan Turing",
        "extract": "Alan Mathison Turing was an English mathematician, computer scientist, and logician.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Alan_Turing"}},
    }
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: fake_opensearch),
            MagicMock(status_code=200, json=lambda: fake_summary),
        ]
        res = tool.execute(query="Alan Turing")
        assert res.is_error is False
        assert "Alan Turing" in res.content
        assert "mathematician" in res.content


def test_remember_tool():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        tool = RememberFactTool(db_path=db_path)
        res = tool.execute(fact="My presentation is on Friday at 10 AM", category="schedule")
        assert res.is_error is False
        assert "remembered" in res.content
    finally:
        try:
            os.remove(db_path)
        except Exception:
            pass


def test_manage_tasks_tool():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        from friday.persistence.task_store import SQLiteTaskStore
        store = SQLiteTaskStore(db_path=db_path)
        tool = ManageTasksTool(store=store)

        # Create
        res_create = tool.execute(action="create", title="Buy milk", priority="high")
        assert res_create.is_error is False
        assert "Buy milk" in res_create.content

        # List
        res_list = tool.execute(action="list")
        assert res_list.is_error is False
        assert "Buy milk" in res_list.content

        # Complete
        res_comp = tool.execute(action="complete", title="Buy milk")
        assert res_comp.is_error is False
        assert "complete" in res_comp.content
    finally:
        try:
            os.remove(db_path)
        except Exception:
            pass


def test_news_tool():
    tool = NewsTool()
    fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Google News</title>
            <item>
                <title>AI Breakthrough Announced by Researchers - Tech Times</title>
                <link>https://example.com/ai-news</link>
                <pubDate>Thu, 03 Sep 2026 04:00:00 GMT</pubDate>
                <source>Tech Times</source>
            </item>
        </channel>
    </rss>
    """
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text=fake_rss)
        res = tool.execute(category="technology", limit=1)
        assert res.is_error is False
        assert "Technology News Headlines" in res.content
        assert "AI Breakthrough" in res.content

