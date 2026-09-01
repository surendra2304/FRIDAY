"""Tests: type_text tool, jitter buffer, shared transcript printer, CLI stdin wiring."""

import asyncio
import io
from types import SimpleNamespace

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


def test_printer_suppresses_empty_untranscribed_turn(capsys):
    from friday.voice.transcripts import LiveTranscriptPrinter

    p = LiveTranscriptPrinter()
    p.on_server_content(_sc(turn_complete=True))
    p.on_turn_complete("", "")

    out = capsys.readouterr().out
    assert "(untranscribed)" not in out
    assert "You:" not in out
    assert "FRIDAY:" not in out


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


def test_cli_exposes_action_audit_command():
    import inspect

    from friday.cli.main import main as cli_main
    from friday.cli.main import print_action_audit

    source = inspect.getsource(cli_main)
    audit_source = inspect.getsource(print_action_audit)
    assert "--action-audit" in source
    assert "print_action_audit(audit_agent)" in source
    assert "chrome_search" in audit_source
    assert "open_windows_update" in audit_source


@pytest.mark.anyio
async def test_stdin_listener_sends_text_to_session():
    """Simulate the CLI stdin thread: a typed line is scheduled onto the loop."""
    loop = asyncio.get_event_loop()
    sent = []

    class FakeSession:
        async def send_text(self, text):
            sent.append(text)


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

    assert GROQ_UNIVERSAL_FALLBACK_MODEL == "openai/gpt-oss-120b"


# ---------------------------------------------------------------------------
# close_application tool
# ---------------------------------------------------------------------------


class _FakeWin:
    def __init__(self, title):
        self._t = title
        self.closed = False

    def window_text(self):
        return self._t

    def close(self):
        self.closed = True


def test_close_application_finds_and_closes(monkeypatch):
    from friday.tools.builtin import close_application as ca

    notepad = _FakeWin("Untitled - Notepad")
    monkeypatch.setattr(ca, "_find_window", lambda t: notepad if "notepad" == t else None)
    result = ca.CloseApplicationTool().execute(window_title="notepad")
    assert result.is_error is False
    assert result.content == "Closed notepad."
    assert notepad.closed is True


def test_close_application_not_found():
    from friday.tools.builtin.close_application import CloseApplicationTool

    result = CloseApplicationTool().execute(window_title="Nonexistent")
    assert result.is_error is True
    assert "No open window" in result.content


def test_close_application_empty_title():
    from friday.tools.builtin.close_application import CloseApplicationTool

    result = CloseApplicationTool().execute(window_title="  ")
    assert result.is_error is True


