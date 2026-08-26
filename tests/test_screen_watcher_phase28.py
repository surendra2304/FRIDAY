# -*- coding: utf-8 -*-
"""Unit tests for Proactive Screen Reading (The Watcher) (The Watcher)."""

from unittest import mock
import pytest

from friday.core.config import Settings
from friday.core.types import Message, Role, ToolResult
from friday.observability.notifications import NotificationManager
from friday.vision.screen_watcher import ScreenWatcherService
from friday.workflows.scheduler import WorkflowScheduler


def test_screen_watcher_analyze_code_error():
    """Watcher classifies traceback as offer_debug and returns json action."""
    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content='{"action": "offer_debug"}')

    watcher = ScreenWatcherService(llm_provider=mock_llm)
    result = watcher.analyze_screen_text("Traceback (most recent call last):\n  File 'app.py', line 10, in <module>\n    raise ValueError('fail')")
    
    assert result["action"] == "offer_debug"
    mock_llm.generate.assert_called_once()


def test_screen_watcher_analyze_email_draft():
    """Watcher classifies email as offer_proofread."""
    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content='{"action": "offer_proofread"}')

    watcher = ScreenWatcherService(llm_provider=mock_llm)
    result = watcher.analyze_screen_text("Subject: Project Update\n\nDear Team,\nPlease find attached our weekly progress report.")
    
    assert result["action"] == "offer_proofread"


def test_screen_watcher_analyze_none():
    """Watcher classifies normal screen text as none."""
    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content='{"action": "none"}')

    watcher = ScreenWatcherService(llm_provider=mock_llm)
    result = watcher.analyze_screen_text("Welcome to the homepage of our corporate website.")
    
    assert result["action"] == "none"


def test_screen_watcher_check_and_notify():
    """Watcher extracts OCR, classifies, and pushes notification to NotificationManager."""
    notif_mgr = NotificationManager()
    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content='{"action": "offer_debug"}')

    watcher = ScreenWatcherService(notification_manager=notif_mgr, llm_provider=mock_llm)

    with mock.patch("friday.vision.screen_watcher.get_active_window_context") as mock_ctx, \
         mock.patch("friday.tools.builtin.screen_ocr.ReadScreenTextTool.execute") as mock_ocr:
        mock_ctx.return_value = {"title": "app.py - Visual Studio Code", "process_name": "Code.exe", "is_active": True}
        mock_ocr.return_value = ToolResult(name="read_screen_text", content="NameError: name 'x' is not defined", is_error=False)

        res = watcher.check_and_notify()
        assert res is not None
        assert res["action"] == "offer_debug"
        assert "VS Code" in res["message"]
        
        pending = notif_mgr.fetch_pending_notifications()
        assert len(pending) == 1
        assert "I noticed you hit an error in VS Code. Would you like me to analyze it?" in pending[0].message


def test_scheduler_proactive_watcher_integration():
    """WorkflowScheduler integrates check_screen_watcher_proactive when enabled."""
    notif_mgr = NotificationManager()
    scheduler = WorkflowScheduler(notification_manager=notif_mgr)
    
    with mock.patch("friday.core.config.get_settings") as mock_set:
        mock_set.return_value = Settings(proactive_watcher_enabled=True, watcher_interval_seconds=30.0)
        
        with mock.patch("friday.vision.screen_watcher.ScreenWatcherService.check_and_notify") as mock_check:
            mock_check.return_value = {"action": "offer_debug", "message": "error noticed"}
            
            res = scheduler.check_screen_watcher_proactive()
            assert res is not None
            assert res["action"] == "offer_debug"
            mock_check.assert_called_once()
