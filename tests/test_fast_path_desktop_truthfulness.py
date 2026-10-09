"""The desktop shortcuts must not claim work they did not do.

``_direct_desktop_action_fast_path`` answers "open notepad and type X" and
"search Y in Chrome" without a model, which is the point of a shortcut. Two
things went wrong inside it, and both were invisible because the *shape* of the
response was perfect:

* ``_launch_process`` returned ``None`` and swallowed every failure, so the
  Chrome branch's ``ok = True`` could not be falsified - its ``except``
  fallback was dead code, and "search google for python asyncio in chrome"
  answered **"Done."** on a machine with no Chrome installed, every time.
* Typing into a window is a SENSITIVE action in the tool registry (``type_text``
  asks the authorizer for a capability), and the shortcut synthesized the same
  keystrokes with no authorization at all. The same user intent was checked or
  unchecked depending only on whether the phrasing matched a pattern.
"""

from __future__ import annotations

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import AuthorizationDecision, AuthorizationResponse
from friday.llm.mock_provider import MockLLMProvider


class RecordingDenier:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def authorize(self, request: object) -> AuthorizationResponse:
        self.requests.append(request)
        return AuthorizationResponse(decision=AuthorizationDecision.DENIED, reason="test: withheld")


class RecordingApprover:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def authorize(self, request: object) -> AuthorizationResponse:
        self.requests.append(request)
        return AuthorizationResponse(decision=AuthorizationDecision.APPROVED, reason="test: approved")


def _agent(authorizer):
    return FridayAgent(
        settings=Settings(env="testing", llm_provider="mock", embedding_provider="none"),
        authorizer=authorizer,
    )


# --------------------------------------------------------------------- notepad
def test_notepad_says_nothing_was_typed_when_notepad_cannot_start(monkeypatch):
    agent = _agent(RecordingApprover())
    monkeypatch.setattr(agent, "_launch_process", lambda *args: False)

    response = agent.process_message("open notepad and type hello world")

    assert "could not start Notepad" in response.content
    assert "I opened Notepad" not in response.content
    assert response.metadata["success"] is False


def test_notepad_does_not_type_when_the_authorizer_withholds_approval(monkeypatch):
    typed: list[str] = []

    class Driver:
        def type_text(self, text):
            typed.append(text)
            return True

    denier = RecordingDenier()
    agent = _agent(denier)
    monkeypatch.setattr(agent, "_launch_process", lambda *args: True)
    monkeypatch.setattr(agent, "_focus_window_for_direct_action", lambda title: True)
    monkeypatch.setattr("friday.agent.mixins.fast_paths.WindowsNativeInputDriver", Driver)

    response = agent.process_message("open notepad and type I am Friday")

    assert typed == [], "text was typed into a window without authorization"
    assert "did not type" in response.content
    assert denier.requests, "the authorizer was never asked"
    request = denier.requests[0]
    assert getattr(request, "tool_name", "") == "type_text"
    assert response.metadata["success"] is False


def test_notepad_types_when_the_launch_worked_and_typing_is_approved(monkeypatch):
    typed: list[str] = []

    class Driver:
        def type_text(self, text):
            typed.append(text)
            return True

    approver = RecordingApprover()
    agent = _agent(approver)
    monkeypatch.setattr(agent, "_launch_process", lambda *args: True)
    monkeypatch.setattr(agent, "_focus_window_for_direct_action", lambda title: True)
    monkeypatch.setattr("friday.agent.mixins.fast_paths.WindowsNativeInputDriver", Driver)

    response = agent.process_message("open notepad and type I am Friday")

    assert typed == ["I am Friday"]
    assert response.content == "Done."
    assert approver.requests


# ---------------------------------------------------------------------- chrome
def test_failed_camera_launch_is_a_terminal_directive_not_llm_fallback(monkeypatch):
    from friday.core.effects import EffectOutcome

    agent = _agent(RecordingApprover())

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError("a recognized failed desktop action reached the LLM")

    monkeypatch.setattr(agent.llm, "generate", provider_must_not_run)
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda _command, **_kwargs: EffectOutcome(
            False,
            "start command was not found",
            {"returncode": 127},
        ),
    )

    response = agent.process_message("open camera")

    assert response.metadata["direct_desktop_action"] == "launch_app"
    assert response.metadata["success"] is False
    assert response.is_done is True
    assert "Could not open Camera" in response.content


def test_chrome_search_does_not_answer_done_when_chrome_is_missing(monkeypatch):
    """The regression that motivated this file: 'Done.' with no browser."""
    approver = RecordingApprover()
    agent = _agent(approver)
    launched: list[tuple] = []

    def missing(*args):
        launched.append(args)
        return False

    monkeypatch.setattr(agent, "_launch_process", missing)

    response = agent.process_message("search google for python asyncio in chrome")

    assert response.content != "Done."
    assert "could not run the Chrome search" in response.content
    assert "Nothing was searched" in response.content
    assert response.metadata["success"] is False
    assert launched, "the shortcut did not even try to launch Chrome"


def test_chrome_search_refuses_and_explains_when_typing_is_not_authorized(monkeypatch):
    denier = RecordingDenier()
    agent = _agent(denier)
    monkeypatch.setattr(agent, "_launch_process", lambda *args: False)

    response = agent.process_message("search for telugu songs in chrome")

    assert "did not open Chrome" in response.content
    assert "withheld" in response.content
    assert response.metadata["refused"] is True
    assert denier.requests and getattr(denier.requests[0], "tool_name", "") == "type_text"


def test_chrome_search_answers_done_when_the_launch_really_happened(monkeypatch):
    agent = _agent(RecordingApprover())
    monkeypatch.setattr(agent, "_launch_process", lambda *args: True)

    response = agent.process_message("search best laptops in chrome")

    assert response.content == "Done."
    assert response.metadata["success"] is True


# ------------------------------------------------------------ query extraction
def test_engine_words_are_not_part_of_the_search_query():
    """'search google for X in chrome' searched for 'google for X'."""
    agent = _agent(RecordingApprover())
    agent._launch_process = lambda *args: True

    for phrasing, expected in (
        ("search google for python asyncio in chrome", "python asyncio"),
        ("search for telugu songs in chrome", "telugu songs"),
        ("search in chrome for weather", "weather"),
        ("chrome and search python decorators", "python decorators"),
        ("search best laptops in chrome", "best laptops"),
    ):
        response = agent.process_message(phrasing)
        assert response.metadata["query"] == expected, phrasing


def test_a_search_word_that_is_content_is_kept():
    agent = _agent(RecordingApprover())
    agent._launch_process = lambda *args: True
    response = agent.process_message("search youtube for lofi in chrome")
    assert response.metadata["query"] == "youtube for lofi"


# --------------------------------------------------- verified launch primitive
def test_launch_process_reports_failure_for_a_missing_program():
    agent = _agent(RecordingApprover())
    assert agent._launch_process("friday-program-that-does-not-exist-xyz") is False


def test_launch_process_reports_success_for_a_real_program():
    import sys

    agent = _agent(RecordingApprover())
    assert agent._launch_process(sys.executable, "-c", "import time; time.sleep(0.6)") is True
