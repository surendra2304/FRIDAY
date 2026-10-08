"""Regression tests for fast-path scope.

FRIDAY answers a lot of input without a model: greetings, the time, "open
notepad", "email Alice that ...". Those detectors match substrings, which is
what makes them tolerant of phrasing - and also what made them answer a request
that merely *contained* a recognised phrase:

    "please read the file called missing_file.txt and also tell me the current date"
        -> "Today is Wednesday, October 07, 2026."

The file was never read and nothing said so. These tests pin the rule that a
fast path may only claim a turn when the turn is a single instruction.
"""

import tempfile

import pytest

from friday.core.language import is_compound_request, second_clause

SINGLE_INSTRUCTIONS = [
    "what time is it",
    "open notepad",
    "open notepad, please",
    "increase the volume to 65%",
    "search google for python asyncio",
    "close chrome",
    "my goal",
    "read notes.txt",
    # Dots in an address or a filename are not sentence boundaries.
    "email alice@x.com that the meeting moved",
    "send the report to bob@corp.co.uk",
    "open http://localhost:3000/dashboard",
    # One action, two objects.
    "volume up and brightness up",
]

COMPOUND_REQUESTS = [
    "read missing_file.txt and also tell me the current date",
    "what time is it and also send an email to a@b.com",
    "check my disk and then summarise it",
    "open notepad. then email bob",
    "summarise the repo; send me the summary",
    "turn off wifi and also mute the volume",
]


@pytest.mark.parametrize("text", SINGLE_INSTRUCTIONS)
def test_single_instructions_are_not_compound(text):
    assert is_compound_request(text) is False, text


@pytest.mark.parametrize("text", COMPOUND_REQUESTS)
def test_compound_requests_are_detected(text):
    assert is_compound_request(text) is True, text


def test_second_clause_names_what_would_have_been_dropped():
    clause = second_clause(
        "please read the file called missing_file.txt and also tell me the current date"
    )
    assert clause is not None
    assert "current date" in clause


def test_device_layer_declines_a_compound_directive():
    """It must not claim the turn, so the agent loop can plan both parts."""
    from friday.devices.windows_friday import windows_friday

    handled, reply, meta = windows_friday.handle_directive(
        "tell me the date and also read notes.txt"
    )
    assert handled is False, f"device layer answered a compound request: {reply!r}"
    assert meta == {}


def test_device_layer_still_answers_a_single_directive():
    from friday.devices.windows_friday import windows_friday

    handled, reply, _ = windows_friday.handle_directive("what time is it")
    assert handled is True
    assert reply


def test_agent_does_not_answer_a_compound_request_from_a_fast_path(monkeypatch):
    """The end-to-end shape of the original bug."""
    import sys

    # These were `os.environ.setdefault`, which mutated the process environment
    # for every module collected afterwards: FRIDAY_ENV=testing left behind here
    # silently switched demo_mode_enabled() on for the rest of the suite and made
    # unrelated tests (FORGE's sample task, ecosystem dashboards) pass only when
    # this file happened to run first. monkeypatch scopes them to this test.
    monkeypatch.setenv("FRIDAY_ENV", "testing")
    monkeypatch.setenv("FRIDAY_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FRIDAY_EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("FRIDAY_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("FRIDAY_MEMORY_DB_PATH", tempfile.mktemp(suffix=".db"))
    monkeypatch.setenv("FRIDAY_LOG_FILE", tempfile.mktemp(suffix=".log"))
    monkeypatch.setenv("FRIDAY_LOG_LEVEL", "CRITICAL")

    from friday.agent.agent import FridayAgent
    from friday.llm.mock_provider import MockLLMProvider

    agent = FridayAgent(llm_provider=MockLLMProvider(), max_tool_iterations=2)
    response = agent.process_message(
        "please read the file called missing_file.txt and also tell me the current date"
    )
    assert not (response.metadata or {}).get("fast_path"), (
        "a fast path claimed a compound request and dropped the other half"
    )
