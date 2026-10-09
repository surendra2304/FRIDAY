"""WhatsApp sending must pass authorization and must not fabricate a send receipt."""

import pytest

from friday.core.types import (
    AuthorizationDecision,
    AuthorizationResponse,
    SafetyLevel,
)
from friday.tools.builtin.whatsapp_tools import SendWhatsAppMessageTool
from friday.tools.registry import ToolRegistry


def test_whatsapp_send_is_sensitive_and_blocked_without_capability(monkeypatch):
    opened_urls = []

    def _record(url):
        # The tool now goes through open_url_verified so that the browser's own
        # answer decides the reply; recording here pins what was *attempted*.
        opened_urls.append(url)
        from friday.core.effects import EffectOutcome

        return EffectOutcome(True, f"Opened {url} in the default browser.", {"url": url})

    monkeypatch.setattr("friday.tools.builtin.whatsapp_tools.open_url_verified", _record)
    registry = ToolRegistry()
    tool = SendWhatsAppMessageTool()
    registry.register(tool)

    result = registry.execute(
        tool.name,
        {"recipient": "+15555550123", "message": "This must not be sent by this test."},
        tool_call_id="whatsapp-auth-regression",
    )

    assert tool.safety_level is SafetyLevel.SENSITIVE
    assert result.is_error
    assert result.safety_level is SafetyLevel.SENSITIVE
    assert "requires a valid ToolAuthorizationCapability" in result.content
    assert opened_urls == []


def test_opening_whatsapp_compose_does_not_claim_the_message_was_dispatched(monkeypatch):
    """An opened URL plus an unrun async worker is not a dispatch receipt."""
    from friday.devices.windows_friday import windows_friday

    class OwnerApprover:
        def authorize(self, _request):
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="approved for this offline test",
            )

    opened_urls = []
    scheduled_targets = []

    class DeferredThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            scheduled_targets.append(self.target)
            # Do not execute the Windows UI automation in this offline test.

    monkeypatch.setattr(windows_friday, "open_url", lambda url: opened_urls.append(url) or True)
    monkeypatch.setattr("threading.Thread", DeferredThread)

    handled, reply, metadata = windows_friday.handle_directive(
        "send hi to 9014603029",
        authorizer=OwnerApprover(),
    )

    assert handled is True
    assert opened_urls and "web.whatsapp.com/send/" in opened_urls[0]
    assert len(scheduled_targets) == 1
    assert metadata["receipt"]["status"] == "DISPATCH_UNCONFIRMED"
    assert metadata["compose_page_opened"] is True
    assert metadata["dispatch_confirmed"] is False
    assert metadata["dispatch_performed"] is None
    assert metadata["delivery_confirmed"] is False
    assert metadata["success"] is False
    assert "cannot confirm whether the message was dispatched" in reply.lower()


@pytest.mark.parametrize(
    ("dispatch_ok", "receipt_status"),
    [(False, "NOT_DISPATCHED"), (True, "DISPATCH_UNCONFIRMED")],
)
def test_direct_whatsapp_receipt_reports_dispatch_not_delivery(
    monkeypatch, dispatch_ok, receipt_status
):
    from friday.devices.windows_friday import windows_friday

    class OwnerApprover:
        def authorize(self, request):
            assert request.tool_name == "send_whatsapp_message"
            assert request.safety_level is SafetyLevel.SENSITIVE
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="approved for this offline test",
            )

    monkeypatch.setattr(
        windows_friday,
        "open_whatsapp",
        lambda **_kwargs: (dispatch_ok, "offline dispatch result"),
    )
    handled, reply, metadata = windows_friday.handle_directive(
        "send hello to +919876543210 on whatsapp",
        authorizer=OwnerApprover(),
    )

    assert handled is True
    assert metadata["success"] is False
    assert metadata["compose_page_opened"] is dispatch_ok
    assert metadata["dispatch_performed"] is (None if dispatch_ok else False)
    assert metadata["dispatch_confirmed"] is False
    assert metadata["delivery_confirmed"] is False
    assert metadata["receipt"]["status"] == receipt_status
    assert metadata["receipt"]["status"] != "SENT"
    if dispatch_ok:
        assert "opened the compose page" in reply
        assert "cannot confirm whether the message was dispatched" in reply.lower()
    else:
        assert "No message dispatch was confirmed" in reply
    assert "confirmed" in reply.lower()
