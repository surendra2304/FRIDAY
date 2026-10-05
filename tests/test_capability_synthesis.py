"""Tests for `friday.cognition.capability` — the never-refuse layer.

These tests run with no network. A model is injected where a plan needs one, and
everything else is exercised against the real tool catalogue and real files in
`tmp_path`. Nothing here mocks the thing under test.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

import friday.cognition.capability as capability_module
from friday.cognition.capability import (
    CapabilityGap,
    CapabilityResolver,
    PlanStep,
    ToolCatalogue,
    ToolSynthesiser,
    _external_requirement,
    _extract_json,
)
from friday.core.types import Message, Role


class NoModelProvider:
    """A model that is not there. Synthesis must fall back to an honest scaffold."""

    def generate(self, messages: list[Message], **_: Any) -> Message:
        raise RuntimeError("no model reachable in tests")


class FakeProvider:
    """A model that returns a canned plan, so planning is tested without egress."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[list[Message]] = []

    def generate(self, messages: list[Message], **_: Any) -> Message:
        self.calls.append(messages)
        return Message(role=Role.ASSISTANT, content=self.payload)


# ── the catalogue ─────────────────────────────────────────────────────────


def test_the_catalogue_lists_tools_that_actually_exist() -> None:
    catalogue = ToolCatalogue()
    names = catalogue.names()

    assert len(names) > 30, f"only found {len(names)} tools; the scan is not working"
    for expected in ("calculator", "run_tests", "read_own_codebase", "self_develop", "self_repair"):
        assert catalogue.has(expected), f"{expected} missing from the catalogue"

    # Every name must resolve to a real BaseTool subclass, not a phantom.
    from friday.tools.base import BaseTool

    for name in names:
        entry = catalogue.entries()[name]
        assert isinstance(entry, (BaseTool, type)), f"{name} is not a tool class or instance"


def test_the_catalogue_does_not_claim_tools_that_do_not_exist() -> None:
    catalogue = ToolCatalogue()
    assert not catalogue.has("quantum_teleporter")
    assert not catalogue.has("")


def test_describe_gives_the_planner_names_and_purposes() -> None:
    description = ToolCatalogue().describe()
    lines = description.splitlines()
    assert len(lines) > 30
    assert any(line.startswith("- self_develop:") for line in lines)


# ── planning ──────────────────────────────────────────────────────────────


def test_a_model_plan_using_real_tools_is_accepted_verbatim() -> None:
    provider = FakeProvider(
        '{"steps": [{"intent": "look up the weather", "tool": "get_weather", "arguments": {"city": "Vijayawada"}}]}'
    )
    resolver = CapabilityResolver(llm=provider)

    steps, source = resolver.plan("what is the weather in Vijayawada")

    assert source == "model"
    assert len(steps) == 1
    assert steps[0].tool == "get_weather"
    assert steps[0].available is True
    assert steps[0].arguments == {"city": "Vijayawada"}
    assert provider.calls, "the planner never called the model"


def test_a_plan_naming_a_tool_that_does_not_exist_becomes_a_gap_not_a_lie() -> None:
    provider = FakeProvider('{"steps": [{"intent": "teleport the laptop", "tool": "quantum_teleporter"}]}')
    resolver = CapabilityResolver(llm=provider)

    steps, _ = resolver.plan("teleport my laptop")

    assert steps[0].tool is None, "an invented tool name must never be trusted"
    assert steps[0].available is False
    assert "not a registered tool" in steps[0].note
    assert "quantum_teleporter" in steps[0].note


def test_a_model_plan_that_is_not_json_falls_through_to_keyword_matching(synthesis_repo: Path) -> None:
    provider = FakeProvider("I would be happy to help with that!")
    resolver = CapabilityResolver(llm=provider, repository_root=synthesis_repo)

    steps, source = resolver.plan("read the tests")

    assert source == "keyword"
    assert steps, "keyword matching found nothing for 'read the tests'"
    assert steps[0].available is True
    assert steps[0].tool in ToolCatalogue().names()
    assert "the model was unavailable" in steps[0].note


def test_an_unplannable_request_is_reported_as_a_gap_not_a_refusal(synthesis_repo: Path) -> None:
    resolver = CapabilityResolver(llm=FakeProvider("no json here"), repository_root=synthesis_repo)
    result = resolver.resolve("zzzz qqqq wwww", allow_synthesis=False)

    assert result.plan_feasible is False
    assert result.plan_source == "none"
    spoken = result.spoken_summary()
    assert "could not break that request into steps" in spoken
    assert "planning gap, not a refusal" in spoken
    assert "I can't" not in spoken and "cannot do that" not in spoken


