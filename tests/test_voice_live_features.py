"""Tests: type_text tool, jitter buffer, shared transcript printer, CLI stdin wiring."""

import asyncio
import io
from types import SimpleNamespace
from unittest import mock

import pytest

from friday.tools.builtin.type_text import TypeTextTool, _escape_literal


# ---------------------------------------------------------------------------
# TypeTextTool
# ---------------------------------------------------------------------------


def test_escape_literal_wraps_special_chars():
    assert _escape_literal("hello") == "hello"
    assert _escape_literal("a+b") == "a{+}b"
    assert _escape_literal("(hi)") == "{(}hi{)}"
    assert _escape_literal("50%") == "50{%}"
    # A hotkey-like string is typed literally, never interpreted as keys
    assert _escape_literal("^c") == "{^}c"
    assert _escape_literal("{ENTER}") == "{{}ENTER{}}"  # braces escaped, not a key


def test_type_text_sends_escaped_literal(monkeypatch):
    from friday.tools.builtin import type_text as tt

    captured = {}

    def fake_send_keys(sequence, **kwargs):
        captured["sequence"] = sequence
        captured["kwargs"] = kwargs

    monkeypatch.setattr(tt, "_get_send_keys", lambda: fake_send_keys)
    tool = TypeTextTool()
    result = tool.execute(text="Hello (world) + more")
    assert result.is_error is False
    assert captured["sequence"] == "Hello {(}world{)} {+} more"
    assert captured["kwargs"]["with_spaces"] is True


def test_type_text_empty_and_unavailable(monkeypatch):
    from friday.tools.builtin import type_text as tt

    tool = TypeTextTool()
    empty = tool.execute(text="   ")
    assert empty.is_error is True

    def broken():
        raise ImportError("no pywinauto")

    monkeypatch.setattr(tt, "_get_send_keys", broken)
    unavailable = tool.execute(text="hi")
    assert unavailable.is_error is True
    assert "unavailable" in unavailable.content


