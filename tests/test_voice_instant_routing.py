"""Instant voice-command routing tests.

Verifies the local-first hybrid voice architecture:
1. classify_instant_command() routes device-control utterances to deterministic
   local execution and leaves pure conversation alone.
2. On turn completion, instant commands are executed locally and the verified
   result is sent back to the Live model for speaking. The model's own
   audio ("Working.") is NOT interrupted (no spk.stop()).
3. Conversational turns are NOT re-processed by the local agent (no duplicated
   work, no mid-sentence speaker cutoff).
4. Typed CLI input is routed through the local agent for instant commands.
"""

import asyncio
from unittest import mock

import pytest

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.voice.audio_io import MockSpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


def _make_agent() -> FridayAgent:
    settings = Settings(env="testing", llm_provider="mock", embedding_provider="none")
    return FridayAgent(
        settings=settings,
        llm_provider=MockLLMProvider(model=settings.llm_model),
        memory=InMemoryConversationMemory(),
    )


class TestClassifyInstantCommand:
    def test_time_volume_battery_screen_route_locally(self):
        agent = _make_agent()
        assert agent.classify_instant_command("what time is it") == "time"
        assert agent.classify_instant_command("increase volume") == "volume_up"
        assert agent.classify_instant_command("volume 40") == "set_volume"
        assert agent.classify_instant_command("mute") == "volume_mute"
        assert agent.classify_instant_command("what is my battery level") == "battery_status"
        assert agent.classify_instant_command("whats on my screen") == "screen_describe"

    def test_desktop_actions_route_locally(self):
        agent = _make_agent()
        assert agent.classify_instant_command("open notepad and type hello world") == "notepad_type"
        assert agent.classify_instant_command("search telugu movies in chrome") == "chrome_search"
        assert agent.classify_instant_command("close chrome") == "close_chrome"
        assert agent.classify_instant_command("open settings") in ("open_settings", "semantic_ui")
        assert agent.classify_instant_command("open calculator") in ("semantic_ui", None)
        assert agent.classify_instant_command("move mouse cursor to center of screen") == "deterministic"

    def test_conversation_does_not_route_locally(self):
        agent = _make_agent()
        for phrase in (
            "how are you today?",
            "save a note about deployment",
            "tell me a joke",
            "what is the capital of France?",
            "",
            "your voice breaking in the middle",
            "step",
            "is",
        ):
            assert agent.classify_instant_command(phrase) is None, phrase


class _MsgTx:
    def __init__(self, text):
        self.text = text


class MockGenAIServerMessage:
    def __init__(self, server_content=None):
        self.server_content = server_content


class OneMsgSession:
    """Yields a single server_content message then stops."""

    def __init__(self, user_text, agent_text="Working.", interrupted=False):
        self._user_text = user_text
        self._agent_text = agent_text
        self._interrupted = interrupted
        self._yielded = False

    async def receive(self):
        if not self._yielded:
            self._yielded = True
            server_content = mock.MagicMock(
                turn_complete=True,
                input_transcription=_MsgTx(self._user_text),
                output_transcription=_MsgTx(self._agent_text),
                interrupted=self._interrupted,
                model_turn=None,
            )
            yield MockGenAIServerMessage(server_content=server_content)


class _MultiMsgSession:
    """Yields multiple server_content messages for multi-fragment tests."""

    def __init__(self, messages):
        self._messages = list(messages)
        self._idx = 0

    async def receive(self):
        while self._idx < len(self._messages):
            msg = self._messages[self._idx]
            self._idx += 1
            yield MockGenAIServerMessage(server_content=msg)


class TestTypedInputRouting:
    @pytest.mark.anyio
    async def test_instant_typed_input_executes_locally(self):
        agent = _make_agent()
        agent.process_message = mock.MagicMock(
            return_value=mock.MagicMock(content="Volume raised from 50% to 60%.")
        )
        session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
        session._active = True
        session._session = mock.MagicMock()  # fake Live session
        session._session.send_realtime_input = mock.AsyncMock()

        result = await session.process_typed_input("increase volume")

        agent.process_message.assert_called_once_with("increase volume")
        assert result == "Volume raised from 50% to 60%."
        # Result sent to Live model for speaking
        session._session.send_realtime_input.assert_called_once()
        sent_text = session._session.send_realtime_input.call_args.kwargs.get("text", "")
        assert "Volume raised from 50% to 60%." in sent_text

    @pytest.mark.anyio
    async def test_conversational_typed_input_goes_to_live(self):
        agent = _make_agent()
        agent.process_message = mock.MagicMock()
        session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
        session._active = True
        session._session = mock.MagicMock()
        session._session.send_realtime_input = mock.AsyncMock()

        result = await session.process_typed_input("tell me about black holes")

        agent.process_message.assert_not_called()
        assert result == ""  # no local result for conversational input
        session._session.send_realtime_input.assert_called_once_with(text="tell me about black holes")

    @pytest.mark.anyio
    async def test_empty_typed_input_returns_empty(self):
        session = GeminiLiveVoiceSession(api_key="TEST_KEY")
        result = await session.process_typed_input("")
        assert result == ""


