# -*- coding: utf-8 -*-
"""Unit tests for Phase 25: System Resource Manager and Proactive Alerting."""

import pytest
from unittest.mock import MagicMock, patch

from friday.tools.builtin.system_monitor import (
    GetSystemResourcesTool,
    KillProcessTool,
    get_current_system_resources,
)
from friday.workflows.scheduler import WorkflowScheduler
from friday.observability.notifications import NotificationManager
from friday.core.types import SafetyLevel


def test_get_system_resources_tool_mocked():
    tool = GetSystemResourcesTool()
    assert tool.name == "get_system_resources"
    assert tool.safety_level == SafetyLevel.SAFE

    mock_virtual_mem = MagicMock(percent=45.0, total=16 * (1024**3), used=7.2 * (1024**3))
    mock_p1 = MagicMock()
    mock_p1.info = {
        "pid": 1111,
        "name": "chrome.exe",
        "memory_info": MagicMock(rss=1024 * 1024 * 500),  # 500 MB
        "cpu_percent": 12.5,
    }

    with patch("psutil.cpu_percent", return_value=35.0):
        with patch("psutil.virtual_memory", return_value=mock_virtual_mem):
            with patch("psutil.process_iter", return_value=[mock_p1]):
                result = tool.execute()
                assert not result.is_error
                assert "CPU Usage: 35.0%" in result.content
                assert "RAM Usage: 45.0%" in result.content
                assert "chrome.exe" in result.content


def test_get_system_resources_specific_process():
    tool = GetSystemResourcesTool()
    mock_p1 = MagicMock()
    mock_p1.info = {
        "pid": 2222,
        "name": "Spotify.exe",
        "memory_info": MagicMock(rss=1024 * 1024 * 350),  # 350 MB
        "cpu_percent": 2.0,
    }

    with patch("psutil.cpu_percent", return_value=20.0):
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=30.0, total=16*(1024**3), used=4*(1024**3))):
            with patch("psutil.process_iter", return_value=[mock_p1]):
                result = tool.execute(process_name="spotify")
                assert not result.is_error
                assert "Spotify.exe" in result.content
                assert "350.0 MB RAM" in result.content


def test_kill_process_tool_by_name():
    tool = KillProcessTool()
    assert tool.name == "kill_process"
    assert tool.safety_level == SafetyLevel.DANGEROUS

    mock_proc = MagicMock()
    mock_proc.info = {"pid": 5555, "name": "Spotify.exe"}
    
    with patch("psutil.process_iter", return_value=[mock_proc]):
        result = tool.execute(pid_or_name="Spotify")
        assert not result.is_error
        assert "Successfully terminated 1 process" in result.content
        mock_proc.terminate.assert_called_once()


def test_proactive_resource_alert_in_scheduler():
    notif_mgr = NotificationManager()
    scheduler = WorkflowScheduler(notification_manager=notif_mgr)

    # 1. First tick at 95% CPU sets the initial timestamp
    with patch("friday.tools.builtin.system_monitor.get_current_system_resources", return_value={
        "cpu_percent": 95.0,
        "ram_percent": 80.0,
        "top_processes": [{"name": "heavy_task.exe", "pid": 9999, "memory_mb": 1200}],
    }):
        res1 = scheduler.check_system_resources_proactive(cpu_threshold=90.0, sustained_seconds=120.0)
        assert res1["alert"] is False
        assert len(notif_mgr.fetch_pending_notifications()) == 0

        # Simulate time passing by 130 seconds
        scheduler._high_cpu_start_time -= 130.0

        # 2. Second check triggers notification
        res2 = scheduler.check_system_resources_proactive(cpu_threshold=90.0, sustained_seconds=120.0)
        assert res2["alert"] is True
        assert "heavy_task.exe" in res2["message"]
        
        pending = notif_mgr.fetch_pending_notifications()
        assert len(pending) == 1
        assert "heavy_task.exe" in pending[0].message