def test_close_application_registered_and_declared():
    from friday.agent.agent import FridayAgent
    from friday.core.config import Settings
    from friday.llm.mock_provider import MockLLMProvider
    from friday.memory.in_memory import InMemoryConversationMemory
    from friday.voice.gemini_live_session import GeminiLiveVoiceSession

    agent = FridayAgent(
        settings=Settings(env="testing", llm_provider="mock"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
    )
    names = {s.get("function", s).get("name") for s in agent.tools.get_schemas()}
    assert "close_application" in names
    session = GeminiLiveVoiceSession(api_key="TEST", agent=agent)
    assert session._build_tools_config() is None


def test_console_logging_error_only_by_default():
    """CLI default console level is ERROR; voice suppresses provider noise unless debug is set."""
    import inspect

    from friday.cli.main import main as cli_main

    source = inspect.getsource(cli_main)
    assert "logging.CRITICAL if voice_requested else logging.ERROR" in source


# ---------------------------------------------------------------------------
# Configuration & environment audit (Session 21)
# ---------------------------------------------------------------------------


def test_headphones_mode_disables_echo_gate_and_enables_barge_in():
    """headphones_mode=True: echo suppression must stay off, local barge-in allowed."""
    from friday.voice.gemini_live_session import GeminiLiveVoiceSession

    hp = GeminiLiveVoiceSession(api_key="T", headphones_mode=True)
    assert hp._echo_suppression is False  # gate not armed before run
    # sender-loop barge-in predicate: headphones mode allows local interruption
    assert (hp.headphones_mode or hp.local_barge_in_during_playback) is True

    spk = GeminiLiveVoiceSession(api_key="T", headphones_mode=False)
    assert (spk.headphones_mode or spk.local_barge_in_during_playback) is False


def test_env_example_documents_every_settings_field():
    from friday.core.config import Settings

    example = open(".env.example", encoding="utf-8").read()
    missing = [f"FRIDAY_{n.upper()}" for n in Settings.model_fields
               if f"FRIDAY_{n.upper()}" not in example]
    assert not missing, f"Undocumented fields in .env.example: {missing}"


def test_missing_env_vars_fall_back_to_safe_defaults(monkeypatch):
    """No .env file at all and no env vars: Settings must load every default cleanly."""
    import os

    for var in list(os.environ):
        if var.startswith("FRIDAY_"):
            monkeypatch.delenv(var, raising=False)

    from friday.core.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_provider == "gemini"  # field default (chain only in .env)
    assert s.voice_live_model == "gemini-3.1-flash-live-preview"
    assert s.voice_headphones_mode is False
    assert s.voice_enabled is False
    assert s.log_level == "INFO"
    assert s.memory_backend == "sqlite"
    assert s.groq_api_key is None and s.mistral_api_key is None


def test_cli_voice_override_message(monkeypatch, capsys):
    """--voice with FRIDAY_VOICE_ENABLED=false prints the override explanation."""
    import sys as _sys
    from unittest import mock as _mock

    monkeypatch.setattr(_sys, "argv", ["friday", "--voice"])
    monkeypatch.setenv("FRIDAY_VOICE_ENABLED", "false")

    voice_session_inst = _mock.MagicMock()
    voice_session_inst.run_live_loop = _mock.AsyncMock(return_value=None)
    mock_cls = _mock.MagicMock(return_value=voice_session_inst)

    from friday.cli.main import main

    with _mock.patch(
        "friday.auth.credential_pool.GeminiCredentialPool.preflight_check",
        return_value={"status": "HEALTHY", "active_project": "PRIMARY"},
    ), _mock.patch("friday.voice.gemini_live_session.GeminiLiveVoiceSession", mock_cls):
        main()

    out = capsys.readouterr().out
    assert "Voice mode enabled via CLI override" in out


# ---------------------------------------------------------------------------
# Voice biometrics (speaker recognition)
# ---------------------------------------------------------------------------


class _FakeEncoder:
    """Deterministic encoder: embeddings derived from a controllable 'voice id'."""

    def __init__(self):
        self.voice_id = 0.0  # tests set this to simulate different speakers

    def embed_utterance(self, wav):
        import numpy as np

        base = np.zeros(256, dtype=np.float32)
        base[0] = 1.0
        base[1] = self.voice_id
        return base


def _fake_pcm(seconds: float = 2.0, amp: int = 8000) -> bytes:
    import numpy as np

    n = int(16000 * seconds)
    samples = (np.ones(n) * amp).astype(np.int16)
    return samples.tobytes()


def test_enroll_and_verify_matching_voice(tmp_path, monkeypatch):
    from friday.security import voice_biometrics as vb

    enc = _FakeEncoder()
    monkeypatch.setattr(vb, "_get_encoder", lambda: enc)

    profile = tmp_path / "voice_profile.npy"
    mgr = vb.VoiceProfileManager(profile_path=profile)

    assert mgr.is_enrolled() is False
    assert mgr.verify_speaker(b"\x01" * 3200) is True  # unenrolled -> allow all

    assert mgr.enroll_from_frames([_fake_pcm(3.0)], sample_rate=16000) is True
    assert profile.is_file()
    assert mgr.is_enrolled() is True

    # Same voice (voice_id unchanged) -> cosine similarity 1.0 -> verified
    assert mgr.verify_speaker(_fake_pcm(2.0)) is True
    assert mgr.similarity(_fake_pcm(2.0)) >= 0.99


def test_verify_rejects_different_speaker(tmp_path, monkeypatch):
    from friday.security import voice_biometrics as vb

    enc = _FakeEncoder()
    monkeypatch.setattr(vb, "_get_encoder", lambda: enc)
    mgr = vb.VoiceProfileManager(profile_path=tmp_path / "p.npy")
    mgr.enroll_from_frames([_fake_pcm(3.0)])

    enc.voice_id = 5.0  # different speaker -> embedding rotated away
    sim = mgr.similarity(_fake_pcm(2.0))
    assert sim < 0.75, sim
    assert mgr.verify_speaker(_fake_pcm(2.0)) is False


def test_threshold_is_075(tmp_path, monkeypatch):
    from friday.security import voice_biometrics as vb

    assert vb.SIMILARITY_THRESHOLD == 0.75
    enc = _FakeEncoder()
    monkeypatch.setattr(vb, "_get_encoder", lambda: enc)
    mgr = vb.VoiceProfileManager(profile_path=tmp_path / "p.npy")
    mgr.enroll_from_frames([_fake_pcm(3.0)])
    enc.voice_id = 1.0  # cosine ~ 1/sqrt(2) = 0.707 < 0.75 -> reject
    assert mgr.verify_speaker(_fake_pcm(2.0)) is False


def test_config_toggle_and_cli_flag_wiring():
    import inspect

    from friday.cli.main import main as cli_main
    from friday.core.config import Settings

    assert Settings.model_fields["voice_biometrics_enabled"].default is False
    cli_src = inspect.getsource(cli_main)
    assert "--enroll-voice" in cli_src
    assert "enroll_voice(duration=5.0)" in cli_src
    from friday.security import voice_biometrics as vb
    vb_src = inspect.getsource(vb)
    assert "Please speak for {duration:.0f} seconds to enroll your voice" in vb_src


@pytest.mark.anyio
async def test_sender_biometrics_gate_blocks_unrecognized_voice():
    """Enrolled + enabled: failing verification drops frames with a warning."""
    import asyncio as _asyncio
    from unittest import mock as _mock

    from friday.voice.audio_io import MicrophoneStream, SpeakerStream
    from friday.voice.gemini_live_session import GeminiLiveVoiceSession

    session = GeminiLiveVoiceSession(api_key="T")
    session._active = True
    session.voice_biometrics_enabled = True

    fake_manager = _mock.MagicMock()
    fake_manager.is_enrolled.return_value = True
    fake_manager.verification_window_frames = 3
    fake_manager.verify_speaker.return_value = False  # unrecognized
    session._biometrics_manager = fake_manager

    sent = []
    mock_ws = _mock.MagicMock()
    mock_ws.send_realtime_input = _mock.AsyncMock(side_effect=lambda audio=None, **kw: sent.append(audio))

    chunk = _fake_pcm(0.04)
    feed = [chunk] * 4

    async def read_and_finish():
        if feed:
            return feed.pop(0)
        session._active = False
        return b""

    mic = _mock.MagicMock(spec=MicrophoneStream)
    mic.read_chunk = read_and_finish
    spk = _mock.MagicMock(spec=SpeakerStream)
    spk.is_playing = False
    spk.queue_size = 0

    with _mock.patch.object(
        session, "_apply_biometrics_gate", wraps=session._apply_biometrics_gate
    ):
        await session._audio_sender_loop(mock_ws, mic, spk, _asyncio.Event())

    # Design: the first window's frames are sent before the verdict lands (no
    # startup lockout); after the failing verdict every subsequent frame drops.
    payloads = [getattr(b, "data", b) for b in sent]
    assert len(payloads) == 2, f"expected only the 2 pre-verdict frames, got {len(payloads)}"
    fake_manager.verify_speaker.assert_called_once()
    verified_window = fake_manager.verify_speaker.call_args[0][0]
    assert len(verified_window) == len(chunk) * 3  # full 3-frame window


@pytest.mark.anyio
async def test_enroll_voice_is_async_and_awaits_mic(tmp_path, monkeypatch, capsys):
    """enroll_voice must be a coroutine that awaits read_chunk (regression:
    the sync version raised 'coroutine never awaited' and recorded silence)."""

    from friday.security import voice_biometrics as vb

    awaited = {"read": 0, "slept": 0}
    fake_pcm = (np_int16 := __import__("numpy").ones(16000, dtype=__import__("numpy").int16)).tobytes()
    # ~2 fake 40ms frames per loop iteration; duration consumed by monkeypatched time
    frame = (__import__("numpy").ones(640, dtype=__import__("numpy").int16)).tobytes()
    clock = {"t": 0.0}
    monkeypatch.setattr(vb.time, "time", lambda: clock["t"])

    async def fast_sleep(s):
        awaited["slept"] += 1
        clock["t"] += 0.25  # advance clock so the recording window closes

    monkeypatch.setattr(vb.asyncio, "sleep", fast_sleep)

    class FakeMic:
        def __init__(self, *a, **kw):
            pass

        def start(self, *a, **kw):
            self._active = True

        def stop(self):
            self._active = False

        @property
        def is_active(self):
            return True

        @property
        def error(self):
            return None

        async def read_chunk(self):
            awaited["read"] += 1
            clock["t"] += 0.04  # advance the mocked clock per 40ms frame
            return frame

    monkeypatch.setattr("friday.voice.audio_io.MicrophoneStream", FakeMic)

    class FakeEncoder:
        def embed_utterance(self, wav):
            import numpy as np

            return np.zeros(256, dtype=np.float32)

    monkeypatch.setattr(vb, "_get_encoder", lambda: FakeEncoder())

    import inspect

    mgr = vb.VoiceProfileManager(profile_path=tmp_path / "p.npy")
    assert inspect.iscoroutinefunction(mgr.enroll_voice), "enroll_voice must be async"

    clock["t"] = 0.0
    result = await mgr.enroll_voice(duration=5.0)
    assert result is True
    assert (tmp_path / "p.npy").is_file()
    assert awaited["read"] > 0, "read_chunk must be awaited (never a bare call)"
    assert "enroll your voice" in capsys.readouterr().out


def test_cli_voice_greeting_and_graceful_shutdown_wiring():
    """Greeting-on-connect and cancel-drain shutdown are wired in the CLI."""
    import inspect

    from friday.cli.main import main as cli_main

    src = inspect.getsource(cli_main)
    assert "Start the conversation by greeting me briefly." in src
    assert "_greet_on_connect" in src
    # Graceful shutdown: task-based run + cancel + drain + loop close
    assert "voice_task.cancel()" in src
    assert "loop.shutdown_asyncgens()" in src
    assert "loop.close()" in src


def test_session_wait_section_cancellation_safe():
    """run_live_loop drains sender/receiver tasks even when cancelled mid-wait."""
    import inspect

    from friday.voice.gemini_live_session import GeminiLiveVoiceSession

    src = inspect.getsource(GeminiLiveVoiceSession.run_live_loop)
    assert "Cancellation-safe cleanup" in src
    assert "for task in (sender_task, receiver_task):" in src
