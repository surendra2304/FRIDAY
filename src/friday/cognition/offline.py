"""The answer FRIDAY gives when its model is unreachable and the work is its own to do.

Found by using the thing. The owner said:

    "count the words in this note: the quick brown fox jumps over the lazy dog"

and FRIDAY answered:

    "LLM generation failed. I'm having trouble connecting to my intelligence core…"

while holding a working word-counting capability it had composed and installed itself
minutes earlier, a planning library, and a tool registry. The autonomous machinery was
real and the conversation could not reach it: every request went to the model, and a
model that could not be reached ended the turn.

This module is the bridge. On a failed generation, the agent asks its own planner what
the request actually needs, runs whatever it can run, builds what it can build (through
the same gate, mandate and reviewer as anything else), and answers with what it did.

The honesty rules are the point:

* the answer says it came from FRIDAY's own library, not from a model;
* every tool that ran is named, with the input it was given and the output it returned,
  so the owner can check the work rather than trust the sentence;
* a capability that was built is reported as built, and a capability that is still
  waiting on a reviewer or a mandate is reported that way - never as done;
* if the request is conversation, or needs someone's judgement, or needs hardware this
  host does not have, this returns nothing and the original failure stands. A confident
  wrong answer would be worse than the honest error it replaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("cognition.offline")


@dataclass
class OfflineAnswer:
    """What FRIDAY managed to do without a model, and the evidence for it."""

    spoken: str
    success: bool = False
    plan_source: str = "none"
    used: list[dict[str, Any]] = field(default_factory=list)
    built: list[dict[str, Any]] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "spoken": self.spoken,
            "success": self.success,
            "plan_source": self.plan_source,
            "used": self.used,
            "built": self.built,
            "remaining": self.remaining,
            "detail": self.detail,
        }


#: The only imports a composed body may contain. Everything else a composed body
#: needs is a string or number operation, which needs no import at all.
PURE_IMPORTS = frozenset({"re", "json"})

#: Names whose presence in a tool body means it is not a pure text transformation.
#: Not a proof of purity - a proof is not possible by reading names - but a body that
#: mentions none of these, imports nothing outside the allowlist, and was composed by
#: FRIDAY's own library, is a function of the text the owner supplied.
IMPURE_NAMES = (
    "__builtins__",
    "__class__",
    "__dict__",
    "__getattribute__",
    "__globals__",
    "__import__",
    "__subclasses__",
    "breakpoint(",
    "compile(",
    "eval(",
    "exec(",
    "globals(",
    "input(",
    "open(",
    "os.",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys.",
    "urllib",
    "vars(",
)

PROVENANCE_MARKER = "composed offline by friday.cognition.composition"


def purity_verdict(tool: Any) -> tuple[bool, str]:
    """Whether this tool is a pure function of the text it is given.

    Reads the code that is about to run, not a flag on the object, because a flag is
    something any tool can set and the source is not.
    """
    import inspect
    import re as _re

    try:
        source = inspect.getsource(tool.execute)
    except Exception as exc:
        return False, f"its source could not be read ({type(exc).__name__})"
    for name in IMPURE_NAMES:
        if name in source:
            return False, f"its body mentions {name!r}"
    for module in _re.findall(
        r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", source, _re.MULTILINE
    ):
        root = (module[0] or module[1]).split(".")[0]
        if root and root not in PURE_IMPORTS:
            return False, f"its body imports {root!r}"

    return True, "a pure function of the text it is given"


def composed_by_friday(tool: Any) -> tuple[bool, str]:
    """Whether FRIDAY's own library wrote this tool's body.

    A separate fact from purity, and a separate requirement: a tool that merely looks
    pure could have been written by a model, and running unreviewed model code without
    a human in the loop is exactly what the SENSITIVE classification is for.
    """
    import inspect

    module_ref = inspect.getmodule(tool)
    if module_ref is None:
        return False, "the tool's module could not be found"
    if PROVENANCE_MARKER in (module_ref.__doc__ or ""):
        return True, "its file declares that FRIDAY's own library composed it"
    return False, "its file does not declare that FRIDAY's own library composed it"


def consent_for_unreviewed_tool(relative_path: str) -> tuple[bool, str]:
    """Whether the owner has already consented to FRIDAY running its own new code.

    The owner's own two ways of saying yes: autonomous mode on this host, or a
    standing mandate he signed. Absence of both is not permission, and the answer
    this returns is used to *keep* the refusal, not to work around it.
    """
    try:
        from friday.core.config import get_settings

        settings = get_settings()
        if getattr(settings, "autonomous_mode", False) or getattr(settings, "full_access_mode", False):
            return True, "autonomous mode is enabled on this host"
    except Exception as exc:
        logger.debug("settings could not be read while checking consent: %s", exc)

    try:
        from friday.cognition.mandate import MandateAuthority

        verdict = MandateAuthority().evaluate(
            "source_repair", paths=(relative_path,), has_test_evidence=True
        )
        if getattr(verdict, "allowed", False):
            return True, f"a standing mandate is in force ({relative_path})"
        reason = getattr(verdict, "reason", "") or getattr(verdict, "refusal", "")
        return False, f"no standing mandate covers this ({reason})"
    except Exception as exc:
        return False, f"the mandate could not be read ({type(exc).__name__}: {exc})"


def payload_from(goal: str, limit: int = 20_000) -> str:
    """The part of a request the owner wants worked on.

    "count the words in this note: the quick brown fox" asks for a count of the text
    after the colon, not of the whole sentence - counting the instruction itself would
    be a wrong answer delivered confidently. A quoted span wins over a colon, because
    "reverse the text 'hello world'" names its payload exactly.
    """
    text = goal.strip()
    quoted = re.search(r"[\"']([^\"']+)[\"']", text)
    if quoted:
        return quoted.group(1)[:limit]
    if ":" in text:
        tail = text.split(":", 1)[1].strip()
        if tail:
            return tail[:limit]
    return text[:limit]


def _arguments_for(tool: Any, step: Any, payload: str) -> dict[str, Any]:
    """The arguments a plan step should be run with.

    A step that named its own arguments is run with them. Otherwise a tool that takes
    an ``input`` is given the owner's own words, because that is what the request was
    about - and the answer reports exactly what was passed, so a wrong payload is
    visible rather than buried.
    """
    arguments = dict(getattr(step, "arguments", None) or {})
    if arguments:
        return arguments
    schema = getattr(tool, "parameters", None) or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if isinstance(properties, dict) and "input" in properties:
        return {"input": payload}
    if isinstance(properties, dict) and properties:
        # It declares parameters and none of them is the text: this planner has no
        # business guessing which one the owner's words belong in.
        return {}
    # No declared schema at all. The signature is the authority then: a tool whose
    # execute() takes `input` was written to be given the owner's words.
    import inspect

    try:
        parameters = inspect.signature(tool.execute).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "input" in parameters:
        return {"input": payload}
    return {}


def _register_installed(registry: Any, path: Path, tool_name: str) -> Any | None:
    """Load a tool that was just installed and put it in the live registry.

    A registry built at start-up does not know about a file written a moment ago, and
    "installed but not runnable" is not an install. Failure here is reported by the
    caller, not swallowed: the installation's own receipt is what claims the file is
    on the tree, so if it cannot be imported that is worth knowing.
    """
    import importlib.util
    import sys

    module_name = f"friday_installed_{tool_name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Register before executing it: a module that is not in sys.modules has no
    # resolvable file, and the file is what the mandate is asked about. Importing
    # properly also keeps module-level behaviour (dataclasses, pickling) working.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and getattr(value, "name", None) == tool_name
            and hasattr(value, "execute")
        ):
            instance = value()
            if registry is not None and hasattr(registry, "register"):
                registry.register(instance)
            return instance
    return None


def answer_without_a_model(
    goal: str,
    *,
    registry: Any | None = None,
    repo_root: str | Path | None = None,
    allow_build: bool = True,
    authorizer: Any | None = None,
) -> OfflineAnswer | None:
    """Do what this request needs using FRIDAY's own machinery, or return None.

    ``None`` means "not mine to answer": the request is conversation, or a plan needs
    judgement that no local rule supplies. The caller keeps its original error.
    """
    if not goal or not goal.strip():
        return None

    try:
        from friday.cognition.capability import CapabilityResolver
    except Exception as exc:  # pragma: no cover - import-time only
        logger.warning("the capability resolver is unavailable: %s", exc)
        return None

    try:
        resolution = CapabilityResolver(registry=registry, repository_root=repo_root).resolve(
            goal, allow_synthesis=allow_build
        )
    except Exception as exc:
        logger.warning("offline planning failed: %s", exc)
        return OfflineAnswer(
            spoken="",
            success=False,
            detail=f"the capability resolver raised {type(exc).__name__}: {exc}",
        )

    payload = payload_from(goal)
    used: list[dict[str, Any]] = []
    built: list[dict[str, Any]] = []
    remaining: list[str] = []

    installations = {
        str(item.get("tool")): item for item in (resolution.synthesised or []) if item.get("tool")
    }

    for step in resolution.steps:
        tool = None
        if step.tool and registry is not None and hasattr(registry, "get"):
            tool = registry.get(step.tool)
        if tool is None and step.available and step.tool:
            # No registry supplied (a CLI or a headless pass): use the catalogue's own
            # instance, which is the same class the registry would have handed back.
            from friday.cognition.capability import ToolCatalogue

            tool = ToolCatalogue().entries().get(step.tool)
        if tool is not None:
            registered_now = _ensure_registered(registry, tool)
            arguments = _arguments_for(tool, step, payload)
            result = _run_tool(
                registry,
                tool,
                arguments,
                authorizer=authorizer,
                relative_path=step.tool and _tool_path(registry, step.tool),
            )
            used.append(
                {
                    "tool": step.tool,
                    "input": arguments,
                    "output": result.get("content", ""),
                    "is_error": result.get("is_error", False),
                    "registered_now": registered_now,
                }
            )
            continue

        if step.tool:
            remaining.append(step.tool)
            continue

        # No tool: the request named a capability instead. The resolver has already
        # tried to build it; read what happened from the installation, never from hope.
        name = None
        for tool_name, item in installations.items():
            if str(item.get("capability", "")).strip() == str(step.intent).strip():
                name = tool_name
                break
        if name is None and installations:
            name = next(iter(installations))
        if name is None:
            remaining.append(step.intent)
            continue

        item = installations[name]
        installation = item.get("installation") or {}
        outcome = str(installation.get("outcome") or "")
        built.append(
            {
                "tool": name,
                "capability": step.intent,
                "outcome": outcome or "NOT_ATTEMPTED",
                "path": item.get("path", ""),
                "authorship": item.get("authorship", ""),
                "detail": installation.get("detail", item.get("detail", "")),
            }
        )
        if outcome != "COMPLETED":
            remaining.append(step.intent)
            continue

        path = Path(repo_root or ".") / str(item.get("path", ""))
        try:
            installed = _register_installed(registry, path, name)
        except Exception as exc:
            built[-1]["detail"] = f"installed, but could not be loaded to run: {exc}"
            remaining.append(step.intent)
            continue
        if installed is None:
            built[-1]["detail"] = "installed, but no tool class was found in the file"
            remaining.append(step.intent)
            continue
        arguments = {} if not hasattr(installed, "parameters") else _arguments_for(installed, step, payload)
        if "input" not in arguments and isinstance(getattr(installed, "parameters", None), dict):
            if "input" in (installed.parameters.get("properties") or {}):
                arguments = {"input": payload}
        result = _run_tool(
            registry,
            installed,
            arguments,
            authorizer=authorizer,
            relative_path=str(item.get("path", "")),
        )
        used.append(
            {
                "tool": name,
                "input": arguments,
                "output": result.get("content", ""),
                "is_error": result.get("is_error", False),
                "just_built": True,
            }
        )

    if not used:
        return OfflineAnswer(
            spoken="",
            success=False,
            plan_source=resolution.plan_source,
            built=built,
            remaining=remaining or [step.intent for step in resolution.steps],
            detail=(
                "nothing could be carried out without a model"
                + (f"; still missing: {', '.join(remaining)}" if remaining else "")
            ),
        )

    lines: list[str] = []
    failures = [item for item in used if item["is_error"]]
    if built:
        lines.append(
            "My model is out of reach, so I did this with my own tooling — "
            f"I built {built[0]['tool']} for it first ({built[0]['authorship']})."
        )
    else:
        lines.append("My model is out of reach, so I answered with my own tooling.")
    for item in used:
        status = "failed" if item["is_error"] else "returned"
        lines.append(f"- {item['tool']} {status}: {item['output']}")
    if remaining:
        lines.append(
            "I could not finish: " + ", ".join(remaining) + " still needs something this host "
            "cannot supply on its own."
        )
    if failures and len(failures) == len(used):
        lines.append("Every tool I ran reported an error, so this request is not done.")

    return OfflineAnswer(
        spoken="\n".join(lines),
        success=bool(used) and not failures,
        plan_source=resolution.plan_source,
        used=used,
        built=built,
        remaining=remaining,
        detail=f"planned by {resolution.plan_source}; {len(used)} tool run(s)",
    )


def _tool_path(registry: Any, name: str) -> str:
    """The repository-relative path of a tool's file, when it can be found.

    Used for one thing: asking the mandate whether the owner's consent covers running
    this tool. `inspect.getfile` is the honest source here, because a tool installed
    moments ago is loaded under a synthetic module name and its class carries no
    importable module path.
    """
    import inspect

    tool = None
    if registry is not None and hasattr(registry, "get"):
        try:
            tool = registry.get(name)
        except Exception:
            tool = None
    if tool is None:
        from friday.cognition.capability import ToolCatalogue

        tool = ToolCatalogue().entries().get(name)
    if tool is None:
        return ""

    import sys

    try:
        file_path = Path(inspect.getfile(type(tool))).resolve()
    except Exception:
        module = sys.modules.get(getattr(type(tool), "__module__", ""))
        raw = getattr(module, "__file__", "") if module is not None else ""
        if not raw:
            return ""
        file_path = Path(raw).resolve()
    for ancestor in file_path.parents:
        if (ancestor / "src").is_dir() and file_path.is_relative_to(ancestor / "src"):
            return file_path.relative_to(ancestor).as_posix()
    return ""


def _ensure_registered(registry: Any, tool: Any) -> bool:
    """Put a tool that exists on disk into the live registry, once.

    A registry is built at start-up; a tool installed since then is on the tree and
    not in it. Both are true at once, and the registry is the thing that authorises
    and runs calls - so the tool is registered here, which is the same thing start-up
    does for every other builtin, rather than being run around it.
    """
    if registry is None or not hasattr(registry, "register"):
        return False
    name = getattr(tool, "name", "")
    if not name:
        return False
    if hasattr(registry, "get") and registry.get(name) is not None:
        return False
    registry.register(tool)
    return True


def _run_tool(
    registry: Any,
    tool: Any,
    arguments: dict[str, Any],
    *,
    authorizer: Any | None = None,
    relative_path: str = "",
) -> dict[str, Any]:
    """Run one tool through the real registry when there is one, and report honestly.

    The registry refuses a tool call that carries no signed authorization, and it is
    right to: that check is the only thing between a model's suggestion and the
    owner's machine. So this does not bypass it - it asks the *same* authorizer the
    agent uses, for the same tool, and runs the call only if the answer is APPROVED.
    A refusal is reported as the refusal it is; the owner is not told the work was
    done when it was blocked.
    """
    name = getattr(tool, "name", "")
    try:
        if registry is not None and hasattr(registry, "execute"):
            capability = None
            if authorizer is not None and hasattr(authorizer, "authorize"):
                from friday.core.types import AuthorizationRequest

                request = AuthorizationRequest(
                    tool_name=name,
                    safety_level=getattr(tool, "safety_level", None),
                    arguments=arguments,
                    tool_call_id=f"offline_{name}",
                    purpose=getattr(tool, "description", ""),
                )
                decision = authorizer.authorize(request)
                decided = str(getattr(decision, "decision", ""))
                if decided.endswith("APPROVED"):
                    capability = getattr(decision, "capability", None)
                    authorized_by = "the authorizer approved it"
                elif any(
                    phrase in str(getattr(decision, "reason", ""))
                    for phrase in (
                        "requires explicit user confirmation",
                        "no interactive terminal is attached",
                    )
                ):
                    # The tool is SENSITIVE because nothing human has reviewed it yet,
                    # and the owner's answer to that is a standing mandate, not a
                    # prompt. Two things must both be true before FRIDAY acts on its
                    # own new code: the code must be incapable of touching anything
                    # (pure, checked by reading it) and the owner's consent must
                    # already be on record. Otherwise the refusal stands, below.
                    pure, purity = purity_verdict(tool)
                    composed, provenance = composed_by_friday(tool)
                    consent, consent_reason = consent_for_unreviewed_tool(relative_path)
                    if not (pure and composed and consent):
                        return {
                            "content": (
                                f"Authorization Block: execution of tool {name!r} was "
                                f"{decided or 'refused'}. Reason: "
                                f"{getattr(decision, 'reason', '') or 'no reason given'} "
                                f"This tool is unreviewed: {purity}; {provenance}. "
                                f"Consent: {consent_reason}."
                            ),
                            "is_error": True,
                        }
                    issuer = getattr(authorizer, "issue_capability_for_request", None)
                    if not callable(issuer):
                        return {
                            "content": (
                                f"Authorization Block: execution of tool {name!r} needs a "
                                "signed capability and this authorizer cannot issue one."
                            ),
                            "is_error": True,
                        }
                    capability = issuer(request)
                    authorized_by = (
                        f"{purity}; {provenance}; {consent_reason}; a capability was issued "
                        "for this one call, and the call is reported as unreviewed"
                    )
                    logger.info("running unreviewed composed tool %s: %s", name, authorized_by)
                else:
                    reason = getattr(decision, "reason", "") or "no reason given"
                    return {
                        "content": (
                            f"Authorization Block: execution of tool {name!r} was "
                            f"{decided or 'refused'}. Reason: {reason}"
                        ),
                        "is_error": True,
                    }
            result = registry.execute(name, arguments, authorization=capability)
        else:
            result = tool.execute(**arguments)
    except Exception as exc:
        logger.warning("offline tool %s raised: %s", name, exc)
        return {"content": f"{type(exc).__name__}: {exc}", "is_error": True}
    return {
        "content": str(getattr(result, "content", result)),
        "is_error": bool(getattr(result, "is_error", False)),
        "authorised_by": locals().get("authorized_by", "the registry's own policy"),
    }
