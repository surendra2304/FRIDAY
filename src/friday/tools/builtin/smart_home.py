# -*- coding: utf-8 -*-
"""Smart Home & IoT Control tools for Phase 27.

Controls physical devices (lights, smart plugs, switches) via local network HTTP APIs
(e.g., Home Assistant or standard local IoT REST bridges) using httpx.
"""

from typing import Any, Dict, Optional
import os

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.smart_home")


def _get_iot_config() -> tuple[str, Optional[str]]:
    """Retrieve configured IoT hub URL and auth token."""
    settings = get_settings()
    url = getattr(settings, "iot_hub_url", "http://localhost:8123") or os.getenv("FRIDAY_IOT_HUB_URL", "http://localhost:8123")
    token = getattr(settings, "iot_hub_token", None) or os.getenv("FRIDAY_IOT_HUB_TOKEN")
    return url.rstrip("/"), token


def _send_iot_request(endpoint: str, payload: Dict[str, Any]) -> tuple[bool, str, Optional[Dict[str, Any]]]:
    """Synchronous wrapper to POST commands to the local IoT hub with timeout & offline handling."""
    import httpx

    base_url, token = _get_iot_config()
    target_url = f"{base_url}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(target_url, json=payload, headers=headers)
            if resp.status_code in (200, 201, 204):
                try:
                    data = resp.json()
                except Exception:
                    data = {"status": "ok"}
                return True, "Command executed successfully.", data
            else:
                return False, f"IoT Hub returned HTTP {resp.status_code}: {resp.text}", None
    except httpx.ConnectError:
        logger.warning(f"Local IoT Hub unreachable at '{base_url}'")
        return False, f"Could not connect to local IoT Hub at {base_url}. Please ensure your hub is online.", None
    except httpx.TimeoutException:
        logger.warning(f"Timeout communicating with local IoT Hub at '{base_url}'")
        return False, f"Request to local IoT Hub at {base_url} timed out.", None
    except Exception as e:
        logger.error(f"IoT Hub request failed: {e}")
        return False, f"Failed to communicate with IoT Hub: {str(e)}", None


class ControlLightTool(BaseTool):
    """Control smart light state and brightness via local IoT hub."""

    name = "control_light"
    description = (
        "Turn smart lights on or off and set brightness (0-100%). "
        "Operates via the local smart home network."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "boolean",
                "description": "True to turn light ON, False to turn light OFF.",
            },
            "brightness": {
                "type": "integer",
                "description": "Optional brightness level from 0 to 100.",
                "minimum": 0,
                "maximum": 100,
            },
            "device_id": {
                "type": "string",
                "description": "Optional specific light device ID or entity name (defaults to main room lights).",
            },
        },
        "required": ["state"],
    }

    def execute(
        self,
        state: bool,
        brightness: Optional[int] = None,
        device_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        payload: Dict[str, Any] = {
            "state": "on" if state else "off",
        }
        if brightness is not None:
            # Clamp brightness between 0 and 100
            clamped_b = max(0, min(100, int(brightness)))
            payload["brightness"] = clamped_b
            if clamped_b == 0:
                payload["state"] = "off"
        if device_id:
            payload["device_id"] = device_id

        success, msg, data = _send_iot_request("/api/services/light/toggle", payload)
        
        status_text = "on" if payload["state"] == "on" else "off"
        b_text = f" at {payload.get('brightness')}% brightness" if "brightness" in payload and payload["state"] == "on" else ""
        target_name = device_id or "Lights"
        
        if success:
            content = f"{target_name} turned {status_text}{b_text}."
            logger.info(f"[IoT] {content}")
            return ToolResult(
                name=self.name,
                content=content,
                is_error=False,
                safety_level=self.safety_level,
                metadata={"state": payload["state"], "brightness": payload.get("brightness"), "device_id": device_id},
            )
        else:
            return ToolResult(
                name=self.name,
                content=f"Unable to control lights: {msg}",
                is_error=True,
                safety_level=self.safety_level,
            )


class ControlPlugTool(BaseTool):
    """Toggle a smart plug / power switch via local IoT hub."""

    name = "control_plug"
    description = (
        "Toggle a smart power plug on or off using its device ID or name."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "ID or entity name of the smart plug (e.g. 'plug_1', 'desk_fan').",
            },
            "state": {
                "type": "boolean",
                "description": "True to turn ON, False to turn OFF.",
            },
        },
        "required": ["device_id", "state"],
    }

    def execute(self, device_id: str, state: bool, **kwargs: Any) -> ToolResult:
        clean_id = (device_id or "").strip()
        if not clean_id:
            return ToolResult(
                name=self.name,
                content="Error: No device_id provided for smart plug.",
                is_error=True,
                safety_level=self.safety_level,
            )

        payload = {
            "device_id": clean_id,
            "state": "on" if state else "off",
        }
        success, msg, data = _send_iot_request("/api/services/switch/toggle", payload)

        status_text = "on" if state else "off"
        if success:
            content = f"Smart plug '{clean_id}' turned {status_text}."
            logger.info(f"[IoT] {content}")
            return ToolResult(
                name=self.name,
                content=content,
                is_error=False,
                safety_level=self.safety_level,
                metadata={"device_id": clean_id, "state": status_text},
            )
        else:
            return ToolResult(
                name=self.name,
                content=f"Unable to control smart plug '{clean_id}': {msg}",
                is_error=True,
                safety_level=self.safety_level,
            )
