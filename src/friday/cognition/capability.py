"""Never refuse a request outright: resolve it into something executable.

The owner's second requirement was blunt. When asked for work it had never done,
FRIDAY was replying that it did not know how. That is a *refusal*, and it is the
wrong answer — not because every request can be granted, but because "I do not
know how" is almost never the true state of the system. The true states are much
more specific and much more useful:

* the capability exists, under a different name (**compose it**)
* the capability is a sequence of things FRIDAY can already do (**chain them**)
* the capability does not exist yet, and is written the same way every other tool
  in this repository was written (**synthesise and prove it**)
* the capability cannot exist here — it needs hardware, credentials or a remote
  service that is not present (**say exactly what is missing, and what it would
  unlock**)

This module produces answers of those four kinds. It never produces "I can't".

How it reasons. A request is turned into a **plan** over the tools that actually
exist, using the configured model when one is reachable. Each plan step is then
checked against the registry. Steps that map to a real tool are kept as-is; steps
whose capability is absent are collected into a :class:`CapabilityGap`. A gap is
not a failure — it is the input to synthesis, which writes the missing tool,
proves it in isolation, and hands it to the same gated path every other change
uses.

What this module deliberately does **not** do: claim success. A plan that was
produced but not executed is reported as produced. A tool that was synthesised
but not yet applied is reported as synthesised, with the gate step it reached. A
request needing a microphone is reported as needing a microphone — with the
reason, so the owner can act on it.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from friday.core.logging import get_logger

logger = get_logger("cognition.capability")

#: Where synthesised tools land, matching where every other builtin lives.
TOOLS_DIRECTORY = "src/friday/tools/builtin"

#: Reasons a gap cannot be closed on this machine. Each names what is missing so
#: the owner can supply it, instead of a shrug.
_EXTERNAL_REQUIREMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:microphone|mic|record (?:my )?voice|listen)\b", re.I), "a microphone"),
    (re.compile(r"\b(?:camera|webcam|take a photo|see me)\b", re.I), "a camera"),
    (re.compile(r"\b(?:printer|print)\b", re.I), "a printer"),
    (re.compile(r"\b(?:sms|text message)\b", re.I), "an SMS gateway credential"),
    (re.compile(r"\b(?:trade|buy|sell) (?:stock|crypto|bitcoin|shares)\b", re.I), "a funded exchange account"),
    (re.compile(r"\b(?:send money|pay |transfer funds|bank)\b", re.I), "a banking credential"),
)


@dataclass
class PlanStep:
    """One step of a plan, and whether a tool exists for it."""

    intent: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    available: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "tool": self.tool,
            "arguments": self.arguments,
            "available": self.available,
            "note": self.note,
        }


@dataclass
class CapabilityGap:
    """A capability the plan needs and the registry does not have."""

    capability: str
    rationale: str
    steps: list[str] = field(default_factory=list)
    external_requirement: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "rationale": self.rationale,
            "steps": list(self.steps),
            "external_requirement": self.external_requirement,
        }


@dataclass
class Resolution:
    """What FRIDAY can honestly say about a request it has never done before."""

    request: str
    plan_feasible: bool
    steps: list[PlanStep] = field(default_factory=list)
    gaps: list[CapabilityGap] = field(default_factory=list)
    synthesised: list[dict[str, Any]] = field(default_factory=list)
    plan_source: str = "none"
    started_at: float = field(default_factory=time.time)
    detail: str = ""

    def spoken_summary(self) -> str:
        """The answer, phrased as a person would give it."""
        lines: list[str] = []

        if self.steps:
            available = [step for step in self.steps if step.available]
            lines.append(
                f"Here is how I would do that, in {len(self.steps)} step(s)"
                + (f", {len(available)} of which I can already run:" if available else ":")
            )
            for step in self.steps:
                marker = "can run now" if step.available else "needs building"
                target = f" via {step.tool}" if step.tool else ""
                lines.append(f"  - {step.intent}{target} ({marker})")

        if self.synthesised:
            for item in self.synthesised:
                installation = item.get("installation") or {}
                if installation.get("reachable"):
                    lines.append(
                        f"I built the missing piece: {item.get('tool')} at {item.get('path')} "
                        f"({item.get('verification')}). It is installed and verified on the real "
                        f"tree ({installation.get('commit', '')[:8]})."
                    )
                    continue
                lines.append(
                    f"I built and self-tested the missing piece: {item.get('tool')} at "
                    f"{item.get('path')} ({item.get('verification')}). "
                    f"{item.get('gate_step', '')} {installation.get('detail', '')}".strip()
                )

        for gap in self.gaps:
            if gap.external_requirement:
                lines.append(
                    f"I cannot complete '{gap.capability}' on this machine: it needs "
                    f"{gap.external_requirement}. Everything up to that point is ready."
                )
            elif not self.synthesised:
                lines.append(
                    f"'{gap.capability}' does not exist here yet. {gap.rationale}"
                )

        if not lines:
            lines.append(
                "I could not break that request into steps I can carry out. "
                f"{self.detail or 'The planner produced no plan, and I will not pretend it did.'}"
            )
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "plan_feasible": self.plan_feasible,
            "plan_source": self.plan_source,
            "steps": [step.as_dict() for step in self.steps],
            "gaps": [gap.as_dict() for gap in self.gaps],
            "synthesised": self.synthesised,
            "detail": self.detail,
        }


PLAN_SYSTEM_PROMPT = """You break an owner's request into steps that FRIDAY can carry out.