def test_type_text_registered_in_default_registry():
    from friday.agent.agent import FridayAgent
    from friday.core.config import Settings
    from friday.llm.mock_provider import MockLLMProvider
    from friday.memory.in_memory import InMemoryConversationMemory

    agent = FridayAgent(
        settings=Settings(env="testing", llm_provider="mock"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
    )
    names = [s.get("function", s).get("name") for s in agent.tools.get_schemas()]
    assert "type_text" in names
    assert "open_application" in names


# ---------------------------------------------------------------------------
# LiveTranscriptPrinter (shared by CLI + diagnostic)
# ---------------------------------------------------------------------------


def _sc(input_tx=None, output_tx=None, part_text=None, turn_complete=False):
    parts = [SimpleNamespace(text=part_text, inline_data=None)] if part_text else []
    return SimpleNamespace(
        input_transcription=SimpleNamespace(text=input_tx) if input_tx else None,
        output_transcription=SimpleNamespace(text=output_tx) if output_tx else None,
        model_turn=SimpleNamespace(parts=parts) if parts else None,
        turn_complete=turn_complete,
    )


def test_printer_streams_both_sides_in_order(capsys):
    from friday.voice.transcripts import LiveTranscriptPrinter

    p = LiveTranscriptPrinter()
    p.on_server_content(_sc(input_tx="What time "))
    p.on_server_content(_sc(input_tx="is it?", turn_complete=False))
    p.on_server_content(_sc(output_tx="It is ", turn_complete=False))
    p.on_server_content(_sc(output_tx="2 PM.", turn_complete=True))
    p.on_turn_complete("What time is it?", "It is 2 PM.")

    out = capsys.readouterr().out
    assert "You: What time is it?" in out.replace("\n", "")
    assert "FRIDAY: It is 2 PM." in out.replace("\n", "")
    # No duplicate fallback lines (both sides streamed live)
    assert out.count("You:") == 1
    assert out.count("FRIDAY:") == 1


def test_printer_fallback_when_nothing_streamed(capsys):
    from friday.voice.transcripts import LiveTranscriptPrinter

    p = LiveTranscriptPrinter()
    p.on_server_content(_sc(turn_complete=True))
    p.on_turn_complete("hello", "Hi there.")

    out = capsys.readouterr().out
    assert "You: hello" in out
    assert "FRIDAY: Hi there." in out


def test_printer_model_turn_text_fallback_stream(capsys):
    from friday.voice.transcripts import LiveTranscriptPrinter

    p = LiveTranscriptPrinter()
    p.on_server_content(_sc(part_text="Speaking via parts."))
    p.on_server_content(_sc(turn_complete=True))
    p.on_turn_complete("say something", "")
    out = capsys.readouterr().out
    assert "FRIDAY: Speaking via parts." in out.replace("\n", "")


# ---------------------------------------------------------------------------
# CLI stdin listener wiring
# ---------------------------------------------------------------------------


def test_cli_voice_uses_printer_stdin_thread_and_echo_mute():
    """The CLI voice branch wires transcripts, stdin listener, and echo gating."""
    import inspect

    from friday.cli.main import main as cli_main

    source = inspect.getsource(cli_main)
    assert "LiveTranscriptPrinter" in source
    assert "_stdin_listener" in source
    assert "run_coroutine_threadsafe" in source
    assert "echo_mute=True" in source
    assert "on_server_content=printer.on_server_content" in source


@pytest.mark.anyio
async def test_stdin_listener_sends_text_to_session():
    """Simulate the CLI stdin thread: a typed line is scheduled onto the loop."""
    loop = asyncio.get_event_loop()
    sent = []

    class FakeSession:
        async def send_text(self, text):
            sent.append(text)

    import sys

    session = FakeSession()
    fake_stdin = io.StringIO("open notepad\n")

    def _listener():
        while True:
            line = fake_stdin.readline()
            if not line:
                break
            text = line.strip()
            if text:
                asyncio.run_coroutine_threadsafe(session.send_text(text), loop)

    import threading

    t = threading.Thread(target=_listener, daemon=True)
    t.start()
    t.join(timeout=5)

    await asyncio.sleep(0.05)  # let the scheduled coroutine run
    assert sent == ["open notepad"]


# ---------------------------------------------------------------------------
# type_text window focusing
# ---------------------------------------------------------------------------


def test_type_text_focuses_window_before_typing(monkeypatch):
    from friday.tools.builtin import type_text as tt

    events = []

    def fake_focus(title):
        events.append(("focus", title))
        return True

    def fake_send_keys(sequence, **kwargs):
        events.append(("type", sequence))

    monkeypatch.setattr(tt, "_focus_window", fake_focus)
    monkeypatch.setattr(tt, "_get_send_keys", lambda: fake_send_keys)

    result = tt.TypeTextTool().execute(text="hello", window_title="Notepad")
    assert result.is_error is False
    # Focus MUST happen before the keystrokes
    assert events[0] == ("focus", "Notepad")
    assert events[1][0] == "type"
    assert "window 'Notepad'" in result.content


def test_type_text_focus_failure_types_into_current_focus(monkeypatch):
    from friday.tools.builtin import type_text as tt

    events = []

    monkeypatch.setattr(tt, "_focus_window", lambda title: False)
    monkeypatch.setattr(tt, "_get_send_keys", lambda lambda_seq=None: None) if False else None

    def fake_send_keys(sequence, **kwargs):
        events.append(sequence)

    monkeypatch.setattr(tt, "_get_send_keys", lambda: fake_send_keys)
    result = tt.TypeTextTool().execute(text="hello", window_title="Missing App")
    assert result.is_error is False
    assert events, "typing still happens when focus fails (best effort)"
    assert "current focus" in result.content


def test_focus_window_matches_title_substring_and_sleeps(monkeypatch):
    from friday.tools.builtin import type_text as tt

    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    class FakeWindow:
        def __init__(self, title):
            self._t = title

        def window_text(self):
            return self._t

        def set_focus(self):
            slept.append("focus")

    import types

    fake_desktop = types.SimpleNamespace(
        windows=lambda: [FakeWindow("PowerShell"), FakeWindow("Untitled - Notepad")]
    )
    import sys

    fake_pywinauto = types.ModuleType("pywinauto")
    fake_pywinauto.Desktop = lambda backend=None: fake_desktop
    monkeypatch.setitem(sys.modules, "pywinauto", fake_pywinauto)

    assert tt._focus_window("notepad") is True
    assert slept[0] == "focus"   # set_focus called
    assert slept[1] == 0.5       # settle delay before typing


# ---------------------------------------------------------------------------
# Updated provider default models
# ---------------------------------------------------------------------------


def test_groq_universal_fallback_model_updated():
    from friday.llm.groq_provider import GROQ_UNIVERSAL_FALLBACK_MODEL

    assert GROQ_UNIVERSAL_FALLBACK_MODEL == "llama-3.1-8b-instant"


def test_cerebras_default_model_updated():
    from friday.llm.cerebras_provider import CEREBRAS_DEFAULT_MODEL

    assert CEREBRAS_DEFAULT_MODEL == "llama3.1-8b-8192"
