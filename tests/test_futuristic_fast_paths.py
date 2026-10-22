"""Futuristic fast-path tests: volume, battery, and screen description commands."""


from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory


def _make_agent() -> FridayAgent:
    settings = Settings(env="testing", llm_provider="mock", embedding_provider="none")
    return FridayAgent(settings=settings, llm_provider=MockLLMProvider(model=settings.llm_model),
                       memory=InMemoryConversationMemory())


class FakeEndpoint:
    """Records pycaw endpoint calls; simulates scalar master volume."""

    def __init__(self, scalar: float = 0.40):
        self.scalar = scalar
        self.calls: list = []

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.scalar

    def SetMasterVolumeLevelScalar(self, value: float, ctx) -> None:
        self.calls.append(("set", value))
        self.scalar = value


def test_volume_up_fast_path(monkeypatch):
    fake = FakeEndpoint(0.40)
    monkeypatch.setattr("friday.tools.builtin.os_control._get_endpoint_volume", lambda: fake)

    agent = _make_agent()
    response = agent.process_message("increase volume")

    assert response.metadata["fast_path"] is True
    assert response.metadata["direct_desktop_action"] == "volume_up"
    assert "50%" in response.content  # 40% + default step 10%
    assert fake.calls == [("set", 0.5)]


def test_volume_down_custom_step(monkeypatch):
    fake = FakeEndpoint(0.55)
    monkeypatch.setattr("friday.tools.builtin.os_control._get_endpoint_volume", lambda: fake)

    agent = _make_agent()
    response = agent.process_message("lower volume by 15 percent")

    assert response.metadata["direct_desktop_action"] == "volume_down"
    assert "40%" in response.content
    assert fake.calls == [("set", 0.40)]


def test_set_volume_absolute_and_clamp(monkeypatch):
    fake = FakeEndpoint(0.20)
    monkeypatch.setattr("friday.tools.builtin.os_control._get_endpoint_volume", lambda: fake)

    agent = _make_agent()
    response = agent.process_message("set volume to 150")
    assert response.metadata["direct_desktop_action"] == "set_volume"
    assert "100%" in response.content
    assert fake.calls == [("set", 1.0)]


def test_volume_already_at_level_noop(monkeypatch):
    fake = FakeEndpoint(0.50)
    monkeypatch.setattr("friday.tools.builtin.os_control._get_endpoint_volume", lambda: fake)

    agent = _make_agent()
    response = agent.process_message("volume 50")

    assert "already at 50%" in response.content
    assert fake.calls == []  # no redundant setter call


def test_mute_delegates_to_manage_volume_tool(monkeypatch):
    calls = []

    class FakeTool:
        def execute(self, action="", level=None, **kwargs):
            calls.append(action)
            return ToolResult(name="manage_volume", content="Volume muted.",
                              is_error=False, safety_level=__import__(
                                  "friday.core.types", fromlist=["SafetyLevel"]).SafetyLevel.SAFE)

    from friday.tools.builtin import os_control
    monkeypatch.setattr(os_control, "ManageVolumeTool", FakeTool)

    agent = _make_agent()
    response = agent.process_message("mute the volume")

    assert calls == ["mute"]
    assert "muted" in response.content.lower()
    assert response.metadata["success"] is True


def test_mute_tool_error_marks_failure(monkeypatch):
    class FailingTool:
        def execute(self, action="", level=None, **kwargs):
            return ToolResult(name="manage_volume", content="Volume control unavailable",
                              is_error=True,
                              safety_level=__import__("friday.core.types",
                                                      fromlist=["SafetyLevel"]).SafetyLevel.SAFE)

    from friday.tools.builtin import os_control
    monkeypatch.setattr(os_control, "ManageVolumeTool", FailingTool)

    agent = _make_agent()
    response = agent.process_message("unmute")

    assert response.metadata["success"] is False
    assert "could not complete" in response.content.lower()


def test_battery_status_read_only():
    agent = _make_agent()
    status = agent._read_battery_status()

    assert isinstance(status, str)
    assert len(status) > 5
    # Either a real percentage report or an honest no-battery message.
    assert ("battery" in status.lower())


def test_battery_fast_path_routing():
    agent = _make_agent()
    for phrase in ("what is my battery level", "battery status", "how much battery do i have?"):
        assert agent._BATTERY_PATTERN.match(phrase), phrase
    # Must NOT hijack unrelated sentences containing 'battery'.
    assert not agent._BATTERY_PATTERN.match("recommend a battery charger near me")


def test_screen_describe_extracts_summary(monkeypatch):
    def fake_execute(self, display="primary", query=None, **kwargs):
        return ToolResult(
            name="get_screen_snapshot",
            content=("Screen Snapshot (1920x1080, Display: primary):\n"
                     "A code editor with the FRIDAY project open."),
            is_error=False,
            safety_level=__import__("friday.core.types", fromlist=["SafetyLevel"]).SafetyLevel.SAFE,
        )

    import friday.tools.builtin.screen_snapshot as ss
    monkeypatch.setattr(ss.ScreenSnapshotTool, "execute", fake_execute)

    agent = _make_agent()
    response = agent.process_message("what's on my screen?")

    assert response.metadata["direct_desktop_action"] == "screen_describe"
    assert response.content == "A code editor with the FRIDAY project open."


def test_screen_describe_graceful_failure(monkeypatch):
    def failing_execute(self, display="primary", query=None, **kwargs):
        raise RuntimeError("Vision provider not configured")

    import friday.tools.builtin.screen_snapshot as ss
    monkeypatch.setattr(ss.ScreenSnapshotTool, "execute", failing_execute)

    agent = _make_agent()
    response = agent.process_message("describe my screen")

    assert response.metadata["success"] is False
    assert "could not complete" in response.content.lower()


def test_fast_paths_do_not_hijack_unrelated_requests(monkeypatch):
    """Unrelated sentences must fall through to normal pipeline (mock LLM echo)."""
    fake = FakeEndpoint(0.40)
    monkeypatch.setattr("friday.tools.builtin.os_control._get_endpoint_volume", lambda: fake)

    agent = _make_agent()
    for phrase in ("screen recording software", "increase the font size",
                   "mute notifications from whatsapp", "battery charger shop"):
        response = agent.process_message(phrase)
        assert response.metadata.get("fast_path") is not True, phrase