You are given the request and the exact list of tools FRIDAY has. Reply with JSON:

{"steps": [{"intent": "short description", "tool": "tool_name_or_null", "arguments": {}}]}

Rules:
- Use only tools from the list, spelling names exactly. A step with no matching
  tool must set "tool" to null and be given a clear "intent".
- Never invent a tool name. If a capability is missing, say so with null; that is
  useful information, and an invented name is not.
- Prefer a two-step chain of real tools over one step that needs a new tool.
- Keep the plan minimal: the fewest steps that achieve the request.
- If the request genuinely cannot be done on a computer, still return the steps
  that can be done, and let one step with a null tool name carry the impasse.
"""


class ToolCatalogue:
    """The tools that actually exist, with the names the model must use.

    Built by introspection rather than by a hand-maintained list, because a list
    that drifts is worse than no list: the planner would confidently name tools
    that do not exist. The agent builds its own registry from the same builtin
    package, so scanning that package cannot disagree with what the agent runs.
    """

    _shared: ClassVar[ToolCatalogue | None] = None

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        self._scanned: dict[str, Any] | None = None

    @classmethod
    def shared(cls) -> ToolCatalogue:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def _instantiate(self, tool_cls: Any) -> Any | None:
        import inspect

        try:
            signature = inspect.signature(tool_cls.__init__)
        except (TypeError, ValueError):
            return None
        required = [
            name
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        ]
        if required:
            # Needs a dependency (memory, an HTTP client) that the catalogue has
            # no business inventing. The agent's own registry supplies those; the
            # catalogue only needs the name and description, which are class
            # attributes, so record the class itself as the entry.
            return tool_cls
        try:
            return tool_cls()
        except Exception as exc:
            logger.debug("tool %s could not be instantiated for the catalogue: %s", tool_cls.__name__, exc)
            return None

    def _scan(self) -> dict[str, Any]:
        if self._scanned is not None:
            return self._scanned
        found: dict[str, Any] = {}

        # Tools the agent holds live are authoritative for the names they cover.
        registry = getattr(self, "_registry", None)
        if registry is not None and hasattr(registry, "list_tools"):
            for tool in registry.list_tools():
                name = getattr(tool, "name", "")
                if isinstance(name, str) and name:
                    found[name] = tool
        try:
            import friday.tools.builtin as builtins_package
            from friday.tools.base import BaseTool
        except Exception as exc:
            logger.warning("builtin tools could not be imported: %s", exc)
            self._scanned = found
            return found

        import pkgutil

        modules = [builtins_package]
        for info in pkgutil.iter_modules(builtins_package.__path__):
            try:
                modules.append(importlib.import_module(f"{builtins_package.__name__}.{info.name}"))
            except Exception as exc:
                logger.debug("skipping builtin module %s: %s", info.name, exc)

        for module in modules:
            for _, obj in vars(module).items():
                if not isinstance(obj, type) or obj is BaseTool or not issubclass(obj, BaseTool):
                    continue
                name = getattr(obj, "name", "") or ""
                if not isinstance(name, str) or not name or name in found:
                    # Already known from the live registry, or a property or other
                    # descriptor rather than a class attribute: either way, not a
                    # name to add.
                    continue
                instance = self._instantiate(obj)
                if instance is not None:
                    found[name] = instance
        self._scanned = found
        logger.info("capability catalogue: %d tools available", len(found))
        return found

    def entries(self) -> dict[str, Any]:
        """Every tool that exists, live registry first and everything else beside it.

        The registry used to replace the scan outright when it was supplied, which
        meant a tool that had been installed a moment ago - a real file in the tools
        directory, importable, executable - was invisible to every planner that had a
        registry to look at. That is exactly the case the offline fallback runs in:
        the registry was built at start-up, the capability was installed after it, and
        the request was answered "nothing could be carried out" while holding a
        working tool for the job. The registry still wins for any name it has, so
        nothing it holds is overridden.
        """
        scanned = self._scan()
        if self._registry is None:
            return scanned
        try:
            live = {tool.name: tool for tool in self._registry.list_tools()}
        except Exception as exc:
            logger.warning("supplied registry could not be listed: %s", exc)
            return scanned
        return {**scanned, **live}

    def names(self) -> list[str]:
        return sorted(self.entries())

    def has(self, name: str) -> bool:
        return name in self.entries()

    def describe(self, limit: int = 140) -> str:
        lines: list[str] = []
        for name, tool in sorted(self.entries().items())[:limit]:
            description = (getattr(tool, "description", "") or "").strip().splitlines()
            first_line = description[0] if description else ""
            lines.append(f"- {name}: {first_line[:160]}")
        return "\n".join(lines)


@dataclass(frozen=True)
class AuthoredBody:
    """An implementation body, who wrote it, and what it claims to do.

    ``self_test`` is present only when the author also states an example: run the
    tool on this input and the answer must be this. It is not decoration - the
    smoke test executes it in a fresh interpreter, so a body that does not behave
    as described never reaches a proposal.
    """

    body: str
    authorship: str
    self_test: dict[str, str] | None = None
    detail: str = ""


#: Verbs that name something a tool can do. A request whose only content is talk
#: ("hello", "why is the sky blue") contains none of these, which is how the
#: offline planner tells work from conversation.
ACTION_VERBS = frozenset(
    {
        "add", "analyse", "analyze", "annotate", "archive", "average", "beautify", "build",
        "calculate", "check",
        "clean", "compare", "compress", "convert", "count", "crop", "decode", "delete",
        "detect", "download", "draft", "encode", "export", "extract", "fetch", "filter",
        "find", "fix", "format", "generate", "group", "import", "install", "list", "log",
        "dedupe", "deduplicate", "mean", "merge", "monitor", "move", "name", "parse", "plot",
        "prettify", "print", "read", "record",
        "rename", "render", "reorder", "replace", "resize", "reverse", "run", "scan",
        "schedule", "search", "send", "sort", "split", "strip", "sum", "summarise", "summarize",
        "sync", "total", "transcribe", "translate", "trim", "upload", "validate", "verify",
        "watch", "write", "zip",
    }
)

#: A quoted span: data the owner supplied, not part of the task's name.
_QUOTED = re.compile(r"[\"']([^\"']*)[\"']")

#: Words that carry no capability of their own; dropped when naming a tool. Kept
#: short deliberately: over-filtering produces names that no longer read as what
#: the tool does.
FILLER_WORDS = frozenset(
    {
        "a", "an", "and", "any", "can", "could", "for", "from", "in", "into", "it", "its",
        "he", "her", "him", "i", "me", "my", "of", "on", "or", "our", "please", "she",
        "that", "the", "their", "them", "they", "we",
        "then", "these", "this", "those", "to", "up", "us", "with", "you", "your",
    }
)


class CapabilityResolver:
    """Turns a request into a plan, and a missing capability into a real tool."""

    def __init__(
        self,
        registry: Any | None = None,
        llm: Any | None = None,
        repository_root: str | Path | None = None,
        synthesiser: Any | None = None,
        installer: Any | None = None,
    ) -> None:
        self.catalogue = ToolCatalogue(registry)
        self._llm = llm
        self.repo_root = Path(repository_root or _repository_root()).resolve()
        self._synthesiser = synthesiser
        #: Where a synthesised candidate goes to be reviewed and authorised. When
        #: it is None one is built on first use, because writing code into the
        #: tree without the gate is the defect this closes, not a supported mode.
        self._installer = installer

    # -- planning ----------------------------------------------------------

    def _get_llm(self) -> Any | None:
        if self._llm is not None:
            return self._llm
        try:
            from friday.core.config import get_settings
            from friday.llm.factory import create_llm_provider

            self._llm = create_llm_provider(get_settings())
        except Exception as exc:
            logger.warning("no model available to plan with: %s", exc)
            self._llm = None
        return self._llm

    def _plan_with_model(self, request: str) -> list[PlanStep]:
        provider = self._get_llm()
        if provider is None:
            return []

        from friday.core.types import Message, Role

        catalogue = self.catalogue.describe()
        if not catalogue:
            return []
        try:
            response = provider.generate(
                [
                    Message(role=Role.SYSTEM, content=PLAN_SYSTEM_PROMPT),
                    Message(
                        role=Role.USER,
                        content=f"Request: {request}\n\nAvailable tools:\n{catalogue}\n",
                    ),
                ]
            )
        except Exception as exc:
            logger.warning("planning call failed: %s", exc)
            return []

        content = (getattr(response, "content", "") or "").strip()
        payload = _extract_json(content)
        if not isinstance(payload, dict):
            return []
        steps: list[PlanStep] = []
        for raw in payload.get("steps") or []:
            if not isinstance(raw, dict):
                continue
            tool_name = raw.get("tool")
            tool = str(tool_name) if tool_name else None
            if tool and not self.catalogue.has(tool):
                # The model named something that does not exist. Record that as a
                # gap rather than silently trusting the name.
                steps.append(
                    PlanStep(
                        intent=str(raw.get("intent", "")),
                        tool=None,
                        arguments={},
                        available=False,
                        note=f"the planner named '{tool}', which is not a registered tool",
                    )
                )
                continue
            steps.append(
                PlanStep(
                    intent=str(raw.get("intent", "")),
                    tool=tool,
                    arguments=dict(raw.get("arguments") or {}),
                    available=bool(tool),
                )
            )
        return steps

    def _plan_by_keyword(self, request: str) -> list[PlanStep]:
        """A last resort that is honest: match request words against tool names.

        Deliberately conservative — an exact-ish token overlap only — because a
        confident wrong tool is worse than reporting that no plan was found.
        """
        words = {word for word in re.findall(r"[a-z]{4,}", request.lower())}
        if not words:
            return []
        names = self.catalogue.names()
        # A word that appears in many tool names carries no information: matching
        # "file" against a catalogue where six tools mention files tells us nothing
        # about which one, or whether any of them is right. Weighting each overlap
        # by how rare the word is, and refusing to answer when the best two tools
        # tie, is what keeps this planner honest. "read the tests" still resolves to
        # `run_tests`, because "tests" appears in few names and no other tool
        # matches as well; "transcribe the meeting notes file" no longer resolves to
        # `file_operations` just because it shares the word "file".
        documents = {word: sum(1 for name in names if word in name.lower().split("_")) for word in words}
        scored: list[tuple[float, str]] = []
        for name in names:
            name_words = set(name.lower().split("_"))
            overlap = name_words & words
            if not overlap:
                continue
            score = sum(1.0 / documents[word] for word in overlap)
            scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored:
            return []
        if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9:
            return []
        best = scored[0][1]
        return [
            PlanStep(
                intent=f"run {best}",
                tool=best,
                arguments={},
                available=True,
                note="matched by name overlap; the model was unavailable to plan",
            )
        ]

    def _plan_by_intent(self, request: str) -> list[PlanStep]:
        """Name the capability a request asks for, when nothing else can plan it.

        This exists because of the answer it replaces. With no model reachable and
        no keyword overlap, the resolver used to say it could not break the request
        into steps at all — which is technically honest and practically useless: it
        is the "I don't know how" the owner objected to, on a host that can build a
        tool. A request with a real action verb and an object names a capability, so
        the step is emitted with no tool and the resolver goes on to synthesise one.

        Bounded on purpose: a verb must be present and there must be an object, so
        conversation ("hello", "why is the sky blue") still gets the honest "no plan"
        rather than a junk tool. What it produces is a plan, and the implementation
        is a scaffold unless a model authors it — which the resolution says out loud.
        """
        # Only the instruction names the capability. "count the words in this note:
        # the quick brown fox" asks for a word count, and the note is what to count -
        # folding the payload into the name produced "count words note quick brown",
        # a capability nobody can implement and a name that hides what was asked for.
        instruction = request
        if ":" in instruction:
            instruction = instruction.split(":", 1)[0]
        instruction = re.sub(_QUOTED, " ", instruction)
        tokens = re.findall(r"[a-z0-9']+", instruction.lower())
        verb = next((token for token in tokens if token in ACTION_VERBS), None)
        if verb is None:
            return []
        object_words = [
            word
            for word in tokens[tokens.index(verb) + 1 :]
            if word not in FILLER_WORDS and len(word) > 1 and not word.isdigit()
            # Digits are data, not the name of a capability: "average these numbers
            # 4 8 12" asks for an average of some numbers, and "average numbers 12"
            # is not a capability - it is a sentence fragment that leaked into a name.
        ][:3]
        if not object_words:
            return []
        capability = " ".join([verb, *object_words])
        return [
            PlanStep(
                intent=capability,
                tool=None,
                arguments={},
                available=False,
                note=(
                    "No tool exists for this and no model was reachable to plan it. The step is "
                    "named from the owner's own words, so it can be built, proven and installed "
                    "like any other tool; without a model its implementation is a scaffold that "
                    "reports its own incompleteness."
                ),
            )
        ]

    def plan(self, request: str) -> tuple[list[PlanStep], str]:
        steps = self._plan_with_model(request)
        if steps:
            return steps, "model"
        steps = self._plan_by_keyword(request)
        if steps:
            return steps, "keyword"
        steps = self._plan_by_intent(request)
        if steps:
            return steps, "intent"
        return [], "none"

    # -- gap analysis ------------------------------------------------------

    def gaps_for(self, request: str, steps: list[PlanStep]) -> list[CapabilityGap]:
        gaps: list[CapabilityGap] = []
        for step in steps:
            if step.available:
                continue
            requirement = _external_requirement(request)
            gaps.append(
                CapabilityGap(
                    capability=step.intent or request,
                    rationale=step.note
                    or (
                        "No registered tool matches this step. It can be built and proven the same "
                        "way every other tool in this repository was."
                    ),
                    steps=[s.intent for s in steps],
                    external_requirement=requirement,
                )
            )
        # A request can need something external even when the plan itself looks
        # complete, and saying so early is more useful than saying it late.
        if not gaps:
            requirement = _external_requirement(request)
            if requirement:
                gaps.append(
                    CapabilityGap(
                        capability=request.strip(),
                        rationale=f"This requires {requirement}, which is not present on this host.",
                        steps=[s.intent for s in steps],
                        external_requirement=requirement,
                    )
                )
        return gaps

    # -- the whole resolution ---------------------------------------------

    def resolve(self, request: str, *, target_path: str = "", allow_synthesis: bool = True) -> Resolution:
        if not request or not request.strip():
            return Resolution(
                request=request,
                plan_feasible=False,
                detail="The request was empty, so there was nothing to plan.",
            )

        steps, source = self.plan(request)
        gaps = self.gaps_for(request, steps)

        resolution = Resolution(
            request=request,
            plan_feasible=bool(steps) and all(step.available for step in steps),
            steps=steps,
            gaps=gaps,
            plan_source=source,
        )

        if not steps:
            resolution.detail = (
                "No tool in the registry maps to this request and no model was reachable to plan it. "
                "This is a planning gap, not a refusal: the request has not been attempted."
            )
            return resolution

        if gaps and allow_synthesis:
            # The provider the caller pinned is the provider that writes the body.
            # Without this the synthesiser built its own, reached for the network
            # and ignored the fake a caller had supplied to keep the run offline.
            synthesiser = self._synthesiser or ToolSynthesiser(
                self.repo_root, llm=self._llm
            )
            for gap in gaps:
                if gap.external_requirement:
                    # Nothing to build: the missing piece is hardware or a
                    # credential, and building a tool would not supply it.
                    continue
                outcome = synthesiser.synthesise(
                    gap, request=request, target_path=target_path, install=True
                )
                outcome["installation"] = self._install(outcome, gap)
                resolution.synthesised.append(outcome)
                if outcome["installation"].get("reachable"):
                    resolution.plan_feasible = True

        if not gaps:
            resolution.detail = "Every step maps to a tool that exists."
        elif any(item.get("installation", {}).get("reachable") for item in resolution.synthesised):
            resolution.detail = (
                "The plan is complete: the missing capability was synthesised, reviewed, "
                "authorised and installed on the real tree."
            )
        elif any(item.get("verified") for item in resolution.synthesised):
            resolution.detail = (
                "The missing capability was synthesised and passed its smoke test, but it is not "
                "installed yet; each item says which gate step it reached and what it needs."
            )
        else:
            resolution.detail = (
                "The plan is incomplete. The gaps are listed with what each one needs."
            )
        return resolution

    def _install(self, outcome: dict[str, Any], gap: CapabilityGap) -> dict[str, Any]:
        """Send a candidate to the gate, or say why it never got there."""
        if not outcome.get("verified") or not outcome.get("source"):
            return {
                "outcome": "NOT_INSTALLED",
                "reachable": False,
                "detail": "there was no verified candidate to install",
            }
        if self._installer is None:
            from friday.cognition.installation import CapabilityInstaller

            self._installer = CapabilityInstaller(self.repo_root)
        installed = self._installer.install(
            tool_name=outcome["tool"],
            source=outcome["source"],
            capability=gap.capability,
            rationale=f"install the capability {gap.capability!r}, requested in FRIDAY's own words",
            smoke_check={
                "ok": bool(outcome.get("verified")),
                "checks": outcome.get("checks") or [],
                "detail": outcome.get("detail", ""),
                "command": outcome.get("smoke_command", "smoke test in a fresh interpreter"),
            },
            relative_path=outcome.get("path", ""),
            self_test=outcome.get("self_test"),
        )
        return installed.as_dict()


# ── synthesis ──────────────────────────────────────────────────────────────


TOOL_TEMPLATE = '''"""Autonomously synthesised tool: {title}

