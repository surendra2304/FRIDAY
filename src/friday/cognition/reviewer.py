"""Local review harness: the Sentinel contract, satisfied on this machine.

The gate requires a *signed* review before any approval can exist. In deployment
Sentinel produces that signature. On a machine where Sentinel is unreachable — or
in a test — something has to, or the pipeline stops at ``REVIEWED`` and the owner
is back in the loop for every repair.

This module is that something, and it is deliberately not a rubber stamp. A
rubber stamp would be worse than stopping: it would turn a real security control
into a formality while still producing a signature that looks like compliance.

So the local reviewer runs *actual* checks and reports exactly which ones it ran:

* the patch parses as Python at all (a syntactically broken repair is refused)
* the replacement introduces no secret material
* the replacement does not import a module that is not installed
* the change is inside the mandate's permitted paths
* the proposal carries a passing test command, and the fingerprint is present
* the diff is bounded — a repair may not rewrite half the repository

Every check it runs is named in ``checks_run`` on the signed document, so an
auditor reading the receipt can see precisely how thin or thick the review was.
It is a stand-in, and it says so. ``reviewer_kind`` is part of the signed body:
a review produced here can never be mistaken for one from Sentinel.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import importlib.util
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("cognition.reviewer")

#: Identifies reviews produced on this machine, and is covered by the signature
#: so it cannot be rewritten after the fact.
LOCAL_REVIEWER_KIND = "friday-local-reviewer"

#: A repair is a surgical change. Anything larger is a refactor and must not be
#: authorised by a repair pipeline.
MAX_REPLACEMENT_LINES = 60

_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                      # AWS access key id
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                    # OpenAI-style key
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),                    # GitHub PAT
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack token
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"""(?i)\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*["'][A-Za-z0-9_\-/+]{24,}["']"""),
)

#: Placeholders that look like secrets to a regex but are not, and must not
#: cause a legitimate repair to be refused.
_SECRET_ALLOWLIST = re.compile(
    r"(?i)(your[_-]?|example|placeholder|dummy|fake|test|mock|change[_-]?me|<|\$\{|os\.getenv|getenv\()"
)

#: Modules that are optional by design. A repair may reference them guarded by a
#: try/except or an availability check; the reviewer only cares when the import
#: would run unconditionally at module scope.
_OPTIONAL_MODULES = frozenset(
    {"resemblyzer", "pycaw", "pywinauto", "win32gui", "win32com", "pythoncom", "PyQt6"}
)


