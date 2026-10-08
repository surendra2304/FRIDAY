"""WhatsApp Automation and Messaging Tools for FRIDAY.

Provides dual-channel WhatsApp communication:
1. Android ADB Intent dispatch (native background app launch and direct send).
2. WhatsApp Web / Desktop protocol launch via system browser or desktop app.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Any

from friday.core.effects import open_url_verified
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.devices.android_controller import AndroidDeviceController
from friday.tools.base import BaseTool

logger = get_logger("tools.whatsapp")


def _clean_phone_number(phone: str) -> str:
    """Normalize phone number to international format without spaces or symbols."""
    clean = re.sub(r"[^\d+]", "", phone.strip())
    if clean.startswith("+"):
        clean = clean[1:]
    return clean


class SendWhatsAppMessageTool(BaseTool):
    """Tool to send WhatsApp messages via connected Android device or WhatsApp Web/Desktop."""

    name = "send_whatsapp_message"
    description = (
        "Send a WhatsApp message to a phone number or contact. Automatically uses "
        "a connected Android phone via ADB intent dispatch if available, or launches "
        "WhatsApp Web/Desktop on Windows."
    )
    # Sending is an external side effect; the registry must require a scoped
    # authorization capability before Android can press Send or a URL is opened.
    safety_level = SafetyLevel.SENSITIVE
    risk_level = "SENSITIVE"
    auth_requirement = "USER"
    side_effects = ["external_message"]
    parameters = {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "Recipient phone number with country code (e.g. '+919876543210' or '919876543210') or contact name.",
            },
            "message": {
                "type": "string",
                "description": "Text message content to send via WhatsApp.",
            },
            "channel": {
                "type": "string",
                "enum": ["auto", "android", "web"],
                "description": "Execution channel: 'auto' (recommended), 'android', or 'web'.",
            },
        },
        "required": ["recipient", "message"],
    }

    def execute(self, recipient: str, message: str, channel: str = "auto", **kwargs: Any) -> ToolResult:
        recip = (recipient or "").strip()
        msg = (message or "").strip()

        if not recip:
            return ToolResult(
                name=self.name,
                content="Error: Recipient phone number or contact is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not msg:
            return ToolResult(
                name=self.name,
                content="Error: WhatsApp message content cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        clean_phone = _clean_phone_number(recip)
        encoded_msg = urllib.parse.quote(msg)

        # 1. Try Android first if channel is 'auto' or 'android'
        if channel in ("auto", "android"):
            android = AndroidDeviceController()
            if android.is_connected():
                logger.info(f"Dispatching WhatsApp message to '{recip}' via connected Android device")
                try:
                    # Construct WhatsApp deep link intent
                    if clean_phone:
                        wa_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
                    else:
                        wa_url = f"https://api.whatsapp.com/send?text={encoded_msg}"

                    # Launch via ADB am start
                    rc, out, err = android.run_adb([
                        "shell", "am", "start", "-a", "android.intent.action.VIEW",
                        "-d", wa_url, "com.whatsapp",
                    ])

                    if rc == 0:
                        # ``am start`` returning 0 means Android accepted the
                        # intent and opened WhatsApp. It does not mean the
                        # message left the device: the composer is what opens,
                        # and the send key is pressed into whatever has focus.
                        # The reply used to say "Successfully sent ...", which is
                        # the one claim this bridge cannot support.
                        time.sleep(2.0)
                        android.press_key("enter")
                        return ToolResult(
                            name=self.name,
                            content=(
                                f"Opened WhatsApp on the connected Android device with the message to "
                                f"{recip} in the composer and pressed send. This is a dispatch, not a "
                                "delivery receipt: FRIDAY cannot read WhatsApp's message status."
                            ),
                            is_error=False,
                            safety_level=self.safety_level,
                            metadata={
                                "channel": "android",
                                "recipient": recip,
                                "delivery_confirmed": False,
                                "dispatch": "intent_accepted",
                            },
                        )
                except Exception as ex:
                    logger.warning(f"Android WhatsApp dispatch failed: {ex}")
                    if channel == "android":
                        return ToolResult(
                            name=self.name,
                            content=f"Failed to send via Android: {ex}",
                            is_error=True,
                            safety_level=self.safety_level,
                        )

        # 2. Fallback or explicit Web / Desktop
        logger.info(f"Opening WhatsApp Web / Desktop for recipient '{recip}'")
        target_url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}" if clean_phone else "https://web.whatsapp.com"
        # webbrowser.open returns False when no browser accepted the URL; the
        # return value used to be discarded, so a machine with no browser was
        # told the message was "pre-filled" in a window that never appeared.
        outcome = open_url_verified(target_url)
        if not outcome.ok:
            return ToolResult(
                name=self.name,
                content=(
                    f"The message to {recip} was NOT sent and NOT pre-filled: {outcome.detail} "
                    "Open WhatsApp yourself, or connect an Android device over ADB so FRIDAY can dispatch it."
                ),
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
                metadata={"channel": "web", "recipient": recip, "url": target_url, **outcome.evidence},
            )
        return ToolResult(
            name=self.name,
            content=(
                f"Opened WhatsApp Web for recipient {recip} with the message pre-filled. "
                "This is not a delivery confirmation: the send button has to be pressed in the browser."
            ),
            is_error=False,
            safety_level=self.safety_level,
            metadata={
                "channel": "web",
                "recipient": recip,
                "url": target_url,
                "delivery_confirmed": False,
                **outcome.evidence,
            },
        )


class OpenWhatsAppTool(BaseTool):
    """Tool to open WhatsApp on the desktop or connected Android device."""

    name = "open_whatsapp"
    description = "Launch WhatsApp on the local Windows desktop or connected Android phone."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "enum": ["auto", "windows", "android"],
                "description": "Target device to open WhatsApp on.",
            }
        },
    }

    def execute(self, device: str = "auto", **kwargs: Any) -> ToolResult:
        if device in ("auto", "android"):
            android = AndroidDeviceController()
            if android.is_connected():
                ok = android.open_app("whatsapp")
                if ok:
                    return ToolResult(
                        name=self.name,
                        content="Opened WhatsApp on connected Android device.",
                        is_error=False,
                        safety_level=self.safety_level,
                    )

        # Fallback or explicit windows
        outcome = open_url_verified("https://web.whatsapp.com")
        if not outcome.ok:
            return ToolResult(
                name=self.name,
                content=f"Could not open WhatsApp: {outcome.detail}",
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
                metadata=outcome.evidence,
            )
        return ToolResult(
            name=self.name,
            content="Opened WhatsApp Web in the default browser.",
            is_error=False,
            safety_level=self.safety_level,
            metadata=outcome.evidence,
        )