Generated by `friday.cognition.capability.ToolSynthesiser` in response to:

    {request}

Provenance: {provenance}

It is an ordinary builtin tool: it appears in the model's schema list and runs
through the normal authorisation path. It is classified SENSITIVE with a USER
requirement, because code no human has reviewed yet must not be born with the
privileges of code that has. Review it, then lower its classification.
"""

from __future__ import annotations

from typing import Any, ClassVar

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class {class_name}(BaseTool):
    """{summary}"""

    name = "{tool_name}"
    description = "{summary}"
    safety_level = SafetyLevel.{safety}
    risk_level = "{safety}"
    auth_requirement = "{auth}"
    parameters: ClassVar[dict[str, Any]] = {{
        "type": "object",
        "properties": {{
            "input": {{
                "type": "string",
                "description": "What to act on.",
            }},
        }},
        "required": [],
    }}

    def execute(self, input: str = "", **_: Any) -> ToolResult:
        """Carry out the capability this tool was created for."""
{body}
'''


class ToolSynthesiser:
    """Writes a missing tool, proves it works, and hands it to the gate.

    Verification here is deliberately weaker than the reflex loop's, and says so.
    A brand-new tool has no failing test to flip, so the strongest available
    proof is: it parses, it imports, it instantiates, it exposes a valid schema,
    and it returns a :class:`ToolResult` for a sample call. That is a smoke test,
    not a test suite, and every receipt from this class is labelled ``smoke_test``
    rather than ``verified_repair``.
    """

    def __init__(self, repo_root: str | Path, llm: Any | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._llm = llm

    def _get_llm(self) -> Any | None:
        if self._llm is not None:
            return self._llm
        try:
            from friday.core.config import get_settings
            from friday.llm.factory import create_llm_provider

            self._llm = create_llm_provider(get_settings())
        except Exception:
            self._llm = None
        return self._llm

    # -- naming ------------------------------------------------------------

    @staticmethod
    def tool_name_for(capability: str) -> str:
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", capability.lower())
            if word not in {"to", "the", "a", "an", "for", "of", "and", "with", "that", "which", "my"}
        ][:4]
        return "_".join(words) or "synthesised_tool"

    @staticmethod
    def class_name_for(tool_name: str) -> str:
        return "".join(part.capitalize() for part in tool_name.split("_")) + "Tool"

    # -- body synthesis ----------------------------------------------------

    def _body_for(
        self, gap: CapabilityGap, request: str, *, skip_model: bool = False
    ) -> AuthoredBody:
        """Return the body, where it came from, and the claim it must live up to.

        Order of authorship: a model if one is reachable, then FRIDAY's own offline
        library of known intents, then an honest scaffold. The middle step is what
        stops "no model" from meaning "no answer" on work FRIDAY already knows how to
        do; the last step is what stops a missing capability from being papered over.

        ``skip_model`` exists for one case: a model authored a body and that body then
        failed its smoke test. A broken answer from a model is not the end of the road
        when the work is one FRIDAY already knows how to do.
        """
        provider = None if skip_model else self._get_llm()
        if provider is not None:
            from friday.core.types import Message, Role

            prompt = (
                f"Write the body of one Python method: `def execute(self, input: str = \"\", **_: Any) -> ToolResult:`\n"
                f"The tool must: {gap.capability}\nIn service of the owner's request: {request}\n\n"
                "Reply with the method body only — no signature, no class, no fences. It must:\n"
                "- be indented to 8 spaces\n"
                "- import nothing at module level; import inside the method if needed\n"
                "- return ToolResult(name=self.name, content=<str>, is_error=<bool>, safety_level=self.safety_level)\n"
                "- never execute a shell command the owner did not ask for\n"
                "- report honestly when it cannot complete, rather than returning a fake success"
            )
            try:
                response = provider.generate(
                    [
                        Message(
                            role=Role.SYSTEM,
                            content="You extend an autonomous assistant with one new, honest Python method.",
                        ),
                        Message(role=Role.USER, content=prompt),
                    ]
                )
                body = _strip_fences(getattr(response, "content", "") or "")
                if body.strip():
                    indented = textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 8)
                    return AuthoredBody(body=indented, authorship="model_authored")
            except Exception as exc:
                logger.warning("model could not author the tool body: %s", exc)

        from friday.cognition.composition import compose

        composed = compose(gap.capability, request)
        if composed is not None:
            # FRIDAY knows this one. The body is library code and the example below
            # is the author's stated claim about it, checked in a fresh interpreter
            # before the candidate is allowed anywhere near the tree.
            return AuthoredBody(
                body=composed.body,
                authorship=f"local_composition:{composed.intent}",
                self_test=composed.self_test,
                detail=composed.summary,
            )

        body = textwrap.indent(
            textwrap.dedent(
                f'''
                """Carry out: {gap.capability}"""
                return ToolResult(
                    name=self.name,
                    content=(
                        "This tool was scaffolded for '{gap.capability}' but its implementation is "
                        "not finished. It is registered so the plan stays visible, and it reports "
                        "its own incompleteness rather than pretending to have run."
                    ),
                    is_error=True,
                    safety_level=self.safety_level,
                )
                '''
            ).strip("\n"),
            " " * 8,
        )
        return AuthoredBody(body=body, authorship="scaffold")

    # -- the whole synthesis ----------------------------------------------

    def synthesise(
        self,
        gap: CapabilityGap,
        *,
        request: str = "",
        target_path: str = "",
        install: bool = False,
    ) -> dict[str, Any]:
        """Produce a candidate tool, verify it, and hand it wherever it belongs.

        ``install=False`` (the historical behaviour) writes the candidate into the
        working tree. That is an ungoverned write — no commit, no review, no
        mandate — so the returned dict says exactly that instead of claiming a
        gate it never reached. ``install=True`` returns the source *without writing
        anything*, for `CapabilityInstaller` to put through the gate.
        """
        if gap.external_requirement:
            return {
                "tool": None,
                "capability": gap.capability,
                "verified": False,
                "verification": "not_attempted",
                "blocked_by": gap.external_requirement,
                "detail": (
                    f"Not synthesised: {gap.capability} needs {gap.external_requirement}. "
                    "Building a tool would not supply it."
                ),
            }

        tool_name = self.tool_name_for(target_path or gap.capability)
        if target_path:
            relative = target_path.lstrip("./")
        else:
            relative = f"{TOOLS_DIRECTORY}/{tool_name}.py"

        destination = self.repo_root / relative
        if destination.exists():
            return {
                "tool": tool_name,
                "capability": gap.capability,
                "path": relative,
                "verified": True,
                "verification": "already_exists",
                "gate_step": "Nothing was written; a tool at this path already exists.",
                "detail": f"{relative} already exists, so nothing was synthesised.",
            }

        smoke_command = "smoke test in a fresh interpreter"

        def build(authored_body: AuthoredBody) -> str:
            return TOOL_TEMPLATE.format(
                title=gap.capability,
                request=request or gap.capability,
                class_name=self.class_name_for(tool_name),
                tool_name=tool_name,
                summary=_one_line(gap.capability),
                safety="SENSITIVE",
                auth="USER",
                body=authored_body.body,
                provenance=_provenance_line(authored_body.authorship, authored_body),
            )

        authored = self._body_for(gap, request)
        body, authorship = authored.body, authored.authorship
        source = build(authored)
        check = self._verify_source(source, tool_name, self_test=authored.self_test)

        # A model that answers with something that does not work must not be the last
        # word on work FRIDAY can do without it: if its own library knows the task, the
        # library gets the job. The discarded attempt is reported either way.
        #
        # The fallback deliberately stops there. A scaffold is not an improvement on a
        # model's failed attempt - it is a file in the tree that says the work was not
        # done - so a capability nobody can implement is still refused, exactly as it
        # was before this library existed. That is what keeps "mangled code is never
        # written" true.
        fallback_note = ""
        if not check["ok"] and authorship == "model_authored":
            fallback = self._body_for(gap, request, skip_model=True)
            if fallback.authorship.startswith("local_composition:"):
                fallback_note = (
                    " The model's body was discarded first: it failed its smoke test ("
                    + str(check["detail"])[:160]
                    + "). The candidate below is what FRIDAY wrote from its own library."
                )
                authored = fallback
                body, authorship = authored.body, authored.authorship
                source = build(authored)
                check = self._verify_source(source, tool_name, self_test=authored.self_test)
        if not check["ok"]:
            return {
                "tool": tool_name,
                "capability": gap.capability,
                "path": relative,
                "source": None,
                "verified": False,
                "verification": "smoke_test",
                "smoke_command": smoke_command,
                "authorship": authorship,
                "self_test": authored.self_test,
                "gate_step": "Not written: the generated tool failed its own smoke test.",
                "fallback_note": fallback_note or None,
                "detail": check["detail"],
            }

        if install:
            # Nothing is written here. The candidate goes to the gate, which owns
            # the only write in this pipeline.
            return {
                "tool": tool_name,
                "capability": gap.capability,
                "path": relative,
                "source": source,
                "verified": True,
                "verification": "smoke_test",
                "smoke_command": smoke_command,
                "authorship": authorship,
                "self_test": authored.self_test,
                "author_detail": authored.detail,
                "checks": check["checks"],
                "gate_step": "Candidate ready for the gate; nothing has been written yet.",
                "detail": check["detail"],
            }

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
        logger.warning("synthesised a new tool at %s (%s)", relative, authorship)

        return {
            "tool": tool_name,
            "capability": gap.capability,
            "path": relative,
            "source": source,
            "verified": True,
            "verification": "smoke_test",
            "smoke_command": smoke_command,
            "authorship": authorship,
            "self_test": authored.self_test,
            "fallback_note": fallback_note or None,
            "checks": check["checks"],
            "gate_step": (
                "Written to the working tree, uncommitted and unreviewed: no gate ran, because "
                "install=False was requested. This file is not governed code yet."
            ),
            "detail": check["detail"],
        }

    # -- verification ------------------------------------------------------

    #: The driver runs inside the smoke-test subprocess. It imports the candidate
    #: in isolation, checks its schema, calls it once, and prints a JSON verdict.
    _SMOKE_DRIVER = """
