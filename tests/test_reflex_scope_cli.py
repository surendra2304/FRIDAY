"""The reflex CLI must preserve narrow scopes and refuse scope typos."""

from __future__ import annotations

import sys
from typing import Any

import pytest


def _run_cli(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    from friday.cli.main import main

    monkeypatch.setattr(sys, "argv", ["friday", *arguments])
    main()


@pytest.mark.parametrize("scope", ["typo", "tests,typo", ","])
def test_reflex_cli_refuses_invalid_scope_before_starting_a_pass(
    scope: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from friday.cognition import reflex

    class CountingBrain:
        calls: list[set[Any] | None] = []

        async def run_once(self, *, include: set[Any] | None = None) -> dict[str, Any]:
            self.calls.append(include)
            return {"status": "COMPLETED", "incidents": 0, "acted_on": 0, "outcomes": []}

    brain = CountingBrain()
    monkeypatch.setattr(reflex, "get_reflex_brain", lambda: brain)

    with pytest.raises(SystemExit) as exited:
        _run_cli(monkeypatch, "--reflex-run", scope)

    assert exited.value.code == 2
    assert "scope" in capsys.readouterr().out.lower()
    assert brain.calls == []


def test_reflex_cli_passes_a_valid_scope_without_widening(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from friday.cognition import reflex
    from friday.cognition.reflex import IncidentKind

    class CountingBrain:
        calls: list[set[Any] | None] = []

        async def run_once(self, *, include: set[Any] | None = None) -> dict[str, Any]:
            self.calls.append(include)
            return {"status": "COMPLETED", "incidents": 0, "acted_on": 0, "outcomes": []}

    brain = CountingBrain()
    monkeypatch.setattr(reflex, "get_reflex_brain", lambda: brain)
    _run_cli(monkeypatch, "--reflex-run", "tests")

    assert brain.calls == [{IncidentKind.TEST_FAILURE}]
    assert '"status": "COMPLETED"' in capsys.readouterr().out
