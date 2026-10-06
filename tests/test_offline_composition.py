"""FRIDAY's offline library of known work, and the claims it makes about itself.

Two things are being tested here, and the second matters more than the first.

The first is that each intent in `friday.cognition.composition` does what it says.
That is checked by iterating the library rather than listing it, so a new intent is
covered the moment it is added — and its example is run in a fresh interpreter, the
same way the smoke test runs it, because code that behaves inside the test process
can behave differently in the one that installs it.

The second is that the checks have teeth. A self-test written by the same author as
the body is only worth something if a wrong body actually fails it, so one test
deliberately corrupts a composition and asserts the failure is caught, named, and
kept out of the candidate. A library of intent checks that never fails anything
would be decoration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from friday.cognition import capability as capability_module
from friday.cognition import composition as composition_module
from friday.cognition.capability import CapabilityResolver, ToolSynthesiser
from friday.cognition.composition import (
    COMPOSITIONS,
    FORBIDDEN_IN_BODY,
    Composition,
    compose,
    intent_for,
)

TOOL_TEMPLATE = capability_module.TOOL_TEMPLATE


class NoModel:
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


def _source_for(composition: Composition, tool_name: str = "probe_capability") -> str:
    """The real template, filled the way the synthesiser fills it."""
    return TOOL_TEMPLATE.format(
        title=composition.intent,
        request="a test asked for it",
        class_name="ProbeCapabilityTool",
        tool_name=tool_name,
        summary=composition.summary,
        safety="SENSITIVE",
        auth="USER",
        body=composition.body,
        provenance=capability_module._provenance_line(
            f"local_composition:{composition.intent}", capability_module.AuthoredBody(
                body=composition.body, authorship=f"local_composition:{composition.intent}"
            )
        ),
    )


# ── every intent, exercised for real ──────────────────────────────────────────


def test_the_library_is_not_empty_and_every_entry_is_named() -> None:
    assert len(COMPOSITIONS) >= 10
    intents = [item.intent for item in COMPOSITIONS]
    assert len(intents) == len(set(intents)), "two intents share a name"
    for item in COMPOSITIONS:
        assert item.patterns, f"{item.intent} can never match"
        assert item.body.strip(), f"{item.intent} has an empty body"
        assert item.summary.strip()


@pytest.mark.parametrize("composition", COMPOSITIONS, ids=lambda item: item.intent)
def test_each_intent_does_what_its_own_example_says(composition: Composition, tmp_path: Path) -> None:
    """Run the stated example against the candidate in a fresh interpreter."""
    source = _source_for(composition)
    candidate = tmp_path / f"{composition.intent}.py"
    candidate.write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ToolSynthesiser._SMOKE_DRIVER,
            str(candidate),
            f"probe_{composition.intent}",
            "probe_capability",
            json.dumps(composition.self_test),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    verdict = json.loads(completed.stdout.strip().splitlines()[-1])

    assert verdict["ok"] is True, verdict
    assert "behaves_as_specified" in verdict["checks"], verdict


@pytest.mark.parametrize("composition", COMPOSITIONS, ids=lambda item: item.intent)
def test_each_intent_is_a_pure_function_of_its_input(composition: Composition) -> None:
    """No composed body may reach for a file, a process or the network."""
    for name in FORBIDDEN_IN_BODY:
        assert name not in composition.body, f"{composition.intent} mentions {name!r}"
    example = composition.self_test
    assert example["input"] != "" and example["expect"] != "", example
    assert example["intent"] == composition.intent, example


@pytest.mark.parametrize("composition", COMPOSITIONS, ids=lambda item: item.intent)
def test_each_intent_returns_a_result_for_the_structural_smoke_input(composition: Composition) -> None:
    """The unconfigured call the smoke test always makes must not raise."""
    from friday.core.types import SafetyLevel, ToolResult

    namespace: dict[str, object] = {"ToolResult": ToolResult}
    exec("def execute(self, input: str = '', **_) -> ToolResult:\n" + composition.body, namespace)

    class Stub:
        name = "probe_capability"
        safety_level = SafetyLevel.SENSITIVE

    result = namespace["execute"](Stub(), input="smoke test")  # type: ignore[operator]
    assert isinstance(result, ToolResult)


# ── the boundary: no intent means no composition, never a guess ───────────────


@pytest.mark.parametrize(
    "ask",
    [
        "translate document french",
        "sort files date",          # sorting files is not sorting lines of text
        "reverse files list",       # reversing a list of paths is not reversing text
        "trim video clip",          # trimming a video is not trimming whitespace
        "resize image avatar",
        "deploy service production",
        "",
    ],
)
def test_work_outside_the_library_composes_nothing(ask: str) -> None:
    """The library answers for what it knows and stays silent about the rest."""
    assert compose(ask) is None


@pytest.mark.parametrize(
    "capability,expected",
    [
        ("count words note paste", "count_words"),
        ("count lines text", "count_lines"),
        ("reverse text note", "reverse_text"),
        ("sum numbers text", "sum_numbers"),
        ("average numbers text", "average_numbers"),
        ("format json text", "format_json"),
        ("capitalize each word", "title_case"),
        ("convert uppercase", "upper_case"),
        ("remove duplicate lines", "unique_lines"),
        ("trim whitespace note", "trim_whitespace"),
        ("sort lines note", "sort_lines"),
    ],
)
def test_the_obvious_phrasings_reach_their_intent(capability: str, expected: str) -> None:
    composition = compose(capability)
    assert composition is not None, f"nothing composed for {capability!r}"
    assert composition.intent == expected


def test_a_body_that_mentions_a_forbidden_name_is_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The purity rule is enforced at compose time, not trusted as a promise."""
    poisoned = Composition(
        intent="poisoned_probe",
        patterns=(r"\bpoisoned\b",),
        example_input="x",
        expect="x",
        body="        import subprocess\n        subprocess.run(['true'])\n        return None",
        summary="deliberately unsafe, for the test only",
    )
    monkeypatch.setattr(composition_module, "COMPOSITIONS", (*COMPOSITIONS, poisoned))

    assert intent_for("poisoned probe") is poisoned, "the fixture did not take effect"
    assert compose("poisoned probe") is None, "an unsafe body was composed anyway"