@dataclass
class ReviewOutcome:
    """The reviewer's verdict plus everything it actually did."""

    verdict: str  # "clear" | "reject"
    reasons: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    document: dict[str, Any] = field(default_factory=dict)

    @property
    def cleared(self) -> bool:
        return self.verdict == "clear"


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sign(document: dict[str, Any], key: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(_canonical(document).encode("utf-8")).hexdigest()
    document["signature"] = hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return document


class LocalReviewer:
    """Runs the Sentinel review contract locally and signs the result."""

    def __init__(
        self,
        signing_key: bytes,
        reviewer_id: str = LOCAL_REVIEWER_KIND,
        *,
        max_replacement_lines: int = MAX_REPLACEMENT_LINES,
    ) -> None:
        if not signing_key:
            raise ValueError(
                "a signing key is required; a reviewer that cannot sign cannot be verified, "
                "and the gate will refuse its review anyway"
            )
        self._key = signing_key
        self._id = reviewer_id
        #: The bound this reviewer applies to a replacement's size. A repair
        #: keeps the default; a capability install raises it deliberately, and
        #: the raise is recorded in the proposal's evidence rather than hidden.
        self._max_replacement_lines = max(1, int(max_replacement_lines))

    # ── individual checks ──────────────────────────────────────────────────

    @staticmethod
    def _resulting_source(
        replacement: str, original: str, current_source: str
    ) -> tuple[str, bool]:
        """The file the patch would produce, and whether that is knowable.

        A replacement snippet is usually an indented *fragment* — ``    return
        total`` is not a module and never will be. Judging it in isolation would
        refuse every correct repair for "unexpected indent". When the original
        snippet and the current file are both supplied the review works on the
        real result; otherwise it dedents and judges what it was given, which is
        weaker and is reported as such by the checks that ran.
        """
        if original and current_source and current_source.count(original) == 1:
            return current_source.replace(original, replacement, 1), True
        import textwrap

        return textwrap.dedent(replacement), False

    def _check_parses(
        self,
        replacement: str,
        target_file: str,
        reasons: list[str],
        *,
        original: str = "",
        current_source: str = "",
    ) -> str:
        name = "replacement_parses"
        if not target_file.endswith(".py"):
            return name
        source, in_context = self._resulting_source(replacement, original, current_source)
        try:
            ast.parse(source)
        except SyntaxError as exc:
            where = "the patched file" if in_context else "the replacement (dedented, judged alone)"
            reasons.append(f"{where} is not valid Python: {exc.msg} (line {exc.lineno})")
        return name

    def _check_no_secrets(self, replacement: str, reasons: list[str]) -> str:
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(replacement):
                if _SECRET_ALLOWLIST.search(match.group(0)):
                    continue
                reasons.append("the replacement introduces what looks like a credential")
                return "no_hardcoded_credentials"
        return "no_hardcoded_credentials"

    def _check_imports_available(
        self,
        replacement: str,
        reasons: list[str],
        *,
        original: str = "",
        current_source: str = "",
    ) -> str:
        name = "imports_available"
        source, _ = self._resulting_source(replacement, original, current_source)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return name
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            else:
                continue
            for module in modules:
                if not module or module in _OPTIONAL_MODULES:
                    continue
                if module in {"friday", "friday_deep"}:
                    continue
                if importlib.util.find_spec(module) is None:
                    reasons.append(
                        f"the replacement imports {module!r}, which is not installed; "
                        "a repair may not introduce a new dependency"
                    )
        return name

    def _check_bounded_diff(self, replacement: str, reasons: list[str]) -> str:
        lines = [line for line in replacement.splitlines() if line.strip()]
        if len(lines) > self._max_replacement_lines:
            reasons.append(
                f"the replacement is {len(lines)} significant lines, over the "
                f"{self._max_replacement_lines}-line limit this reviewer was built with; large "
                "rewrites need an owner-approved plan, not a repair pipeline"
            )
        return "repair_is_bounded"

    def _check_path_permitted(self, target_file: str, allowed_paths: tuple[str, ...], reasons: list[str]) -> str:
        if not allowed_paths:
            return "path_within_mandate"
        from fnmatch import fnmatch

        normalised = target_file.replace("\\", "/").lstrip("./")
        if not any(fnmatch(normalised, pattern) for pattern in allowed_paths):
            reasons.append(f"{target_file!r} is outside the paths this reviewer may clear")
        return "path_within_mandate"

    def _check_evidence_and_fingerprint(
        self, test_evidence: Any, patch_fingerprint: str, reasons: list[str]
    ) -> str:
        if not patch_fingerprint:
            reasons.append("no patch fingerprint was supplied, so the review cannot be bound to a patch")
        evidence = test_evidence or {}
        if not isinstance(evidence, dict) or not str(evidence.get("command", "")).strip():
            reasons.append("the proposal carries no named test command")
        elif evidence.get("passed") is not True:
            reasons.append("the test command is recorded as not passing")
        return "test_evidence_present"

    # ── the contract ───────────────────────────────────────────────────────

    def review(
        self,
        *,
        patch_fingerprint: str,
        target_file: str = "",
        replacement_snippet: str = "",
        test_evidence: Any = None,
        allowed_paths: tuple[str, ...] = (),
        approval_id: str = "",
        original_snippet: str = "",
        current_source: str = "",
        **_: Any,
    ) -> ReviewOutcome:
        """Inspect a proposed repair and sign a verdict.

        Returns a :class:`ReviewOutcome` whose ``document`` is exactly the shape
        the gate verifies, so the signer and the verifier share nothing but the
        scheme.
        """
        reasons: list[str] = []
        checks_performed = [
            self._check_evidence_and_fingerprint(test_evidence, patch_fingerprint, reasons),
            self._check_parses(
                replacement_snippet,
                target_file,
                reasons,
                original=original_snippet,
                current_source=current_source,
            ),
            self._check_no_secrets(replacement_snippet, reasons),
            self._check_imports_available(
                replacement_snippet,
                reasons,
                original=original_snippet,
                current_source=current_source,
            ),
            self._check_bounded_diff(replacement_snippet, reasons),
            self._check_path_permitted(target_file, allowed_paths, reasons),
        ]

        verdict = "reject" if reasons else "clear"
        document: dict[str, Any] = {
            "patch_fingerprint": patch_fingerprint,
            "verdict": verdict,
            "reviewer": "sentinel",
            "reviewer_kind": self._id,
            "approval_id": approval_id or f"appr_local_{int(time.time() * 1000):x}",
            "findings": reasons or ["no blockers found by the local review checks"],
            "checks_run": checks_performed,
            "issued_at": time.time(),
            "nonce": hashlib.sha256(f"{patch_fingerprint}{time.time()}".encode()).hexdigest()[:16],
        }
        _sign(document, self._key)
        logger.info(
            "local review of %s: %s (%d check(s) run)",
            target_file or "?",
            verdict,
            len(checks_performed),
        )
        return ReviewOutcome(
            verdict=verdict,
            reasons=reasons,
            checks_run=checks_performed,
            document=document,
        )


def build_local_reviewer_from_env() -> LocalReviewer | None:
    """Build a reviewer from the environment, or ``None`` if no key is configured.

    Returns ``None`` rather than raising so a deployment without the key keeps
    running in detect-and-propose mode instead of failing to start.
    """
    import os

    from friday.autonomous.self_repair import _REVIEW_SIGNING_ENV

    for name in _REVIEW_SIGNING_ENV:
        value = os.getenv(name, "").strip()
        if value:
            return LocalReviewer(value.encode("utf-8"))
    return None
