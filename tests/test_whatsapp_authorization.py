"""WhatsApp sending must pass FRIDAY's capability authorization gate."""

from friday.core.types import SafetyLevel
from friday.tools.builtin.whatsapp_tools import SendWhatsAppMessageTool
from friday.tools.registry import ToolRegistry


def test_whatsapp_send_is_sensitive_and_blocked_without_capability(monkeypatch):
    opened_urls = []
    monkeypatch.setattr("friday.tools.builtin.whatsapp_tools.webbrowser.open", opened_urls.append)
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