import importlib.util, json, sys, traceback
path, module_name, tool_name = sys.argv[1], sys.argv[2], sys.argv[3]
self_test = json.loads(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
verdict = {"checks": [], "ok": False, "detail": ""}
try:
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verdict["checks"].append("imports_cleanly")

    tool_cls = next(
        (
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and obj.__name__.endswith("Tool")
            and obj.__module__ == module_name
        ),
        None,
    )
    if tool_cls is None:
        verdict["detail"] = "the generated module defines no tool class"
        print(json.dumps(verdict))
        raise SystemExit(0)

    tool = tool_cls()
    verdict["checks"].append("instantiates")

    schema = tool.to_openai_schema()
    if schema["function"]["name"] != tool_name:
        verdict["detail"] = "the tool exposes a schema under a different name"
        print(json.dumps(verdict))
        raise SystemExit(0)
    verdict["checks"].append("schema_valid")

    from friday.core.types import ToolResult
    result = tool.execute(input="smoke test")
    if not isinstance(result, ToolResult):
        verdict["detail"] = f"execute() returned {type(result).__name__}, not a ToolResult"
        print(json.dumps(verdict))
        raise SystemExit(0)
    verdict["checks"].append("returns_tool_result")

    if self_test:
        answer = tool.execute(input=self_test["input"])
        got = str(getattr(answer, "content", "")).strip()
        if getattr(answer, "is_error", True):
            verdict["detail"] = (
                "the author's own example failed: the tool reported an error on "
                + repr(self_test["input"]) + " (" + got[:120] + ")"
            )
            print(json.dumps(verdict))
            raise SystemExit(0)
        if got != str(self_test["expect"]).strip():
            verdict["detail"] = (
                "the author's own example failed: on " + repr(self_test["input"])
                + " it should have answered " + repr(self_test["expect"])
                + " and it answered " + repr(got[:120])
            )
            print(json.dumps(verdict))
            raise SystemExit(0)
        verdict["checks"].append("behaves_as_specified")

    verdict["ok"] = True
    verdict["detail"] = (
        "the tool ran, returned a ToolResult, and did what its author said it does"
        if self_test
        else "the tool ran and returned a ToolResult"
    )
except SystemExit:
    raise
except Exception:
    verdict["detail"] = traceback.format_exc(limit=2).strip().splitlines()[-1]
print(json.dumps(verdict))
"""

    def _verify_source(
        self, source: str, tool_name: str, self_test: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Parse, import and exercise the candidate tool, in a separate process.

        The candidate is code a model wrote moments ago and no human has read. It
        is therefore never exec'd inside the running FRIDAY process: it runs under
        a fresh interpreter with a timeout, and only its JSON verdict comes back.
        """
        checks: list[str] = []
        try:
            ast.parse(source)
        except SyntaxError as exc:
            return {"ok": False, "checks": checks, "detail": f"the generated tool does not parse: {exc}"}
        checks.append("syntax_valid")

        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory(prefix="friday-tool-") as workdir:
            candidate = Path(workdir) / f"{tool_name}.py"
            candidate.write_text(source, encoding="utf-8")
            module_name = f"friday_synth_{tool_name}"

            environment = dict(os.environ)
            source_root = str(self.repo_root / "src")
            existing = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = os.pathsep.join(
                part for part in (source_root, existing) if part
            )
            environment["PYTHONDONTWRITEBYTECODE"] = "1"

            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        self._SMOKE_DRIVER,
                        str(candidate),
                        module_name,
                        tool_name,
                        json.dumps(self_test) if self_test else "",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=workdir,
                    env=environment,
                )
            except subprocess.TimeoutExpired:
                return {
                    "ok": False,
                    "checks": checks,
                    "detail": "the generated tool did not finish its smoke test within 60 seconds",
                }

            stdout = completed.stdout.strip()
            verdict: dict[str, Any] | None = None
            for line in reversed(stdout.splitlines()):
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and "ok" in parsed:
                    verdict = parsed
                    break
            if verdict is None:
                tail = (completed.stderr or stdout or "no output").strip().splitlines()[-3:]
                return {
                    "ok": False,
                    "checks": checks,
                    "detail": "the smoke test produced no verdict: " + " | ".join(tail),
                }
            checks.extend(verdict.get("checks", []))

        if not verdict.get("ok"):
            return {
                "ok": False,
                "checks": checks,
                "detail": f"the generated tool failed its smoke test: {verdict.get('detail', '')}".strip(),
            }
        return {
            "ok": True,
            "checks": checks,
            "detail": (
                "Smoke test passed in a separate process: the tool parses, imports, instantiates, "
                "exposes a valid schema and returns a ToolResult. This is not a behavioural test — "
                "the tool has no assertions of its own yet."
            ),
        }


