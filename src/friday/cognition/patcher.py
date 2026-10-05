"""Turning a diagnosed failure into a candidate repair.

Two backends, one contract:

* :class:`RulePatcher` recognises failure shapes it can fix **deterministically**
  and offline. It never guesses: when no rule matches it returns no candidate,
  which is a truthful "I do not know how to fix this" rather than a coin flip.
* :class:`LLMPatcher` asks the configured language model for a minimal patch. It
  is used when a model is reachable, and it is *only* ever a source of
  candidates — the gate's test evidence requirement is what decides whether a
  candidate is real.

Nothing here applies a change. A :class:`PatchCandidate` is a hypothesis, and the
pipeline's job is to falsify it by running the tests before anyone trusts it.

The offline rules exist because the most common autonomous repair is not exotic:
a module imports something absent, a name is misspelled, an optional dependency
is imported unguarded, a stale attribute is read. Those are fixable without a
model, and a system that can only fix them with a model is not autonomous — it is
networked.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("cognition.patcher")


@dataclass
class PatchCandidate:
    """A proposed change to one file, with the reasoning that produced it."""

    target_file: str
    original_snippet: str
    replacement_snippet: str
    rationale: str
    confidence: str = "medium"  # high = a deterministic rewrite, low = a guess
    backend: str = "rule"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_file": self.target_file,
            "original_snippet": self.original_snippet,
            "replacement_snippet": self.replacement_snippet,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "backend": self.backend,
            "notes": list(self.notes),
        }


@dataclass
class FailureReport:
    """What a failing test run told us, in a form a patcher can reason about."""

    test_node_id: str = ""
    test_file: str = ""
    message: str = ""
    exception_type: str = ""
    exception_value: str = ""
    source_file: str = ""
    source_line: int = 0
    traceback_text: str = ""

    def summary(self) -> str:
        if self.test_node_id:
            return f"{self.test_node_id}: {self.exception_type}: {self.exception_value}".strip(": ")
        return self.message or "unknown failure"


# ── parsing a pytest run ───────────────────────────────────────────────────


#: `FAILED node::test - Exception: message` from the short summary.
_HEADER = re.compile(
    r"^(?P<kind>FAILED|ERROR)\s+(?P<node>[\w./\\:\[\]\-]+)"
    r"(?:\s+-\s+(?P<detail>.*))?$"
)
#: `_______ test_name _______` — the divider that opens a failure's traceback.
#: This, not the summary line, is what tells us whose body is being printed.
_DIVIDER = re.compile(r"^_+\s*(?P<name>[\w.\[\]\-]+)\s*_+$")
_LOCATION = re.compile(r"^(?P<file>[\w./\\\-]+\.py):(?P<line>\d+):")
_EXCEPTION = re.compile(r"^E\s+(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit))\b:?\s*(?P<value>.*)$")
_EXCEPTION_BARE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception))\s*:\s*(?P<value>.+)$")
_MODULE_NOT_FOUND = re.compile(r"No module named '?(?P<module>[\w.]+)'?")
_NAME_ERROR = re.compile(r"name '(?P<name>\w+)' is not defined")
_ATTRIBUTE_ERROR = re.compile(r"'(?P<obj>\w+)' object has no attribute '(?P<attr>\w+)'")
_IMPORT_ERROR = re.compile(r"cannot import name '(?P<name>\w+)' from '(?P<module>[\w.]+)'")


def parse_pytest_output(output: str, repo_root: str | Path = ".") -> list[FailureReport]:
    """Extract structured failures from real pytest output.

    Parsing text is unfashionable, but it is what the tool actually emits, and a
    parser that admits what it could not understand beats one that invents a
    failure shape it never saw.

    Two pytest facts shape this function, and getting either wrong silently
    produces reports with no traceback — which read exactly like "unfixable":

    * The traceback bodies come **before** the ``FAILED ...`` summary lines, so a
      single forward pass that only starts collecting at ``FAILED`` collects
      nothing. The ``_____ name _____`` dividers are what identify a body.
    * A divider names the test by its *function* name, while the summary names the
      full node id. The two are joined at the end.
    """
    root = Path(repo_root)
    by_name: dict[str, FailureReport] = {}
    order: list[str] = []
    node_ids: dict[str, str] = {}
    current: FailureReport | None = None

    for raw_line in output.splitlines():
        stripped = raw_line.strip()

        divider = _DIVIDER.match(stripped)
        if divider:
            name = divider.group("name")
            current = by_name.get(name)
            if current is None:
                current = FailureReport(test_node_id=name)
                by_name[name] = current
                order.append(name)
            continue

        header = _HEADER.match(stripped)
        if header:
            node = header.group("node")
            function_name = node.split("::")[-1].split("[")[0]
            node_ids[function_name] = node
            report = by_name.get(function_name)
            if report is None:
                report = FailureReport(test_node_id=node)
                by_name[function_name] = report
                order.append(function_name)
            report.test_file = node.split("::")[0]
            detail = (header.group("detail") or "").strip()
            if detail and not report.exception_type:
                parsed = _EXCEPTION_BARE.match(detail)
                if parsed:
                    report.exception_type = parsed.group("type")
                    report.exception_value = parsed.group("value").strip()
                else:
                    report.message = detail
            current = report
            continue

        location = _LOCATION.match(stripped)
        if location and current is not None:
            candidate_path = location.group("file")
            if candidate_path.endswith(".py") and "test" not in Path(candidate_path).name:
                current.source_file = candidate_path
                current.source_line = int(location.group("line"))
            continue

        exception = _EXCEPTION.match(raw_line)
        if exception and current is not None and not current.exception_type:
            current.exception_type = exception.group("type")
            current.exception_value = exception.group("value").strip()
            current.traceback_text += raw_line + "\n"
            continue

        if current is not None:
            current.traceback_text += raw_line + "\n"

    reports = [by_name[name] for name in order]
    for report in reports:
        if report.test_node_id in node_ids.values():
            continue
        resolved_node = node_ids.get(report.test_node_id.split("[")[0])
        if resolved_node:
            report.test_node_id = resolved_node
        if not report.test_file and "::" in report.test_node_id:
            report.test_file = report.test_node_id.split("::")[0]

    # Attach the primary source file from the traceback when pytest did not print
    # a location line, which happens for import-time failures.
    for report in reports:
        if not report.source_file:
            for match in re.finditer(r'File "([^"]+\.py)", line (\d+)', report.traceback_text):
                candidate = match.group(1)
                if "site-packages" in candidate:
                    continue
                try:
                    resolved = Path(candidate).resolve()
                except (OSError, ValueError):
                    continue
                if root.resolve() in resolved.parents:
                    report.source_file = candidate
                    report.source_line = int(match.group(2))
                    break
    return [report for report in reports if report.test_node_id]


# ── deterministic rules ────────────────────────────────────────────────────


class RulePatcher:
    """Fixes failure shapes it recognises exactly, and declines the rest."""

    name = "rule"

    def candidate_for(
        self,
        report: FailureReport,
        *,
        repo_root: str | Path = ".",
        current_source: str = "",
        allowed_paths: tuple[str, ...] = (),
    ) -> PatchCandidate | None:
        if not current_source or not report.source_file:
            return None

        for rule in (
            self._fix_undefined_name,
            self._fix_missing_module_import,
            self._fix_unguarded_optional_import,
            self._fix_missing_attribute,
        ):
            candidate = rule(report, current_source, report.source_file, allowed_paths)
            if candidate is not None:
                logger.info(
                    "rule %s produced a candidate for %s",
                    rule.__name__,
                    report.source_file,
                )
                return candidate
        return None

    # -- individual rules --------------------------------------------------

    def _fix_undefined_name(
        self,
        report: FailureReport,
        source: str,
        target: str,
        allowed_paths: tuple[str, ...],
    ) -> PatchCandidate | None:
        """A `name ... is not defined` caused by a typo of a name defined nearby.

        Only fires when exactly one near-miss name exists in the same file, so it
        can never pick between two plausible spellings.
        """
        match = _NAME_ERROR.search(report.exception_value)
        if not match:
            return None
        missing = match.group("name")

        defined = set()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if isinstance(target_node, ast.Name):
                        defined.add(target_node.id)

        near = [name for name in defined if _is_near_miss(missing, name)]
        if len(near) != 1:
            return None
        correct = near[0]
        if f" {missing}" not in source and f"({missing}" not in source and f"{missing}." not in source:
            return None

        original = _line_containing(source, missing)
        if not original:
            return None
        replacement = original.replace(missing, correct)
        return PatchCandidate(
            target_file=target,
            original_snippet=original,
            replacement_snippet=replacement,
            rationale=(
                f"`{missing}` is not defined; the only near-miss name defined in this file is "
                f"`{correct}`, so the reference is a typo of it."
            ),
            confidence="high",
            backend=self.name,
            notes=[f"undefined name {missing!r} -> {correct!r}"],
        )

    def _fix_missing_module_import(
        self,
        report: FailureReport,
        source: str,
        target: str,
        allowed_paths: tuple[str, ...],
    ) -> PatchCandidate | None:
        """A module the file uses but never imports, where that module is installed."""
        combined = f"{report.exception_value}\n{report.traceback_text}"
        match = _MODULE_NOT_FOUND.search(combined)
        if not match:
            return None
        module = match.group("module").split(".")[0]

        import importlib.util

        if importlib.util.find_spec(module) is None:
            # The dependency genuinely is not installed. Adding an import would
            # convert a clear error into a worse one.
            return None
        if re.search(rf"^\s*(?:import|from)\s+{re.escape(module)}\b", source, re.MULTILINE):
            return None
        if not re.search(rf"\b{re.escape(module)}\.", source):
            return None

        lines = source.splitlines()
        insert_at = 0
        for index, line in enumerate(lines[:60]):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) or stripped.startswith('"""') or stripped.startswith("#"):
                insert_at = index + 1
            elif stripped.startswith(("def ", "class ")) and index > 0:
                break
        original = lines[insert_at] if insert_at < len(lines) else ""
        if not original:
            return None
        replacement = f"import {module}\n{original}"

        return PatchCandidate(
            target_file=target,
            original_snippet=original,
            replacement_snippet=replacement,
            rationale=(
                f"{target} uses `{module}` without importing it; the module is installed, "
                "so the missing import is the defect."
            ),
            confidence="high",
            backend=self.name,
            notes=[f"added `import {module}`"],
        )

    def _fix_unguarded_optional_import(
        self,
        report: FailureReport,
        source: str,
        target: str,
        allowed_paths: tuple[str, ...],
    ) -> PatchCandidate | None:
        """An optional dependency imported at module scope kills the whole import.

        The fix is to make the import lazy, which is the pattern the rest of this
        codebase already uses for exactly these packages.
        """
        combined = f"{report.exception_value}\n{report.traceback_text}"
        match = _MODULE_NOT_FOUND.search(combined)
        if not match:
            return None
        module = match.group("module").split(".")[0]

        from friday.cognition.reviewer import _OPTIONAL_MODULES  # single source of truth

        if module not in _OPTIONAL_MODULES:
            return None

        pattern = re.compile(rf"^import {re.escape(module)}\s*$", re.MULTILINE)
        found = pattern.search(source)
        if not found:
            return None
        original = found.group(0)
        replacement = (
            f"# {module} is optional: imported lazily so its absence cannot break this module.\n"
            f'# See friday.cognition.patcher._fix_unguarded_optional_import.\n'
            f"def _load_{module}() -> object:\n"
            f'    import {module}  # noqa: PLC0415 - deliberately deferred\n'
            f"    return {module}"
        )
        return PatchCandidate(
            target_file=target,
            original_snippet=original,
            replacement_snippet=replacement,
            rationale=(
                f"`import {module}` at module scope makes an optional dependency mandatory; "
                "deferring the import keeps the module loadable without it."
            ),
            confidence="high",
            backend=self.name,
            notes=[f"deferred optional import of {module}"],
        )

    def _fix_missing_attribute(
        self,
        report: FailureReport,
        source: str,
        target: str,
        allowed_paths: tuple[str, ...],
    ) -> PatchCandidate | None:
        """A renamed attribute, when the class in this very file defines the new name."""
        match = _ATTRIBUTE_ERROR.search(report.exception_value)
        if not match:
            return None
        obj, attr = match.group("obj"), match.group("attr")

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        defined_attrs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        defined_attrs.add(item.name)
                    elif isinstance(item, ast.Assign):
                        for t in item.targets:
                            if isinstance(t, ast.Name):
                                defined_attrs.add(t.id)

        near = [name for name in defined_attrs if name != attr and _is_near_miss(attr, name)]
        if len(near) != 1:
            return None
        correct = near[0]

        original = _line_containing(source, f".{attr}")
        if not original:
            return None
        return PatchCandidate(
            target_file=target,
            original_snippet=original,
            replacement_snippet=original.replace(f".{attr}", f".{correct}"),
            rationale=(
                f"{obj!r} has no attribute {attr!r}; this file defines {correct!r}, which is "
                "the only close match, so the call site is stale."
            ),
            confidence="medium",
            backend=self.name,
            notes=[f"{attr!r} -> {correct!r}"],
        )


