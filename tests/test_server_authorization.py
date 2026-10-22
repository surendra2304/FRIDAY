"""A server must not ask a human a question the human cannot see.

Found by driving the live API. `POST /api/chat` with a request FRIDAY could serve
locally printed this into the *server's* log:

    [AUTHORIZATION REQUEST] Safety Level: SENSITIVE
    Tool      : count_words_note
    Authorize execution? [y/N]:

and then read a stdin nobody was typing into. On a deployment where stdin stays open
that is a request thread blocked for as long as the pipe lives; here it was an
immediate EOF, reported as a refusal, which the user saw as the tool layer silently
saying no.

The rule these tests pin: an interactive authorizer may only prompt when there is a
terminal to prompt *on*. Otherwise it refuses, says why, and reads nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from friday.cli.auth import CLIAuthorizer
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
)


def _sensitive_request() -> AuthorizationRequest:
    return AuthorizationRequest(
        tool_name="count_words_note",
        safety_level=SafetyLevel.SENSITIVE,
        arguments={"input": "one two three"},
        tool_call_id="test_call",
        purpose="count some words",
    )


class _NoTerminal:
    """Like the stdin a server has: present, readable, and nobody on the other end."""

    def isatty(self) -> bool:
        return False

    def readline(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("the authorizer read stdin without a terminal")

    def __bool__(self) -> bool:
        return True


class _Terminal:
    def __init__(self, answer: str = "y\n") -> None:
        self.answer = answer
        self.reads = 0

    def isatty(self) -> bool:
        return True

    def readline(self, *args, **kwargs) -> str:
        self.reads += 1
        return self.answer


def test_without_a_terminal_the_cli_authorizer_refuses_and_says_why(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _NoTerminal())
    response = CLIAuthorizer().authorize(_sensitive_request())

    assert response.decision is AuthorizationDecision.DENIED
    assert "no interactive terminal is attached" in (response.reason or "")
    assert response.capability is None, "a refusal must not carry a capability"


def test_without_a_terminal_no_prompt_is_printed_or_read(monkeypatch, capsys) -> None:
    """The specific failure: a prompt written to a log and a read from an empty pipe."""
    monkeypatch.setattr(sys, "stdin", _NoTerminal())
    CLIAuthorizer().authorize(_sensitive_request())

    printed = capsys.readouterr().out
    assert "Authorize execution?" not in printed, printed
    assert "AUTHORIZATION REQUEST" not in printed, printed


def test_with_a_terminal_the_owner_is_still_asked(monkeypatch) -> None:
    """The interactive behaviour the CLI is for must survive the fix."""
    terminal = _Terminal("y\n")
    monkeypatch.setattr(sys, "stdin", terminal)
    response = CLIAuthorizer().authorize(_sensitive_request())

    assert terminal.reads == 1, "the owner was not asked"
    assert response.decision is AuthorizationDecision.APPROVED
    assert response.capability is not None


def test_with_a_terminal_a_no_is_still_a_no(monkeypatch) -> None:
    terminal = _Terminal("n\n")
    monkeypatch.setattr(sys, "stdin", terminal)
    response = CLIAuthorizer().authorize(_sensitive_request())

    assert response.decision is AuthorizationDecision.DENIED
    assert response.capability is None


def test_dangerous_actions_are_never_shown_as_asked_without_a_terminal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", _NoTerminal())
    request = _sensitive_request()
    request.safety_level = SafetyLevel.DANGEROUS
    response = CLIAuthorizer().authorize(request)

    assert response.decision is AuthorizationDecision.DENIED
    assert "no interactive terminal is attached" in (response.reason or "")
    assert "CONFIRM" not in capsys.readouterr().out


def test_the_api_server_does_not_build_an_interactive_authorizer(monkeypatch) -> None:
    """Read the server's own construction, with a terminal and without one."""
    import friday.api.server as server_module

    monkeypatch.setattr(CLIAuthorizer, "_has_a_terminal", staticmethod(lambda: False))
    built = server_module._build_authorizer() if hasattr(server_module, "_build_authorizer") else None
    if built is None:
        source = Path(server_module.__file__).read_text(encoding="utf-8")
        assert "CLIAuthorizer() if CLIAuthorizer._has_a_terminal() else DefaultSecureAuthorizer()" in source, (
            "the server's authorizer construction changed; make sure a headless process "
            "cannot get an interactive authorizer"
        )
    else:
        assert isinstance(built, DefaultSecureAuthorizer)

    # And the headless authorizer keeps the safety property: SENSITIVE needs consent.
    response = DefaultSecureAuthorizer().authorize(_sensitive_request())
    assert response.decision is AuthorizationDecision.DENIED


def test_an_injected_prompt_channel_is_asked_even_without_a_terminal(monkeypatch) -> None:
    """The boundary the terminal guard draws.

    A caller that installs its own prompt function — a UI, an automation harness, a
    test — is not asking this process's stdin, so the absence of a terminal does not
    speak for it. That keeps the interactive protocol reachable from a desktop shell
    while the API server, which installs nothing, still fails closed.
    """
    monkeypatch.setattr(sys, "stdin", _NoTerminal())
    asked: list[str] = []

    def fake_prompt(prompt: str) -> str:
        asked.append(prompt)
        return "y"

    monkeypatch.setattr("friday.cli.auth._prompt_user", fake_prompt)
    response = CLIAuthorizer().authorize(_sensitive_request())

    assert asked, "the injected channel was never asked"
    assert response.decision is AuthorizationDecision.APPROVED
    assert response.capability is not None