@pytest.mark.anyio
async def test_instant_command_executes_locally_and_sends_result():
    agent = _make_agent()
    agent.process_message = mock.MagicMock(
        return_value=mock.MagicMock(content="It is 3:30 PM.")
    )
    session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
    session._active = True
    session._session = mock.MagicMock()
    session._session.send_realtime_input = mock.AsyncMock()

    spk = MockSpeakerStream()
    turns = []
    await session._audio_receiver_loop(
        OneMsgSession(user_text="what time is it", agent_text="Working."),
        spk,
        lambda u, a: turns.append((u, a)),
        asyncio.Event(),
    )

    agent.process_message.assert_called_once_with("what time is it")
    # Result sent back to Live model for speaking
    session._session.send_realtime_input.assert_called_once()
    sent_text = session._session.send_realtime_input.call_args.kwargs.get("text", "")
    assert "It is 3:30 PM." in sent_text
    assert turns == [("what time is it", "It is 3:30 PM.")]


@pytest.mark.anyio
async def test_instant_command_does_not_stop_speaker():
    """Model audio (e.g. 'Working.') should NOT be purged for instant commands."""
    agent = _make_agent()
    agent.process_message = mock.MagicMock(
        return_value=mock.MagicMock(content="Volume raised to 60%.")
    )
    session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
    session._active = True
    session._session = mock.MagicMock()
    session._session.send_realtime_input = mock.AsyncMock()

    spk = MockSpeakerStream()
    stop_calls = []
    mock.patch.object(spk, "stop", side_effect=lambda: stop_calls.append(1)).start()

    await session._audio_receiver_loop(
        OneMsgSession(user_text="increase volume", agent_text="Working."),
        spk,
        lambda u, a: None,
        asyncio.Event(),
    )

    # Speaker must NOT be stopped — model audio drains naturally
    assert stop_calls == [], "spk.stop() must NOT be called for instant commands"
    agent.process_message.assert_called_once()


@pytest.mark.anyio
async def test_conversational_turn_skips_local_reprocessing():
    agent = _make_agent()
    agent.process_message = mock.MagicMock()
    session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
    session._active = True
    session._session = mock.MagicMock()
    session._session.send_realtime_input = mock.AsyncMock()

    spk = MockSpeakerStream()
    turns = []
    await session._audio_receiver_loop(
        OneMsgSession(user_text="tell me about black holes", agent_text="Black holes are regions of spacetime."),
        spk,
        lambda u, a: turns.append((u, a)),
        asyncio.Event(),
    )

    agent.process_message.assert_not_called()
    assert turns == [("tell me about black holes", "Black holes are regions of spacetime.")]


@pytest.mark.anyio
async def test_interrupted_turn_clears_transcript_accum():
    """Wake-word fragments cleared on interruption don't bleed into next turn."""
    agent = _make_agent()
    session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
    session._active = True
    session._session = mock.MagicMock()
    session._session.send_realtime_input = mock.AsyncMock()

    # Turn 1: partial transcript then interrupted
    partial_server = mock.MagicMock(
        turn_complete=False,
        input_transcription=_MsgTx("step"),
        output_transcription=None,
        interrupted=False,
        model_turn=None,
    )
    interrupt_server = mock.MagicMock(
        turn_complete=False,
        input_transcription=None,
        output_transcription=None,
        interrupted=True,
        model_turn=None,
    )
    # Turn 2: real command
    real_server = mock.MagicMock(
        turn_complete=True,
        input_transcription=_MsgTx("what time is it"),
        output_transcription=_MsgTx("It is 3:30 PM."),
        interrupted=False,
        model_turn=None,
    )

    spk = MockSpeakerStream()
    turns = []

    class ThreeMsgSession:
        def __init__(self):
            self._messages = [
                partial_server,
                interrupt_server,
                real_server,
            ]
            self._idx = 0

        async def receive(self):
            while self._idx < len(self._messages):
                yield MockGenAIServerMessage(server_content=self._messages[self._idx])
                self._idx += 1

    await session._audio_receiver_loop(
        ThreeMsgSession(),
        spk,
        lambda u, a: turns.append((u, a)),
        asyncio.Event(),
    )

    # The "step" fragment was cleared by interruption; only the real command committed
    assert len(turns) == 1
    assert turns[0][0] == "what time is it"


@pytest.mark.anyio
async def test_interrupted_turn_does_not_commit_to_memory():
    """Interrupted turns should not be committed to conversation memory."""
    agent = _make_agent()
    session = GeminiLiveVoiceSession(api_key="TEST_KEY", agent=agent)
    session._active = True
    session._session = mock.MagicMock()
    session._session.send_realtime_input = mock.AsyncMock()

    # Turn 1: user speaks, then interrupted
    partial_server = mock.MagicMock(
        turn_complete=False,
        input_transcription=_MsgTx("hello"),
        output_transcription=None,
        interrupted=False,
        model_turn=None,
    )
    interrupt_server = mock.MagicMock(
        turn_complete=False,
        input_transcription=None,
        output_transcription=None,
        interrupted=True,
        model_turn=None,
    )

    spk = MockSpeakerStream()

    class TwoMsgSession:
        def __init__(self):
            self._messages = [partial_server, interrupt_server]
            self._idx = 0

        async def receive(self):
            while self._idx < len(self._messages):
                yield MockGenAIServerMessage(server_content=self._messages[self._idx])
                self._idx += 1

    # Don't trigger turn_complete — no memory commit should happen
    # The partial "hello" should be cleared by the interruption
    turns = []
    await session._audio_receiver_loop(
        TwoMsgSession(),
        spk,
        lambda u, a: turns.append((u, a)),
        asyncio.Event(),
    )

    assert turns == [], "interrupted turn must not produce a turn callback"