# ── helpers ────────────────────────────────────────────────────────────────


def _repository_root() -> Path:
    """The checkout this package is running from."""
    return Path(__file__).resolve().parents[3]


def _provenance_line(authorship: str, authored: AuthoredBody) -> str:
    """What a reader of this file needs to know about who wrote it and how it was checked."""
    if authorship == "model_authored":
        return (
            "the body was written by a language model and no human has read it. It passed the "
            "structural smoke test; treat it as unreviewed generated code."
        )
    if authorship.startswith("local_composition:"):
        intent = authorship.split(":", 1)[1]
        example = authored.self_test or {}
        return (
            "the body was composed offline by friday.cognition.composition from its known "
            f"intent {intent!r} ({authored.detail}). The author stated the example in advance "
            f"({example.get('input')!r} -> {example.get('expect')!r}) and the smoke test ran it "
            "against this file in a fresh interpreter. That is the author's own claim, not a "
            "human review: read the body before trusting it."
        )
    return (
        "the body is a scaffold: the capability was planned and installed, but nothing here "
        "implements it. It reports its own incompleteness instead of faking a result."
    )


def _one_line(text: str, limit: int = 180) -> str:
    return " ".join(text.split())[:limit]


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        if len(parts) >= 2:
            body = parts[1]
            if body.startswith("python"):
                body = body[len("python") :]
            return body.strip("\n")
    return stripped


def _extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model response, or return None."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except ValueError:
        return None


def _external_requirement(request: str) -> str | None:
    """What this request needs that a program cannot supply."""
    for pattern, requirement in _EXTERNAL_REQUIREMENTS:
        if pattern.search(request):
            return requirement
    return None
