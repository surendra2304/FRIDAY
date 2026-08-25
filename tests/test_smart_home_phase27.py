# -*- coding: utf-8 -*-
"""Unit tests for Phase 27: IoT & Smart Home Control."""

from unittest import mock
import pytest
import httpx

from friday.core.config import Settings
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.builtin.smart_home import ControlLightTool, ControlPlugTool, _send_iot_request


def test_control_light_tool_is_safe():
    """ControlLightTool is marked SAFE and validates inputs."""
    tool = ControlLightTool()
    assert tool.safety_level == SafetyLevel.SAFE
    assert tool.name == "control_light"


def test_control_plug_tool_is_safe():
    """ControlPlugTool is marked SAFE and validates inputs."""
    tool = ControlPlugTool()
    assert tool.safety_level == SafetyLevel.SAFE
    assert tool.name == "control_plug"


def test_control_light_tool_success():
    """ControlLightTool sends successful HTTP POST to IoT hub."""
    tool = ControlLightTool()
    with mock.patch("friday.tools.builtin.smart_home._send_iot_request") as mock_req:
        mock_req.return_value = (True, "Command executed successfully.", {"status": "ok"})
        res = tool.execute(state=True, brightness=75)
        
        assert not res.is_error
        assert "Lights turned on at 75% brightness." in res.content
        mock_req.assert_called_once_with(
            "/api/services/light/toggle",
            {"state": "on", "brightness": 75},
        )


def test_control_light_tool_turn_off():
    """ControlLightTool turns off light without brightness suffix."""
    tool = ControlLightTool()
    with mock.patch("friday.tools.builtin.smart_home._send_iot_request") as mock_req:
        mock_req.return_value = (True, "Command executed successfully.", {"status": "ok"})
        res = tool.execute(state=False)
        
        assert not res.is_error
        assert "Lights turned off." in res.content
        mock_req.assert_called_once_with(
            "/api/services/light/toggle",
            {"state": "off"},
        )


def test_control_plug_tool_success():
    """ControlPlugTool sends toggle command for specific plug."""
    tool = ControlPlugTool()
    with mock.patch("friday.tools.builtin.smart_home._send_iot_request") as mock_req:
        mock_req.return_value = (True, "Command executed successfully.", {"status": "ok"})
        res = tool.execute(device_id="desk_fan", state=True)
        
        assert not res.is_error
        assert "Smart plug 'desk_fan' turned on." in res.content
        mock_req.assert_called_once_with(
            "/api/services/switch/toggle",
            {"device_id": "desk_fan", "state": "on"},
        )


def test_control_light_hub_offline_handling():
    """ControlLightTool handles offline / connection errors gracefully."""
    tool = ControlLightTool()
    with mock.patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        res = tool.execute(state=True)
        
        assert res.is_error
        assert "Unable to control lights" in res.content
        assert "Could not connect to local IoT Hub" in res.content
