"""When told to do something it has never done, FRIDAY must not shrug.

The owner's requirement, in their words: *"when told to do work it has never done,
it must not say it doesn't know how — it must think like a human and execute."*

With a model reachable, planning is the model's job. Without one — this sandbox has
no egress, and a laptop on a train has none either — the honest failure mode used to
be "I could not break that request into steps", which is a shrug on a host that can
build tools. These tests pin the replacement: a request with a real action verb and
an object names a capability, that capability is planned, synthesised, verified and
handed to the gate, and the answer says exactly which step it reached.

The boundary matters as much as the capability: conversation must still get "no
plan" rather than a junk tool, and hardware the host does not have must still be
named as the blocker.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from friday.cognition import capability as capability_module
from friday.cognition.capability import (
    ACTION_VERBS,
    CapabilityResolver,
    PlanStep,
    ToolCatalogue,
)


class NoModel:
    """A provider that refuses to plan, so the offline path is what runs."""

    def generate(self, *args, **kwargs):
        raise RuntimeError("no egress from here")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src/friday/tools/builtin").mkdir(parents=True)
    (tmp_path / "README.md").write_text("# scratch\n", encoding="utf-8")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "o@example.invalid"),
        ("config", "user.name", "Owner"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True)
    return tmp_path


def _resolver(repo: Path) -> CapabilityResolver:
    return CapabilityResolver(llm=NoModel(), repository_root=repo)


@pytest.mark.parametrize(
    "ask,expected",
    [
        ("count the words in a note I paste in", "count words note paste"),
        ("please summarise this article for me", "summarise article"),
        ("convert the spreadsheet into json", "convert spreadsheet json"),
        ("transcribe the meeting notes file", "transcribe meeting notes file"),
    ],
)
def test_a_capability_request_is_planned_from_its_own_words(
    repo: Path, ask: str, expected: str
) -> None:
    steps, source = _resolver(repo).plan(ask)

    assert source == "intent", f"{ask!r} was planned by {source!r}"
    assert len(steps) == 1
    assert steps[0].tool is None, "a missing capability must not be attributed to a real tool"
    assert steps[0].available is False
    assert steps[0].intent == expected


@pytest.mark.parametrize(
    "ask",
    [
        "hello there",
        "why is the sky blue?",
        "zzzz qqqq wwww",
        "thank you",
        "count",          # a verb with no object is not a capability
        "",
    ],
)
def test_talk_is_still_not_a_plan(repo: Path, ask: str) -> None:
    """The boundary: no verb, or no object, means the honest "no plan" stands."""
    steps, source = _resolver(repo).plan(ask)
    assert steps == []
    assert source == "none"


def test_the_resolver_takes_the_request_all_the_way_to_the_gate(repo: Path) -> None:
    """Planned, synthesised, smoke-tested, and stopped by the gate, not by a shrug."""
    resolver = _resolver(repo)
    result = resolver.resolve("count the words in a note I paste in")

    assert result.gaps, "the missing capability was not identified"
    assert result.synthesised, "nothing was synthesised for the gap"
    item = result.synthesised[0]
    assert item["verified"] is True, item
    assert item["verification"] == "smoke_test"
    assert item["checks"] == [
        "syntax_valid",
        "imports_cleanly",
        "instantiates",
        "schema_valid",
        "returns_tool_result",
    ]

    # No reviewer is configured in this fixture, so installation must stop there and
    # the tree must be untouched - the candidate is a proposal, not a file.
    installation = item["installation"]
    assert installation["outcome"] == "AWAITING_REVIEWER", installation
    assert not (repo / item["path"]).exists()

    spoken = result.spoken_summary()
    assert "I could not break that request into steps" not in spoken
    assert "self-tested the missing piece" in spoken
    assert "no reviewer is configured" in spoken


def test_the_planned_capability_name_is_a_usable_tool_name(repo: Path) -> None:
    """The name must survive the journey: plan -> tool name -> Python class."""
    from friday.cognition.capability import ToolSynthesiser

    steps, _ = _resolver(repo).plan("count the words in a note I paste in")
    tool_name = ToolSynthesiser.tool_name_for(steps[0].intent)
    class_name = ToolSynthesiser.class_name_for(tool_name)

    assert tool_name == "count_words_note_paste"
    assert class_name == "CountWordsNotePasteTool"
    assert class_name.isidentifier()
    ast.parse(f"class {class_name}:\n    pass\n")


def test_a_verb_the_host_cannot_satisfy_names_what_is_missing(repo: Path) -> None:
    """Hardware the host does not have is a blocker, not a plan."""
    result = _resolver(repo).resolve("transcribe my microphone recording")

    assert result.plan_feasible is False
    gap = result.gaps[0]
    assert gap.external_requirement, "the missing hardware was not named"
    assert not result.synthesised, "a tool was built for something no tool can supply"
    assert "it needs" in result.spoken_summary()


def test_every_action_verb_is_lowercase_and_single_word() -> None:
    """The vocabulary is matched against lowercased tokens, so it must be shaped that way."""
    assert ACTION_VERBS
    for verb in ACTION_VERBS:
        assert verb.islower()
        assert " " not in verb
        assert verb.isalpha()


def test_the_planner_never_claims_a_tool_that_does_not_exist(repo: Path) -> None:
    """A synthesised step is marked unavailable, and nothing else claims otherwise."""
    result = _resolver(repo).resolve("count the words in a note I paste in")
    catalogue = ToolCatalogue().names()
    for step in result.steps:
        if step.tool is not None:
            assert step.tool in catalogue, f"{step.tool} was invented"
    assert isinstance(result.steps[0], PlanStep)
    assert result.plan_source == "intent"
    assert capability_module.ACTION_VERBS is ACTION_VERBS


# ── what a real run found: a plausible tool is worse than no tool ─────────────


def test_a_word_shared_by_many_tools_is_not_evidence(repo: Path) -> None:
    """Found by running the planner on real requests.

    "transcribe the meeting notes file" matched the keyword planner through the word
    "file", and the plan confidently named `file_operations` for a transcription job.
    A word that appears in many tool names says nothing about which one is meant; the
    old planner ignored presence-in-many-names and its tie-break was alphabetical, so
    the winner was an accident. The honest outcome is no tool at all, plus a named
    capability to build.
    """
    steps, source = _resolver(repo).plan("transcribe the meeting notes file")

    assert source == "intent", f"the planner guessed a tool again (source={source!r})"
    assert all(step.tool is None for step in steps), [step.tool for step in steps]
    assert steps[0].intent == "transcribe meeting notes file"


def test_a_tie_between_tools_is_not_a_choice(repo: Path) -> None:
    """When two tools match equally well, this planner has no opinion - and says so.

    "type the info" scores four tools identically (0.5 each) on the words "type" and
    "info", because each of those words appears in exactly two tool names. Picking
    whichever sorts first is a coin flip presented as a plan, and the request names
    no action either, so the answer is the honest "no plan".
    """
    steps, source = _resolver(repo).plan("type the info")

    assert steps == [], [step.tool for step in steps]
    assert source == "none"


def test_a_tie_is_refused_even_when_the_request_names_an_action(repo: Path) -> None:
    """A tie must not be broken by the alphabetical tie-break, even with a real verb.

    "fetch the webpage" scores `fetch_webpage` and `fetch_webpage_content` identically
    at 1.0. The plan that comes out has no tool in it, so the capability is built
    rather than an arbitrary one of the two existing tools being run against the
    owner's request.
    """
    steps, source = _resolver(repo).plan("fetch the webpage")

    assert source == "intent"
    assert steps[0].tool is None
    assert steps[0].intent == "fetch webpage"


def test_a_rare_word_is_still_evidence(repo: Path) -> None:
    """The other side of the rule: weighting must not throw away real evidence.

    "check" appears in exactly one tool name, so "check the system" really does point
    at `health_check` even though "system" appears in four. Dropping the confident
    answer here would be as wrong as inventing one above.
    """
    steps, source = _resolver(repo).plan("check the system")

    assert source == "keyword"
    assert steps[0].tool == "health_check"


def test_the_keyword_planner_still_answers_when_the_evidence_is_clear(repo: Path) -> None:
    """The tie rule must not break the case that worked: "read the tests"."""
    steps, source = _resolver(repo).plan("read the tests")

    assert source == "keyword"
    assert steps[0].tool == "run_tests"
