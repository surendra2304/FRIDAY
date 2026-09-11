"""Comprehensive real-system test suite for WindowsFridayController and NativeTTS.

Verifies:
1. Master Windows FRIDAY directives (YouTube, Apps, Volume, Brightness, Telemetry, PowerShell).
2. Exact percentage volume setting and step controls.
3. YouTube search and URL resolution.
4. App lifecycle: launching and terminating applications cleanly.
5. Windows SAPI Text-to-Speech synthesis.
6. System telemetry and network diagnostics.
"""

import time
import pytest
import psutil
from friday.devices.windows_friday import windows_friday
from friday.voice.native_tts import native_tts, clean_text_for_speech


class TestWindowsFridayController:
    """Test suite executing real Windows OS controller functions for FRIDAY."""

    def test_battery_and_system_specs(self) -> None:
        """Verify real hardware specs and battery status."""
        h, reply, meta = windows_friday.handle_directive("battery")
        assert h is True
        assert "Battery" in reply or "sensor not detected" in reply
        assert meta["action"] == "battery_info"

        h, reply, meta = windows_friday.handle_directive("system specs")
        assert h is True
        assert "Laptop Status:" in reply
        assert "logical cores" in reply
        assert meta["action"] == "specs"

    def test_network_status(self) -> None:
        """Verify real local IP and gateway query."""
        h, reply, meta = windows_friday.handle_directive("network status")
        assert h is True
        assert "Network:" in reply
        assert "Local IP address is" in reply
        assert meta["action"] == "network_status"

    def test_volume_percentage_control(self) -> None:
        """Verify exact volume percentage read, set, and restoration."""
        initial_vol = windows_friday.get_volume_percent() or 20

        # Set to 30%
        h, reply, meta = windows_friday.handle_directive("set volume to 30%")
        assert h is True
        assert "Volume set to" in reply
        new_vol = windows_friday.get_volume_percent()
        if new_vol is not None:
            assert abs(new_vol - 30) <= 2

        # Restore initial volume
        windows_friday.set_volume_percent(initial_vol)
        restored = windows_friday.get_volume_percent()
        if restored is not None:
            assert abs(restored - initial_vol) <= 2

    def test_youtube_resolution(self) -> None:
        """Verify direct YouTube watch URL retrieval."""
        url = windows_friday._get_first_youtube_video("Star Boy")
        assert url is not None
        assert "https://www.youtube.com/watch?v=" in url

    def test_powershell_execution(self) -> None:
        """Verify arbitrary PowerShell command execution."""
        h, reply, meta = windows_friday.handle_directive("powershell Write-Output 'FRIDAY_OK'")
        assert h is True
        assert "FRIDAY_OK" in reply
        assert meta["action"] == "powershell"

    def test_app_launch_and_close(self) -> None:
        """Verify launching and cleanly terminating an application."""
        # 1. Launch notepad
        h, reply, meta = windows_friday.handle_directive("open notepad")
        assert h is True
        assert "Opened" in reply or "Brought active" in reply
        # Check process exists (allow up to 3 seconds for UWP/modern Notepad to spawn)
        procs = []
        for _ in range(6):
            time.sleep(0.5)
            procs = [p.name() for p in psutil.process_iter() if "notepad" in p.name().lower()]
            if procs:
                break
        assert len(procs) > 0, "Notepad process should be running"

        # 2. Close notepad
        h, reply, meta = windows_friday.handle_directive("close notepad")
        assert h is True
        assert "Closed" in reply
        time.sleep(1.0)

        # Check process terminated
        procs_after = [p.name() for p in psutil.process_iter() if "notepad" in p.name().lower()]
        assert len(procs_after) == 0, "Notepad process should be terminated"

    def test_directive_intent_matching(self) -> None:
        """Verify natural language directive matching via can_handle."""
        assert windows_friday.can_handle("play Star Boy on youtube") is True
        assert windows_friday.can_handle("open chrome") is True
        assert windows_friday.can_handle("close notepad") is True
        assert windows_friday.can_handle("volume up") is True
        assert windows_friday.can_handle("set volume to 50%") is True
        assert windows_friday.can_handle("what apps are open") is True
        assert windows_friday.can_handle("battery") is True
        assert windows_friday.can_handle("show desktop") is True
        assert windows_friday.can_handle("lock pc") is True
        assert windows_friday.can_handle("take screenshot") is True
        assert windows_friday.can_handle("contacts") is True
        assert windows_friday.can_handle("save contact ramesh 9876543210") is True
        assert windows_friday.can_handle("ramesh is 9876543210") is True

    def test_contact_management_and_whatsapp_dispatch(self) -> None:
        """Verify contact saving, phone normalization, listing, and WhatsApp dispatch."""
        from unittest import mock

        # 1. Save contact
        ok, reply, meta = windows_friday.handle_directive("save contact ramesh 9876543210")
        assert ok is True
        assert meta["action"] == "save_contact"
        assert meta["name"] == "Ramesh"

        # 2. List contacts
        ok, reply, meta = windows_friday.handle_directive("contacts")
        assert ok is True
        assert "Ramesh" in reply
        assert "+919876543210" in reply

        # 3. Direct WhatsApp dispatch using saved contact
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("send hi to ramesh in whatsapp")
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            mock_url.assert_called_once()
            url = mock_url.call_args[0][0]
            assert "phone=919876543210" in url
            assert "text=hi" in url

        # 4. WhatsApp dispatch to 10-digit number directly
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("send hello to 9876543210 on whatsapp")
            assert ok is True
            url = mock_url.call_args[0][0]
            assert "phone=919876543210" in url

        # 5. Delete contact
        ok, reply, meta = windows_friday.handle_directive("delete contact ramesh")
        assert ok is True
        assert meta["action"] == "delete_contact"

    def test_phone_number_whatsapp_directives(self) -> None:
        """Verify direct phone number commands (send <msg> to <phone>, text <phone> <msg>) route to WhatsApp."""
        from unittest import mock

        # 1. 'send hi to 9014603029' (no 'whatsapp' keyword in command)
        assert windows_friday.is_whatsapp_directive("send hi to 9014603029") is True
        assert windows_friday.can_handle("send hi to 9014603029") is True

        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("send hi to 9014603029")
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            assert meta["message"] == "hi"
            mock_url.assert_called_once()
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hi" in url

        # 2. 'send hello to +919014603029'
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("send hello to +919014603029")
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hello" in url

        # 3. 'text 9014603029 hi'
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("text 9014603029 hi")
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hi" in url

    def test_gmail_directives(self) -> None:
        """Verify Gmail directives are recognized and routed with correct parameters."""
        from unittest import mock

        assert windows_friday.is_gmail_directive("open gmail") is True
        assert windows_friday.is_gmail_directive("compose email") is True
        assert windows_friday.is_gmail_directive("send email to test@gmail.com with subject Hi") is True
        assert windows_friday.can_handle("open gmail") is True
        assert windows_friday.can_handle("send email to test@gmail.com") is True

        # Compose with subject and body
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive("send email to test@gmail.com with subject Meeting and body Hello team")
            assert ok is True
            assert meta["action"] == "open_gmail"
            assert meta["to"] == "test@gmail.com"
            assert meta["subject"] == "Meeting"
            assert meta["body"] == "Hello team"
            mock_url.assert_called_once()
            url = mock_url.call_args[0][0]
            assert "to=test%40gmail.com" in url
            assert "su=Meeting" in url
            assert "body=Hello+team" in url

    def test_browser_hwnd_resolution(self) -> None:
        """Verify _get_active_browser_hwnd executes safely without error."""
        hwnd = windows_friday._get_active_browser_hwnd(["whatsapp", "chrome"])
        assert hwnd is None or isinstance(hwnd, int)




class TestNativeTTS:
    """Test suite for Windows Native SAPI Text-to-Speech engine."""

    def test_clean_text_for_speech(self) -> None:
        """Verify markdown, links, and code blocks are stripped before speaking."""
        raw = "Here is a **great** test: ```python\nprint('hello')\n``` and visit https://google.com!"
        cleaned = clean_text_for_speech(raw)
        assert "**" not in cleaned
        assert "print('hello')" not in cleaned
        assert "https://google.com" not in cleaned
        assert "great test" in cleaned

    def test_native_tts_speak(self) -> None:
        """Verify speech synthesis enqueuing and execution without error."""
        native_tts.speak("FRIDAY system check complete.")
        time.sleep(0.5)
        native_tts.stop()