# ── the self-test has teeth ───────────────────────────────────────────────────


def test_a_body_that_does_not_match_its_stated_example_is_caught(tmp_path: Path) -> None:
    """Corrupt a composition and watch the check fail. Green here means it can fail."""
    broken = Composition(
        intent="count_words",
        patterns=(r"\bcount\b.*\bwords?\b",),
        example_input="one two three",
        expect="3",
        body=(
            "        return ToolResult(\n"
            "            name=self.name,\n"
            '            content="4",\n'
            "            is_error=False,\n"
            "            safety_level=self.safety_level,\n"
            "        )"
        ),
        summary="right shape, wrong answer",
    )
    candidate = tmp_path / "wrong.py"
    candidate.write_text(_source_for(broken), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ToolSynthesiser._SMOKE_DRIVER,
            str(candidate),
            "probe_wrong",
            "probe_capability",
            json.dumps(broken.self_test),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    verdict = json.loads(completed.stdout.strip().splitlines()[-1])

    assert verdict["ok"] is False, verdict
    assert "behaves_as_specified" not in verdict["checks"]
    assert "the author's own example failed" in verdict["detail"], verdict
    assert "'3'" in verdict["detail"] and "'4'" in verdict["detail"], verdict


def test_an_erroring_body_is_caught_by_the_example_too(tmp_path: Path) -> None:
    """A tool that fails honestly on the stated example is still a failure to install."""
    broken = Composition(
        intent="count_words",
        patterns=(r"\bcount\b.*\bwords?\b",),
        example_input="one two three",
        expect="3",
        body=(
            "        return ToolResult(\n"
            "            name=self.name,\n"
            '            content="I could not do that.",\n'
            "            is_error=True,\n"
            "            safety_level=self.safety_level,\n"
            "        )"
        ),
        summary="honest, and not the work that was asked for",
    )
    candidate = tmp_path / "errors.py"
    candidate.write_text(_source_for(broken), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ToolSynthesiser._SMOKE_DRIVER,
            str(candidate),
            "probe_errors",
            "probe_capability",
            json.dumps(broken.self_test),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    verdict = json.loads(completed.stdout.strip().splitlines()[-1])

    assert verdict["ok"] is False, verdict
    assert "reported an error" in verdict["detail"], verdict


# ── the whole chain, offline ─────────────────────────────────────────────────


def test_the_resolver_builds_working_code_not_a_scaffold(repo: Path) -> None:
    """"count the words in a note" must produce a tool that counts words.

    Before this library existed the same request produced a registered stub that
    reported its own incompleteness: the pipeline was real and the work was not done.
    """
    result = CapabilityResolver(llm=NoModel(), repository_root=repo).resolve(
        "count the words in a note I paste in"
    )

    assert result.plan_source == "intent"
    item = result.synthesised[0]
    assert item["authorship"] == "local_composition:count_words", item
    assert item["self_test"] == {"input": "one two three", "expect": "3", "intent": "count_words"}
    assert "behaves_as_specified" in item["checks"], item["checks"]

    # The candidate is real code: run it on a note that is not the example.
    source = item["source"]
    namespace: dict[str, object] = {}
    from friday.core.types import SafetyLevel, ToolResult

    namespace["ToolResult"] = ToolResult
    body = source.split("def execute(self, input: str = \"\", **_: Any) -> ToolResult:", 1)[1]
    exec("def execute(self, input: str = '', **_) -> ToolResult:" + body, namespace)

    class Stub:
        name = "count_words_note_paste"
        safety_level = SafetyLevel.SENSITIVE

    answer = namespace["execute"](Stub(), input="the quick brown fox jumps")  # type: ignore[operator]
    assert answer.is_error is False
    assert answer.content == "5", answer.content

    spoken = result.spoken_summary()
    assert "I could not break that request into steps" not in spoken
    # No reviewer here, so it must stop at the gate and say so - not claim an install.
    assert item["installation"]["outcome"] == "AWAITING_REVIEWER", item["installation"]


def test_an_unreachable_model_no_longer_means_a_scaffold_for_known_work(repo: Path) -> None:
    """The same request with the model unreachable and the model absent must agree."""
    resolver = CapabilityResolver(llm=NoModel(), repository_root=repo)
    first = resolver.resolve("reverse the text in my note")
    item = first.synthesised[0]

    assert item["authorship"].startswith("local_composition:"), item["authorship"]
    assert item["self_test"], "a composed candidate must carry the claim it was checked against"
    assert "behaves_as_specified" in item["checks"], item["checks"]


def test_an_unknown_capability_still_produces_the_honest_scaffold(repo: Path) -> None:
    """The library must not turn every request into a confident-looking tool."""
    result = CapabilityResolver(llm=NoModel(), repository_root=repo).resolve(
        "resize the image avatar"
    )

    item = result.synthesised[0]
    assert item["authorship"] == "scaffold", item["authorship"]
    assert item["self_test"] is None
    assert "behaves_as_specified" not in item["checks"], item["checks"]
    source = item["source"]
    assert "not finished" in source
    assert "scaffold" in source


def test_a_model_that_answers_with_nonsense_does_not_stop_known_work(repo: Path) -> None:
    """A model that returns prose instead of code must not be the last word.

    This is the realistic failure, not a hypothetical one: asked for a method body, a
    model answers with a paragraph, or with the plan it already gave. The candidate
    then fails its smoke test. If the task is one the library knows, the library gets
    the job, and the discarded attempt is reported rather than hidden.
    """
    from friday.core.types import Message, Role

    class NonsenseProvider:
        def generate(self, messages: list[Message], **_: object) -> Message:
            return Message(
                role=Role.ASSISTANT,
                content="Sure! Here is how I would count the words in a note: I would split it.",
            )

    synthesiser = ToolSynthesiser(repo, llm=NonsenseProvider())
    from friday.cognition.capability import CapabilityGap

    outcome = synthesiser.synthesise(
        CapabilityGap(capability="count the words in a note", rationale="no tool does this"),
        request="count the words in a note I paste in",
    )

    assert outcome["verified"] is True, outcome["detail"]
    assert outcome["authorship"] == "local_composition:count_words", outcome["authorship"]
    assert "behaves_as_specified" in outcome["checks"], outcome["checks"]
    assert outcome["fallback_note"], "the discarded model attempt was not reported"
    assert "discarded" in outcome["fallback_note"]
    assert "count words" in outcome["body"] if "body" in outcome else True
    assert "str(len(input.split()))" in outcome["source"], "the library body did not land"


def test_nonsense_from_a_model_still_stops_work_nobody_can_do(repo: Path) -> None:
    """The other half of that rule, and the protection it must not erode.

    When the model's answer does not work and the library does not know the task,
    nothing is written and the failure is reported exactly as it was.
    """
    from friday.core.types import Message, Role

    class NonsenseProvider:
        def generate(self, messages: list[Message], **_: object) -> Message:
            return Message(role=Role.ASSISTANT, content="def execute(:\n    not python at all")

    from friday.cognition.capability import CapabilityGap

    synthesiser = ToolSynthesiser(repo, llm=NonsenseProvider())
    outcome = synthesiser.synthesise(
        CapabilityGap(capability="teleport the laptop", rationale="x"),
        request="teleport my laptop to the office",
    )

    assert outcome["verified"] is False
    assert "does not parse" in outcome["detail"], outcome["detail"]
    assert not (repo / outcome["path"]).exists(), "a failed candidate reached the tree"
    assert not outcome.get("fallback_note"), outcome.get("fallback_note")
