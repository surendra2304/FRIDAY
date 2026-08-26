# -*- coding: utf-8 -*-
"""Unit tests for Full-Duplex Voice Engine3: Active Screen Awareness."""

import pytest
from unittest.mock import patch, MagicMock

from friday.vision.active_context import get_active_window_context, format_active_window_prompt
from friday.agent.prompts import get_default_system_prompt
from friday.core.config import Settings
from friday.tools.builtin.screen_ocr import GetActiveAppContextTool, ReadActiveWindowTextTool


def test_get_active_window_context_mocked():
    with patch("sys.platform", "win32"):
        with patch("win32gui.GetForegroundWindow", return_value=12345):
            with patch("win32gui.GetWindowText", return_value="test.py - Visual Studio Code"):
                with patch("win32process.GetWindowThreadProcessId", return_value=(0, 999)):
                    with patch("psutil.Process") as mock_proc_cls:
                        mock_proc = MagicMock()
                        mock_proc.name.return_value = "Code.exe"
                        mock_proc_cls.return_value = mock_proc

                        ctx = get_active_window_context()
                        assert ctx["is_active"] is True
                        assert ctx["title"] == "test.py - Visual Studio Code"
                        assert ctx["process_name"] == "Code.exe"

                        prompt_line = format_active_window_prompt()
                        assert "Visual Studio Code" in prompt_line
                        assert "Code" in prompt_line


def test_system_prompt_includes_active_context():
    settings = Settings()
    with patch("friday.vision.active_context.format_active_window_prompt", return_value="The user is currently looking at: Chrome - Google Search."):
        prompt = get_default_system_prompt(settings, include_active_context=True)
        assert "AMBIENT SCREEN CONTEXT" in prompt
        assert "The user is currently looking at: Chrome - Google Search." in prompt


def test_get_active_app_context_tool():
    tool = GetActiveAppContextTool()
    assert tool.name == "get_active_app_context"
    
    with patch("friday.vision.active_context.get_active_window_context", return_value={
        "title": "Document1 - Word",
        "process_name": "WINWORD.EXE",
        "url": None,
        "is_active": True,
    }):
        result = tool.execute()
        assert not result.is_error
        assert "WINWORD.EXE" in result.content
        assert "Document1 - Word" in result.content


def test_read_active_window_text_tool_graceful_handling():
    tool = ReadActiveWindowTextTool()
    assert tool.name == "read_active_window_text"

    with patch("friday.tools.builtin.screen_ocr._capture_screen", return_value=MagicMock()):
        with patch("friday.tools.builtin.screen_ocr._run_ocr", return_value=[
            ("Hello", (10, 10, 50, 30)),
            ("World", (60, 10, 100, 30)),
        ]):
            result = tool.execute()
            assert not result.is_error
            assert "Hello World" in result.content
