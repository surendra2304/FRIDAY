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


# Desktop directives require an authorizer now; these tests cover the
# directive mechanics, so they opt in to an approving one.
pytestmark = pytest.mark.usefixtures("approve_directives")


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

    @pytest.mark.windows
    @pytest.mark.hardware
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

    def test_youtube_search_does_not_claim_playback(self, monkeypatch) -> None:
        """Verify explicit YouTube search does not select a result or claim playback."""
        opened = []
        monkeypatch.setattr(windows_friday, "open_url", lambda url: opened.append(url) or True)
        ok, message = windows_friday.play_youtube("Star Boy")
        assert ok is True
        assert opened == ["https://www.youtube.com/results?search_query=Star+Boy"]
        assert "No video was selected or played" in message

    @pytest.mark.windows
    @pytest.mark.hardware
    def test_powershell_execution(self) -> None:
        """Verify arbitrary PowerShell command execution."""
        h, reply, meta = windows_friday.handle_directive("powershell Write-Output 'FRIDAY_OK'")
        assert h is True
        assert "FRIDAY_OK" in reply
        assert meta["action"] == "powershell"

    @pytest.mark.windows
    @pytest.mark.hardware
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
        assert windows_friday.can_handle("play Star Boy on youtube") is False
        assert windows_friday.can_handle("play something on Spotify") is False
        assert windows_friday.is_whatsapp_directive("mute notifications from whatsapp") is False
        assert windows_friday.is_whatsapp_directive("mute notifications in whatsapp") is False
        assert windows_friday.is_whatsapp_directive("send hi to ramesh in whatsapp") is True
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

    def test_contact_management_and_whatsapp_dispatch(self, approve_directives) -> None:
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
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url, mock.patch("threading.Thread"):
            ok, reply, meta = windows_friday.handle_directive(
                "send hi to ramesh in whatsapp",
                authorizer=approve_directives,
            )
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            mock_url.assert_called_once()
            url = mock_url.call_args[0][0]
            assert "phone=919876543210" in url
            assert "text=hi" in url

        # 4. WhatsApp dispatch to 10-digit number directly
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url, mock.patch("threading.Thread"):
            ok, reply, meta = windows_friday.handle_directive(
                "send hello to 9876543210 on whatsapp",
                authorizer=approve_directives,
            )
            assert ok is True
            url = mock_url.call_args[0][0]
            assert "phone=919876543210" in url

        # 5. Delete contact
        ok, reply, meta = windows_friday.handle_directive("delete contact ramesh")
        assert ok is True
        assert meta["action"] == "delete_contact"

    def test_phone_number_whatsapp_directives(self, approve_directives) -> None:
        """Verify direct phone number commands (send <msg> to <phone>, text <phone> <msg>) route to WhatsApp."""
        from unittest import mock

        # 1. 'send hi to 9014603029' (no 'whatsapp' keyword in command)
        assert windows_friday.is_whatsapp_directive("send hi to 9014603029") is True
        assert windows_friday.can_handle("send hi to 9014603029") is True

        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url, mock.patch("threading.Thread"):
            ok, reply, meta = windows_friday.handle_directive(
                "send hi to 9014603029",
                authorizer=approve_directives,
            )
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            assert meta["message"] == "hi"
            mock_url.assert_called_once()
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hi" in url

        # 2. 'send hello to +919014603029'
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url, mock.patch("threading.Thread"):
            ok, reply, meta = windows_friday.handle_directive(
                "send hello to +919014603029",
                authorizer=approve_directives,
            )
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hello" in url

        # 3. 'text 9014603029 hi'
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url, mock.patch("threading.Thread"):
            ok, reply, meta = windows_friday.handle_directive(
                "text 9014603029 hi",
                authorizer=approve_directives,
            )
            assert ok is True
            assert meta["action"] == "open_whatsapp"
            url = mock_url.call_args[0][0]
            assert "phone=919014603029" in url
            assert "text=hi" in url

    def test_open_gmail_opens_inbox_without_a_recipient(self, monkeypatch) -> None:
        """Opening the inbox is not a send request and must not demand a recipient."""
        opened_urls = []
        monkeypatch.setattr(windows_friday, "open_url", lambda url: opened_urls.append(url) or True)

        handled, reply, meta = windows_friday.handle_directive("open gmail")

        assert handled is True
        assert opened_urls == ["https://mail.google.com/"]
        assert meta["action"] == "open_gmail"
        assert meta["success"] is True
        assert "recipient" not in meta
        assert "Gmail in the default browser" in reply

    def test_compose_email_never_sends_through_smtp(self, approve_directives, monkeypatch) -> None:
        """A draft request must not be turned into an automatic SMTP send."""
        from types import SimpleNamespace
        from unittest import mock

        from friday.tools.builtin import email_tools

        class EmailCredentials:
            email_address = "fixture@example.com"
            email_app_password = "fixture-password"

        monkeypatch.setattr("friday.core.config.get_settings", lambda: EmailCredentials())
        send_attempts = []
        opened_urls = []

        def recorded_send(**kwargs):
            send_attempts.append(kwargs)
            return SimpleNamespace(sent=True, refused=False, detail="local SMTP accepted")

        monkeypatch.setattr(email_tools, "_send_smtp_email", recorded_send)
        monkeypatch.setattr(
            windows_friday,
            "open_url",
            lambda url: opened_urls.append(url) or True,
        )

        handled, reply, metadata = windows_friday.handle_directive(
            "compose email to test@example.com about Meeting",
            authorizer=approve_directives,
        )

        assert handled is True
        assert send_attempts == []
        assert len(opened_urls) == 1
        assert "to=test%40example.com" in opened_urls[0]
        assert "su=Meeting" in opened_urls[0]
        assert metadata["action"] == "compose_email"
        assert metadata["success"] is True
        assert metadata["draft_opened"] is True
        assert metadata["sent"] is False
        assert "not sent" in reply.lower()

    def test_compose_email_named_contact_resolves_the_actual_name(self, approve_directives, monkeypatch) -> None:
        """The word 'to' is a preposition here, not the contact name."""
        lookups = []
        opened_urls = []

        def find_contact(name):
            lookups.append(name)
            return {"alice": "alice@example.com"}.get(name.lower())

        monkeypatch.setattr(windows_friday, "_lookup_contact_email", find_contact)
        monkeypatch.setattr(
            windows_friday,
            "open_url",
            lambda url: opened_urls.append(url) or True,
        )

        handled, _reply, metadata = windows_friday.handle_directive(
            "compose email to Alice about Meeting",
            authorizer=approve_directives,
        )

        assert handled is True
        assert lookups == ["Alice"]
        assert metadata["recipient_name"] == "Alice"
        assert metadata["to"] == "alice@example.com"
        assert "to=alice%40example.com" in opened_urls[0]

    def test_explicit_send_to_named_contact_still_resolves_after_draft_split(
        self, approve_directives, monkeypatch
    ) -> None:
        from types import SimpleNamespace

        lookups = []
        sends = []
        monkeypatch.setattr(
            windows_friday,
            "_lookup_contact_email",
            lambda name: lookups.append(name) or "alice@example.com",
        )
        monkeypatch.setattr(
            windows_friday,
            "open_gmail",
            lambda **kwargs: sends.append(kwargs)
            or SimpleNamespace(
                sent=False,
                detail="offline send result is unconfirmed",
                provider="offline_fixture",
            ),
        )

        handled, _reply, metadata = windows_friday.handle_directive(
            "send email to Alice about Meeting",
            authorizer=approve_directives,
        )

        assert handled is True
        assert lookups == ["Alice"]
        assert sends == [{"to": "alice@example.com", "subject": "Meeting", "body": ""}]
        assert metadata["action"] == "open_gmail"
        assert metadata["direct_action"] == "send_email"
        assert metadata["to"] == "alice@example.com"
        assert metadata["success"] is False

    def test_compose_email_unknown_contact_does_not_open_a_blank_draft(
        self, approve_directives, monkeypatch
    ) -> None:
        """An unresolved named recipient must not silently disappear from a draft."""
        lookups = []
        opened_urls = []
        monkeypatch.setattr(
            windows_friday,
            "_lookup_contact_email",
            lambda name: lookups.append(name) or None,
        )
        monkeypatch.setattr(
            windows_friday,
            "open_url",
            lambda url: opened_urls.append(url) or True,
        )

        handled, reply, metadata = windows_friday.handle_directive(
            "compose email to Bob about Meeting",
            authorizer=approve_directives,
        )

        assert handled is True
        assert lookups == ["Bob"]
        assert opened_urls == []
        assert metadata["action"] == "compose_email"
        assert metadata["success"] is False
        assert metadata["draft_opened"] is False
        assert metadata["sent"] is False
        assert metadata["direct_action"] == "compose_email"
        assert "do not have an email address for bob" in reply.lower()
        assert "did not open the draft" in reply.lower()

    def test_draft_subject_without_recipient_is_not_parsed_as_a_contact(
        self, approve_directives, monkeypatch
    ) -> None:
        opened_urls = []
        lookups = []
        monkeypatch.setattr(
            windows_friday,
            "_lookup_contact_email",
            lambda name: lookups.append(name) or None,
        )
        monkeypatch.setattr(
            windows_friday,
            "open_url",
            lambda url: opened_urls.append(url) or True,
        )

        handled, _reply, metadata = windows_friday.handle_directive(
            "draft email about Meeting",
            authorizer=approve_directives,
        )

        assert handled is True
        assert lookups == []
        assert metadata["recipient_name"] is None
        assert metadata["subject"] == "Meeting"
        assert len(opened_urls) == 1
        assert "su=Meeting" in opened_urls[0]

    @pytest.mark.parametrize(
        "command",
        [
            "compose email",
            "draft email",
            "write an email",
            "new email",
            "please draft an email",
        ],
    )
    def test_email_draft_only_phrasings_open_a_draft_without_sending(
        self, approve_directives, monkeypatch, command
    ) -> None:
        """Each supported draft phrasing is user-facing, authorized, and non-sending."""
        from friday.tools.builtin import email_tools

        class EmailCredentials:
            email_address = "fixture@example.com"
            email_app_password = "fixture-password"

        monkeypatch.setattr("friday.core.config.get_settings", lambda: EmailCredentials())
        send_attempts = []
        opened_urls = []

        def forbidden_send(**kwargs):
            send_attempts.append(kwargs)
            raise AssertionError("a draft-only request reached the SMTP send function")

        monkeypatch.setattr(email_tools, "_send_smtp_email", forbidden_send)
        monkeypatch.setattr(
            windows_friday,
            "open_url",
            lambda url: opened_urls.append(url) or True,
        )

        handled, reply, metadata = windows_friday.handle_directive(
            command,
            authorizer=approve_directives,
        )

        assert handled is True
        assert metadata["action"] == "compose_email"
        assert metadata["success"] is True
        assert metadata["sent"] is False
        assert send_attempts == []
        assert opened_urls == ["https://mail.google.com/mail/?view=cm&fs=1"]
        assert "draft was not sent" in reply.lower()

    def test_gmail_directives(self, approve_directives, monkeypatch) -> None:
        """Verify Gmail directives are routed with local, non-sending stand-ins."""
        from unittest import mock

        class NoEmailCredentials:
            email_address = None
            email_app_password = None

        monkeypatch.setattr("friday.core.config.get_settings", lambda: NoEmailCredentials())

        assert windows_friday.is_gmail_directive("open gmail") is True
        assert windows_friday.is_gmail_directive("compose email") is True
        assert windows_friday.is_gmail_directive("send email to test@gmail.com with subject Hi") is True
        assert windows_friday.can_handle("open gmail") is True
        assert windows_friday.can_handle("send email to test@gmail.com") is True

        # Compose with subject and body
        with mock.patch.object(windows_friday, "open_url", return_value=True) as mock_url:
            ok, reply, meta = windows_friday.handle_directive(
                "send email to test@gmail.com with subject Meeting and body Hello team",
                authorizer=approve_directives,
            )
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