def _is_near_miss(a: str, b: str, *, max_distance: int = 2) -> bool:
    """Cheap edit-distance test used to decide whether a rename is plausible."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > max_distance:
        return False
    if a.lower() == b.lower():
        return True
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1] <= max_distance


def _line_containing(source: str, needle: str, *, max_line_length: int = 200) -> str:
    """Return the first line containing ``needle``, stripped of indentation noise.

    The gate matches snippets literally, so the whole line is returned as-is
    rather than a fragment, and a line that is too long to be a sensible snippet
    is refused instead of truncated into something that will not match.
    """
    for line in source.splitlines():
        if needle in line and len(line) <= max_line_length:
            return line
    return ""


# ── model-backed patching ──────────────────────────────────────────────────


PATCH_SYSTEM_PROMPT = """You repair a Python codebase. You are given one failing test \
and the current content of the file the traceback points at.

Reply with EXACTLY two fenced blocks and nothing else:

<original>
the exact lines from the file that must be replaced, copied byte for byte, \
including leading indentation, and appearing exactly once in the file
</original>
<replacement>
the replacement lines
</replacement>
<rationale>
one sentence explaining the defect
</rationale>

Rules:
- Make the smallest change that fixes the failure.
- The <original> block must match the file verbatim. If you cannot quote it exactly, reply NO_FIX.
- Never add a dependency, never delete a test, never weaken an assertion.
- If the failure is environmental or you are unsure, reply NO_FIX.
"""


class LLMPatcher:
    """Asks a configured model for a minimal patch. Candidates only, never truth."""

    name = "llm"

    def __init__(self, provider: Any | None = None) -> None:
        self._provider = provider

    def _get_provider(self) -> Any | None:
        if self._provider is not None:
            return self._provider
        try:
            from friday.core.config import get_settings
            from friday.llm.factory import create_llm_provider

            self._provider = create_llm_provider(get_settings())
        except Exception as exc:  # a model is a convenience, never a requirement
            logger.warning("no LLM available for patch synthesis: %s", exc)
            self._provider = None
        return self._provider

    def candidate_for(
        self,
        report: FailureReport,
        *,
        repo_root: str | Path = ".",
        current_source: str = "",
        allowed_paths: tuple[str, ...] = (),
    ) -> PatchCandidate | None:
        provider = self._get_provider()
        if provider is None or not current_source or not report.source_file:
            return None

        from friday.core.types import Message, Role

        prompt = (
            f"Test: {report.test_node_id}\n"
            f"Exception: {report.exception_type}: {report.exception_value}\n"
            f"File to repair: {report.source_file}\n\n"
            f"--- current content of {report.source_file} ---\n{current_source}\n"
        )
        try:
            response = provider.generate(
                [
                    Message(role=Role.SYSTEM, content=PATCH_SYSTEM_PROMPT),
                    Message(role=Role.USER, content=prompt),
                ]
            )
        except Exception as exc:
            logger.warning("patch synthesis failed: %s", exc)
            return None

        content = getattr(response, "content", "") or ""
        if "NO_FIX" in content:
            return None

        blocks = {}
        for tag in ("original", "replacement", "rationale"):
            match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", content, re.DOTALL)
            if match:
                blocks[tag] = match.group(1)
        if set(blocks) != {"original", "replacement", "rationale"}:
            return None
        if current_source.count(blocks["original"]) != 1:
            # Ambiguous or absent. The gate would refuse it and the reviewer flags
            # it; declining here keeps the failure honest and cheap.
            return None

        return PatchCandidate(
            target_file=report.source_file,
            original_snippet=blocks["original"],
            replacement_snippet=blocks["replacement"],
            rationale=blocks["rationale"].strip(),
            confidence="low",
            backend=self.name,
            notes=["proposed by a language model; unverified until the tests pass"],
        )


class CompositePatcher:
    """Rules first, then the model. The cheap, exact answer wins when it exists."""

    def __init__(self, patchers: list[Any] | None = None) -> None:
        self._patchers = patchers if patchers is not None else [RulePatcher(), LLMPatcher()]

    def candidate_for(self, report: FailureReport, **kwargs: Any) -> PatchCandidate | None:
        for patcher in self._patchers:
            candidate = patcher.candidate_for(report, **kwargs)
            if candidate is not None:
                return candidate
        return None

    def all_candidates(self, report: FailureReport, **kwargs: Any) -> list[PatchCandidate]:
        found: list[PatchCandidate] = []
        for patcher in self._patchers:
            candidate = patcher.candidate_for(report, **kwargs)
            if candidate is not None:
                found.append(candidate)
        return found