# ── honest refusals about hardware and credentials ────────────────────────


@pytest.mark.parametrize(
    ("request_text", "requirement"),
    [
        ("record my voice on the microphone", "a microphone"),
        ("take a photo of my desk with the camera", "a camera"),
        ("print this page on the printer", "a printer"),
        ("send an sms to my brother", "an SMS gateway credential"),
    ],
)
def test_requests_needing_hardware_name_what_is_missing(request_text: str, requirement: str) -> None:
    assert _external_requirement(request_text) == requirement


def test_an_external_requirement_is_not_synthesised_into_a_fake_tool() -> None:
    """A missing microphone is not a missing program; building code would be a lie."""
    gap = CapabilityGap(capability="listen to the room", rationale="x", external_requirement="a microphone")
    outcome = ToolSynthesiser(Path("/nonexistent")).synthesise(gap)

    assert outcome["verified"] is False
    assert outcome["verification"] == "not_attempted"
    assert outcome["blocked_by"] == "a microphone"
    assert outcome["tool"] is None


# ── synthesis ─────────────────────────────────────────────────────────────


@pytest.fixture()
def synthesis_repo(tmp_path: Path) -> Path:
    (tmp_path / "src/friday/tools/builtin").mkdir(parents=True)
    return tmp_path


def test_a_missing_capability_becomes_a_real_verified_tool(synthesis_repo: Path) -> None:
    synthesiser = ToolSynthesiser(synthesis_repo, llm=NoModelProvider())
    gap = CapabilityGap(capability="count the words in a note", rationale="no tool does this")

    outcome = synthesiser.synthesise(gap, request="count the words in my note")

    assert outcome["verified"] is True
    assert outcome["verification"] == "smoke_test"
    assert outcome["tool"] == "count_words_in_note"
    assert outcome["checks"] == [
        "syntax_valid",
        "imports_cleanly",
        "instantiates",
        "schema_valid",
        "returns_tool_result",
    ]

    written = synthesis_repo / outcome["path"]
    assert written.exists(), "the synthesiser claimed a tool it never wrote"
    source = written.read_text(encoding="utf-8")
    ast.parse(source)  # a real, parseable module
    assert "class CountWordsInNoteTool(BaseTool)" in source
    assert "safety_level = SafetyLevel.SENSITIVE" in source
    assert 'auth_requirement = "USER"' in source


