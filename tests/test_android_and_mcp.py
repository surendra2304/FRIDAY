"""Unit tests verifying Android Device Controller and FastMCP server integrations."""

import pytest
from friday.devices.android_controller import AndroidDeviceController, COMMON_APP_PACKAGES, KEY_EVENT_MAP
from friday.tools.builtin.android_control import (
    AndroidTapTool,
    AndroidSwipeTool,
    AndroidTypeTool,
    AndroidKeyEventTool,
    AndroidOpenAppTool,
    AndroidDeviceInfoTool,
)
from friday.tools.registry import ToolRegistry


def test_android_key_and_app_mappings():
    """Verify common Android keys and app package aliases are mapped."""
    assert "home" in KEY_EVENT_MAP
    assert "back" in KEY_EVENT_MAP
    assert "app_switch" in KEY_EVENT_MAP
    assert KEY_EVENT_MAP["home"] == 3
    assert KEY_EVENT_MAP["back"] == 4

    assert "youtube" in COMMON_APP_PACKAGES
    assert "chrome" in COMMON_APP_PACKAGES
    assert COMMON_APP_PACKAGES["youtube"] == "com.google.android.youtube"


def test_android_device_controller_scaffold():
    """Verify Android controller builds commands properly."""
    ctrl = AndroidDeviceController(adb_device_id="emulator-5554")
    assert ctrl.device_type == "android"
    assert ctrl.adb_device_id == "emulator-5554"
    cmd = ctrl._build_cmd(["shell", "input", "tap", "100", "200"])
    assert "-s" in cmd
    assert "emulator-5554" in cmd
    assert "tap" in cmd


def test_android_tools_registered_in_registry():
    """Verify all Android tools instantiate and register in ToolRegistry."""
    reg = ToolRegistry()
    reg.register(AndroidTapTool())
    reg.register(AndroidSwipeTool())
    reg.register(AndroidTypeTool())
    reg.register(AndroidKeyEventTool())
    reg.register(AndroidOpenAppTool())
    reg.register(AndroidDeviceInfoTool())

    assert reg.get("android_tap") is not None
    assert reg.get("android_swipe") is not None
    assert reg.get("android_type") is not None
    assert reg.get("android_keyevent") is not None
    assert reg.get("android_open_app") is not None
    assert reg.get("android_device_info") is not None


def test_fastmcp_endpoints_in_api_server():
    """Verify FastMCP and Android endpoints are exposed on the FastAPI app."""
    from friday.api.server import app
    routes = [route.path for route in app.routes]
    assert "/sse" in routes
    assert "/messages" in routes
    assert "/api/command" in routes
    assert "/api/android" in routes
    assert "/api/tools" in routes
    assert "/api/health" in routes
    assert "/api/metrics" in routes
    assert "/api/ws/voice" in routes
