"""FRIDAY's own working knowledge of how to do things, with no model in the room.

A model is not always reachable — this host has no egress at all, and a laptop on a
train has none either. When the owner asks for work in that situation, the resolver
now plans it and the synthesiser builds a tool, but the body used to be a scaffold:
a registered stub that reported its own incompleteness. The pipeline was real and the
work was not done.

This module is the answer to that, and it is deliberately not a model. It is a
library of intents FRIDAY knows how to carry out — counting words, reversing text,
summing the numbers in a note — each one a small, deterministic implementation of a
task a person could do by hand without looking anything up. When a request matches an
intent, FRIDAY writes the implementation from its own knowledge and says which intent
it was. That is what "think like a human and execute" means for the class of work that
does not need anyone's judgement: knowing how, and doing it.

What a composed tool is, honestly:

* the body is real code from this repository's library, not generated text;
* every intent carries an example the author states *in advance* — this input must
  produce exactly this answer — and that example is executed against the candidate in
  a fresh interpreter before anything is installed. A body that does not behave the
  way it claims fails its own test, loudly;
* a self-test is still the author's own claim about the code. It narrows what a human
  has to read; it does not replace reading. Installed tools therefore stay SENSITIVE
  with a USER requirement until someone lowers that;
* no composed body imports anything beyond the standard parser, opens anything, or
  reaches the network. Composed bodies are pure functions of ``input``, which is also
  why it is safe to run one unsupervised in the smoke test. :func:`compose` enforces
  that by refusing to emit a body that mentions a dangerous name at all.

Nothing here guesses. An intent either matches, or the caller gets ``None`` and the
scaffold's honest "not finished" stands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


def _result(expression: str, *, indent: int = 8, error: bool = False) -> str:
    """A ``return ToolResult(...)`` block whose ``content`` is ``expression``."""
    pad = " " * indent
    return (
        f"{pad}return ToolResult(\n"
        f"{pad}    name=self.name,\n"
        f"{pad}    content={expression},\n"
        f"{pad}    is_error={error},\n"
        f"{pad}    safety_level=self.safety_level,\n"
        f"{pad})"
    )


#: Extract every number from the text. Written out rather than tucked inside each
#: body so all the numeric intents share one extraction rule.
_NUMBERS_PREAMBLE = (
    "        import re\n"
    "\n"
    "        numbers = [\n"
    '            float(token) for token in re.findall(r"-?\\d+(?:\\.\\d+)?", input)\n'
    "        ]"
)

_EMPTY_ANSWER = {
    "count_words": _result('"0"', indent=12),
    "count_lines": _result('"0"', indent=12),
    "sum_numbers": _result(
        '"There are no numbers in that text, so nothing was added."', indent=12, error=True
    ),
    "average_numbers": _result(
        '"There are no numbers in that text, so there is no average."', indent=12, error=True
    ),
}


@dataclass(frozen=True)
class Composition:
    """One thing FRIDAY knows how to do, with the example that proves it does.

    ``body`` is the indented body of ``execute(self, input: str = "", **_: Any)``.
    ``example_input`` and ``expect`` are the author's stated claim: run the tool on
    that input, and ``content`` must strip-compare equal to ``expect``, with no error.
    """

    intent: str
    patterns: tuple[str, ...]
    example_input: str
    expect: str
    body: str
    summary: str

    @property
    def self_test(self) -> dict[str, str]:
        return {"input": self.example_input, "expect": self.expect, "intent": self.intent}


#: The library. Order matters: the first intent whose pattern matches wins, so the
#: narrower ones come first. Every pattern is matched against the capability phrase
#: the planner named ("count words note paste") and, failing that, the owner's request.
COMPOSITIONS: Final[tuple[Composition, ...]] = (
    Composition(
        intent="count_words",
        patterns=(r"\bcount\b.*\bwords?\b", r"\bword\s+count\b", r"\bhow many words\b"),
        example_input="one two three",
        expect="3",
        body=(
            "        if not input.strip():\n"
            f"{_EMPTY_ANSWER['count_words']}\n"
            f"{_result('str(len(input.split()))')}"
        ),
        summary="Count the words in the text, where a word is a run of non-space characters.",
    ),
    Composition(
        intent="count_lines",
        patterns=(r"\bcount\b.*\blines?\b", r"\bline\s+count\b", r"\bhow many lines\b"),
        example_input="alpha\nbeta\ngamma",
        expect="3",
        body=(
            "        if not input:\n"
            f"{_EMPTY_ANSWER['count_lines']}\n"
            f"{_result('str(len(input.splitlines()))')}"
        ),
        summary="Count the lines in the text.",
    ),
    Composition(
        intent="count_characters",
        patterns=(
            r"\bcount\b.*\b(characters?|chars?|letters?)\b",
            r"\bcharacter\s+count\b",
            r"\bhow many characters\b",
        ),
        example_input="abcde",
        expect="5",
        body=_result("str(len(input))"),
        summary="Count the characters in the text, including spaces.",
    ),
    Composition(
        intent="reverse_text",
        patterns=(
            r"\breverse\b.*\b(text|string|words?|letters?|characters?|note|sentence|paragraph|line|it|this|that)\b",
            r"\bbackwards?\b.*\b(text|string|words?|note|sentence|line)\b",
        ),
        example_input="abc",
        expect="cba",
        body=_result("input[::-1]"),
        summary="Return the text reversed, character by character.",
    ),
    Composition(
        intent="title_case",
        patterns=(
            r"\btitle\s*case\b",
            r"\bcapital(ise|ize)\b.*\b(each|every)\b",
            r"\bheadline\b",
        ),
        example_input="hello wide world",
        expect="Hello Wide World",
        body=_result("input.title()"),
        summary="Capitalise the first letter of every word.",
    ),
    Composition(
        intent="upper_case",
        patterns=(
            r"\buppercase\b",
            r"\bupper\s*case\b",
            r"\ball\s+caps\b",
            r"\bshout\b",
            r"\bcapital(ise|ize)\b",
        ),
        example_input="quiet words",
        expect="QUIET WORDS",
        body=_result("input.upper()"),
        summary="Return the text in upper case.",
    ),
    Composition(
        intent="lower_case",
        patterns=(r"\blowercase\b", r"\blower\s*case\b", r"\bdowncase\b"),
        example_input="LOUD WORDS",
        expect="loud words",
        body=_result("input.lower()"),
        summary="Return the text in lower case.",
    ),
    Composition(
        intent="trim_whitespace",
        patterns=(
            r"\b(trim|strip)\b.*\b(whitespace|spaces?|text|string|note|lines?|input|edges?)\b",
            r"\bremove\b.*\b(whitespace|spaces?)\b",
        ),
        example_input="  padded  ",
        expect="padded",
        body=_result("input.strip()"),
        summary="Remove leading and trailing whitespace.",
    ),
    Composition(
        intent="sort_lines",
        patterns=(
            r"\bsort\b.*\b(lines?|text|note|words?|alphabetically)\b",
            r"\balphabet(ise|ize)\b.*\b(lines?|list|text|note|words?)\b",
        ),
        example_input="beta\nalpha",
        expect="alpha\nbeta",
        body=(
            "        lines = [line for line in input.splitlines() if line.strip()]\n"
            + _result('"\\n".join(sorted(lines))')
        ),
        summary="Sort the non-empty lines of the text alphabetically.",
    ),
    Composition(
        intent="unique_lines",
        patterns=(
            r"\b(unique|distinct|deduplicate|dedupe|remove)\b.*\b(lines?|duplicates?)\b",
            r"\bduplicates?\b",
        ),
        example_input="alpha\nbeta\nalpha",
        expect="alpha\nbeta",
        body=(
            "        seen: dict[str, None] = {}\n"
            "        for line in input.splitlines():\n"
            "            if line.strip():\n"
            "                seen.setdefault(line, None)\n"
            + _result('"\\n".join(seen)')
        ),
        summary="Remove duplicate lines, keeping the first occurrence of each.",
    ),
    Composition(
        intent="sum_numbers",
        patterns=(r"\bsum\b", r"\badd\b.*\bnumbers?\b", r"\btotal\b.*\bnumbers?\b"),
        example_input="1 2 3",
        expect="6",
        body=(
            f"{_NUMBERS_PREAMBLE}\n"
            "        if not numbers:\n"
            f"{_EMPTY_ANSWER['sum_numbers']}\n"
            "        total = sum(numbers)\n"
            f"{_result('str(int(total)) if float(total).is_integer() else str(total)')}"
        ),
        summary="Add up every number it can find in the text.",
    ),
    Composition(
        intent="average_numbers",
        patterns=(r"\baverage\b", r"\bmean\b", r"\bavg\b"),
        example_input="2 4 6",
        expect="4",
        body=(
            f"{_NUMBERS_PREAMBLE}\n"
            "        if not numbers:\n"
            f"{_EMPTY_ANSWER['average_numbers']}\n"
            "        average = sum(numbers) / len(numbers)\n"
            f"{_result('str(int(average)) if float(average).is_integer() else str(average)')}"
        ),
        summary="Average the numbers it can find in the text.",
    ),
    Composition(
        intent="format_json",
        patterns=(
            r"\b(format|pretty|beautify|indent|reformat)\b.*\bjson\b",
            r"\bjson\b.*\b(pretty|format|indent)\b",
        ),
        example_input='{"a":1,"b":[2,3]}',
        expect='{\n  "a": 1,\n  "b": [\n    2,\n    3\n  ]\n}',
        body=(
            "        import json\n"
            "\n"
            "        if not input.strip():\n"
            + _result('"There is no JSON in that text."', indent=12, error=True)
            + "\n"
            "        try:\n"
            "            payload = json.loads(input)\n"
            "        except ValueError as exc:\n"
            + _result(
                'f"That is not valid JSON, so it was not reformatted: {exc}"', indent=12, error=True
            )
            + "\n"
            + _result("json.dumps(payload, indent=2)")
        ),
        summary="Reformat JSON with indentation, refusing invalid input honestly.",
    ),
)

#: Names a composed body must never mention. Composed bodies run unsupervised in the
#: smoke test, so they are pure functions of their input by construction: no imports
#: beyond JSON parsing, no files, no processes, no network. This is a refusal at
#: compose time rather than a promise in a docstring.
FORBIDDEN_IN_BODY: Final[frozenset[str]] = frozenset(
    {
        "__import__",
        "eval(",
        "exec(",
        "globals(",
        "os.",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys.",
        "urllib",
    }
)


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def intent_for(capability: str, request: str = "") -> Composition | None:
    """The composition that answers this capability, or None. Never guesses.

    The capability phrase — the planner's own naming of the task — is matched first
    and is the only thing that can select an intent. The owner's full request is
    consulted second, and only when the capability phrase named no intent: a request
    can say "sum the numbers" while the planner named the step "add numbers total",
    and either way it is the same library entry.
    """
    for composition in COMPOSITIONS:
        if any(_matches(pattern, capability) for pattern in composition.patterns):
            return composition
    if request and request != capability:
        for composition in COMPOSITIONS:
            if any(_matches(pattern, request) for pattern in composition.patterns):
                return composition
    return None


def compose(capability: str, request: str = "") -> Composition | None:
    """Return the composition for this capability, refusing anything unsafe.

    A composition whose body mentions a forbidden name is treated as absent: the
    caller falls back to the scaffold, which says it is unfinished. That is a worse
    answer than a working tool and a better one than an unsupervised body holding a
    door open.
    """
    composition = intent_for(capability, request)
    if composition is None:
        return None
    if any(name in composition.body for name in FORBIDDEN_IN_BODY):
        return None
    return composition