def test_a_synthesised_tool_is_smoke_tested_for_real(synthesis_repo: Path) -> None:
    synthesiser = ToolSynthesiser(synthesis_repo, llm=NoModelProvider())
    gap = CapabilityGap(capability="rename a batch of files", rationale="no tool does this")

    outcome = synthesiser.synthesise(gap)
    module_path = synthesis_repo / outcome["path"]

    import importlib.util

    spec = importlib.util.spec_from_file_location("synthesised_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["synthesised_under_test"] = module
    try:
        spec.loader.exec_module(module)
        tool = next(
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and obj.__name__.endswith("Tool")
            and obj.__module__ == "synthesised_under_test"
        )
        from friday.core.types import ToolResult

        result = tool().execute(input="smoke test")
        assert isinstance(result, ToolResult)
        # The scaffold must not pretend to have done the work.
        assert result.is_error is True
        assert "not finished" in result.content
    finally:
        sys.modules.pop("synthesised_under_test", None)


def test_synthesis_refuses_to_overwrite_a_tool_that_already_exists(synthesis_repo: Path) -> None:
    target = synthesis_repo / "src/friday/tools/builtin/weather.py"
    target.write_text("# the real weather tool\n", encoding="utf-8")

    outcome = ToolSynthesiser(synthesis_repo, llm=NoModelProvider()).synthesise(
        CapabilityGap(capability="weather", rationale="x"),
        target_path="src/friday/tools/builtin/weather.py",
    )

    assert outcome["verification"] == "already_exists"
    assert target.read_text(encoding="utf-8") == "# the real weather tool\n"


def test_a_tool_that_cannot_parse_is_never_written(synthesis_repo: Path) -> None:
    synthesiser = ToolSynthesiser(synthesis_repo, llm=NoModelProvider())
    gap = CapabilityGap(capability="break everything", rationale="x")

    # Force the model to author mangled code.
    class BadProvider:
        def generate(self, messages: list[Message], **_: Any) -> Message:
            return Message(role=Role.ASSISTANT, content="def execute(:\n    this is not python")

    synthesiser._llm = BadProvider()
    outcome = synthesiser.synthesise(gap)

    assert outcome["verified"] is False
    assert outcome["verification"] == "smoke_test"
    assert "does not parse" in outcome["detail"]
    assert not (synthesis_repo / outcome["path"]).exists(), "broken code must never reach the tree"


def test_synthesis_writes_nothing_when_the_tool_raises_on_its_smoke_call(synthesis_repo: Path) -> None:
    class RudeProvider:
        def generate(self, messages: list[Message], **_: Any) -> Message:
            return Message(
                role=Role.ASSISTANT,
                content="raise RuntimeError('I refuse to be smoke tested')\n",
            )

    synthesiser = ToolSynthesiser(synthesis_repo, llm=RudeProvider())
    outcome = synthesiser.synthesise(CapabilityGap(capability="explode", rationale="x"))

    assert outcome["verified"] is False
    assert "RuntimeError" in outcome["detail"], outcome["detail"]
    assert not (synthesis_repo / outcome["path"]).exists()


# ── the end-to-end resolution ─────────────────────────────────────────────


def test_a_request_with_a_real_plan_is_feasible_without_synthesis(synthesis_repo: Path) -> None:
    provider = FakeProvider('{"steps": [{"intent": "check the time", "tool": "get_time_date"}]}')
    resolver = CapabilityResolver(llm=provider, repository_root=synthesis_repo)

    result = resolver.resolve("what time is it")

    assert result.plan_feasible is True
    assert result.gaps == []
    assert result.plan_source == "model"
    assert "can run now" in result.spoken_summary()


def test_a_request_needing_a_new_tool_is_synthesised_and_reported_as_such(
    synthesis_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider(
        '{"steps": [{"intent": "transcribe a podcast episode", "tool": "transcribe_audio"}]}'
    )
    monkeypatch.setattr(capability_module, "TOOLS_DIRECTORY", "src/friday/tools/builtin")
    resolver = CapabilityResolver(llm=provider, repository_root=synthesis_repo)

    result = resolver.resolve("transcribe this audio file for me")

    assert len(result.gaps) == 1
    assert result.synthesised and result.synthesised[0]["verified"] is True
    assert result.synthesised[0]["verification"] == "smoke_test"
    assert (synthesis_repo / result.synthesised[0]["path"]).exists()
    spoken = result.spoken_summary()
    assert "I built the missing piece" in spoken
    assert "needs building" in spoken


def test_the_resolution_is_json_safe(synthesis_repo: Path) -> None:
    """The tool result metadata crosses the API boundary, so it must serialise."""
    import json

    provider = FakeProvider('{"steps": [{"intent": "check the time", "tool": "get_time_date"}]}')
    resolver = CapabilityResolver(llm=provider, repository_root=synthesis_repo)
    payload = resolver.resolve("what time is it").as_dict()

    json.dumps(payload)  # raises if anything exotic leaked into the payload
    assert payload["steps"][0]["tool"] == "get_time_date"


# ── the JSON extractor ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        '{"steps": []}',
        'Sure! Here is the plan:\n```json\n{"steps": [{"intent": "a", "tool": null}]}\n```\nHope that helps.',
        'prefix {"steps": [{"intent": "a"}]} suffix',
    ],
)
def test_plans_are_extracted_from_however_the_model_frames_them(text: str) -> None:
    payload = _extract_json(text)
    assert isinstance(payload, dict)
    assert "steps" in payload


def test_a_missing_json_object_is_reported_as_missing() -> None:
    assert _extract_json("no plan at all") is None
    assert _extract_json("") is None


def test_plan_step_serialises_cleanly() -> None:
    step = PlanStep(intent="x", tool="time_date", arguments={"a": 1}, available=True, note="")
    assert step.as_dict()["tool"] == "time_date"


@pytest.fixture(autouse=True)
def _never_write_into_the_real_repository() -> Any:
    """The capability layer writes code. These tests must never write *ours*.

    A synthesised tool landing in the live repository during a test run would be
    worse than a failing test: it would be an unattended change to FRIDAY's own
    source. Every test below passes a `tmp_path` root; this fixture proves it.
    """
    import friday.cognition.capability as module

    builtin_dir = Path(module._repository_root()) / module.TOOLS_DIRECTORY
    before = sorted(builtin_dir.glob("*.py"))
    yield
    after = sorted(builtin_dir.glob("*.py"))
    assert after == before, (
        "a capability test wrote into the live tool directory: "
        f"{[p.name for p in set(after) - set(before)]}"
    )
