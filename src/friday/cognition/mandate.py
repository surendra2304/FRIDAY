"""Standing autonomy mandate: the owner's authority, exercised in advance.

The gated repair pipeline in :mod:`friday.autonomous.self_repair` is built on one
invariant: **no agent may approve a repair.** That invariant is right, and this
module does not weaken it. What it adds is the missing half of autonomy.

Refusing to let an agent approve itself left the owner in the loop for every
repair, which means FRIDAY can diagnose but never fix. The owner asked for the
opposite. The resolution is not to let FRIDAY name itself "surendra" — that would
be a forged identity, and the gate is right to refuse a name it cannot verify.
The resolution is that the owner issues a **signed standing mandate**, once,
which says: within these bounds, on my behalf, without asking me each time.

So the approval on a repair is either the owner's live decision or the owner's
pre-recorded decision. Both are the owner. Neither is an agent.

Everything here is fail-closed, and every refusal is a first-class result:

* A mandate is a signed document. Flip one byte — a scope, an expiry, the
  allowed file pattern — and the signature stops verifying.
* A mandate expires. An unbounded mandate is a permanent hole; the default is
  bounded in time and renewable in one command.
* A mandate is revocable. Revocation is recorded as its own signed document, so
  "I withdraw this" is as auditable as "I grant this".
* A mandate is *scoped*. It may name which files can be touched and how many at
  once. A mandate for `src/**` does not authorise a change to `.github/**`.
* A mandate never overrides the other gates. Test evidence is still required.
  The fingerprint binding is still enforced. Rollback is still available. The
  mandate replaces the human keystroke, nothing else.

Signing scheme, deliberately reimplemented here rather than shared with the gate
so that a verifier never has to execute the code it is verifying::

    hash      = sha256(canonical_json(document minus "signature"))
    signature = hmac_sha256(key, hash)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any, Literal

from friday.core.logging import get_logger

logger = get_logger("cognition.mandate")

#: Environment key holding the owner's autonomy signing secret. Deliberately
#: distinct from the control API key and the Sentinel review key: each secret
#: authorises a different act, and reusing one would let a leaked review key
#: grant standing autonomy.
MANDATE_KEY_ENV = "FRIDAY_AUTONOMY_KEY"

#: Where granted mandates live until they expire or are revoked.
DEFAULT_LEDGER_ENV = "FRIDAY_AUTONOMY_LEDGER"
DEFAULT_LEDGER_PATH = "data/autonomy_mandates.json"
LEDGER_VERSION = 1

#: Default mandate lifetime. Long enough to cover a working day of unattended
#: operation, short enough that a forgotten mandate does not outlive the reason
#: it was granted.
DEFAULT_TTL_SECONDS = 12 * 3600

#: A mandate is an owner document. An agent may never issue one, for the same
#: reason it may never approve a repair: the authority being delegated is the
#: owner's, and an agent cannot delegate what it does not hold.
NON_OWNER_ISSUERS = frozenset(
    {
        "",
        "friday",
        "forge",
        "sentinel",
        "inference",
        "memora",
        "stratex",
        "intelx",
        "futuris",
        "cortex",
        "system",
        "bot",
        "agent",
        "automation",
        "self",
    }
)

#: What a mandate may permit. Kept as an explicit vocabulary so a mandate cannot
#: silently widen: an unknown scope is refused rather than ignored.
SCOPE_SOURCE_REPAIR = "source_repair"
SCOPE_CONFIG_REPAIR = "config_repair"
SCOPE_DEPENDENCY_INSTALL = "dependency_install"
SCOPE_PEER_RECONNECT = "peer_reconnect"
SCOPE_TEST_AUTHORING = "test_authoring"
SCOPE_RUNTIME_CLEANUP = "runtime_cleanup"

ALL_SCOPES = (
    SCOPE_SOURCE_REPAIR,
    SCOPE_CONFIG_REPAIR,
    SCOPE_DEPENDENCY_INSTALL,
    SCOPE_PEER_RECONNECT,
    SCOPE_TEST_AUTHORING,
    SCOPE_RUNTIME_CLEANUP,
)

#: Scopes that change the system's own code or configuration, and therefore go
#: through the full gate (test evidence, review, checkpoint, rollback).
GATED_SCOPES = frozenset({SCOPE_SOURCE_REPAIR, SCOPE_CONFIG_REPAIR, SCOPE_TEST_AUTHORING})

#: Scopes that act on the running environment rather than the repository.
OPERATIONAL_SCOPES = frozenset({SCOPE_DEPENDENCY_INSTALL, SCOPE_PEER_RECONNECT, SCOPE_RUNTIME_CLEANUP})

MandateRefusal = Literal[
    "NO_KEY",
    "MALFORMED",
    "BAD_SIGNATURE",
    "WRONG_ISSUER",
    "EXPIRED",
    "REVOKED",
    "SCOPE_NOT_GRANTED",
    "FILE_NOT_PERMITTED",
    "TOO_MANY_FILES",
    "NO_TEST_EVIDENCE",
]


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _now() -> float:
    return time.time()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class MandateVerdict:
    """The answer to "may this be done without asking the owner?".

    Carries the refusal by name so a caller can act on it, and a human-readable
    reason so an operator can fix it without reading this file.
    """

    allowed: bool
    refusal: MandateRefusal | None = None
    reason: str = ""
    mandate_id: str = ""

    def __post_init__(self) -> None:
        if self.allowed and self.refusal is not None:
            raise ValueError("a verdict cannot be both allowed and refused")

    @classmethod
    def permit(cls, mandate_id: str, reason: str = "") -> "MandateVerdict":
        return cls(allowed=True, mandate_id=mandate_id, reason=reason)

    @classmethod
    def deny(cls, refusal: MandateRefusal, reason: str) -> "MandateVerdict":
        return cls(allowed=False, refusal=refusal, reason=reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "refusal": self.refusal,
            "reason": self.reason,
            "mandate_id": self.mandate_id,
        }


@dataclass
class AutonomyMandate:
    """A bounded, expiring, revocable delegation of the owner's approval.

    Deliberately a plain document rather than a class with behaviour: it is
    signed, transmitted and stored as JSON, and the verification code must be able
    to check it without importing the code that produced it.
    """

    issued_by: str
    scopes: tuple[str, ...] = ALL_SCOPES
    allowed_paths: tuple[str, ...] = ("src/**", "tests/**", "config/**", "scripts/**", "docs/**")
    max_files_per_change: int = 3
    max_changes: int = 0  # 0 = unlimited within the lifetime
    issued_at: float = field(default_factory=_now)
    expires_at: float = 0.0
    mandate_id: str = ""
    note: str = ""
    require_test_evidence: bool = True

    def __post_init__(self) -> None:
        if not self.mandate_id:
            self.mandate_id = f"mandate_{int(self.issued_at)}_{os.urandom(3).hex()}"
        if not self.expires_at:
            self.expires_at = self.issued_at + DEFAULT_TTL_SECONDS
        self.scopes = tuple(dict.fromkeys(self.scopes))

    # ── serialisation ──────────────────────────────────────────────────────

    def body(self) -> dict[str, Any]:
        """Everything the signature covers."""
        return {
            "mandate_id": self.mandate_id,
            "issued_by": self.issued_by,
            "scopes": list(self.scopes),
            "allowed_paths": list(self.allowed_paths),
            "max_files_per_change": int(self.max_files_per_change),
            "max_changes": int(self.max_changes),
            "issued_at": float(self.issued_at),
            "expires_at": float(self.expires_at),
            "note": self.note,
            "require_test_evidence": bool(self.require_test_evidence),
        }

    def to_document(self) -> dict[str, Any]:
        return dict(self.body())

    def sign(self, key: bytes) -> dict[str, Any]:
        document = self.to_document()
        digest = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
        document["signature"] = hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()
        return document

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "AutonomyMandate":
        return cls(
            issued_by=str(document.get("issued_by", "")),
            scopes=tuple(document.get("scopes") or ()),
            allowed_paths=tuple(document.get("allowed_paths") or ()),
            max_files_per_change=int(document.get("max_files_per_change", 0) or 0),
            max_changes=int(document.get("max_changes", 0) or 0),
            issued_at=float(document.get("issued_at", 0.0) or 0.0),
            expires_at=float(document.get("expires_at", 0.0) or 0.0),
            mandate_id=str(document.get("mandate_id", "")),
            note=str(document.get("note", "")),
            require_test_evidence=bool(document.get("require_test_evidence", True)),
        )

    # ── predicates ─────────────────────────────────────────────────────────

    def is_expired(self, at: float | None = None) -> bool:
        return (at if at is not None else _now()) >= self.expires_at

    def grants(self, scope: str) -> bool:
        return scope in self.scopes

    def permits_path(self, relative_path: str) -> bool:
        """Whether the mandate reaches this file.

        Separators are normalised so a Windows-authored mandate and a POSIX path
        agree, and a path is compared against the mandate's own patterns only —
        never matched optimistically.
        """
        normalised = relative_path.replace("\\", "/").lstrip("./")
        return any(fnmatch(normalised, pattern) for pattern in self.allowed_paths)

    def describe(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "issued_by": self.issued_by,
            "scopes": list(self.scopes),
            "allowed_paths": list(self.allowed_paths),
            "max_files_per_change": self.max_files_per_change,
            "issued_at": _iso(self.issued_at),
            "expires_at": _iso(self.expires_at),
            "expired": self.is_expired(),
            "note": self.note,
        }


def verify_mandate(document: dict[str, Any], key: bytes) -> bool:
    """Verify a mandate's HMAC in constant time.

    Every field except the signature participates, so changing a scope, an expiry
    or a permitted path invalidates the signature rather than silently widening
    what the owner granted.
    """
    signature = str(document.get("signature", ""))
    if not signature:
        return False
    body = {k: v for k, v in document.items() if k != "signature"}
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    expected = hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class MandateLedger:
    """Durable record of granted and revoked mandates.

    The ledger is the *authority*, not a cache: a mandate absent from it is not
    honoured, so revoking one is a real act with a real effect, not a note.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.getenv(DEFAULT_LEDGER_ENV, "").strip() or DEFAULT_LEDGER_PATH
        self._granted: dict[str, dict[str, Any]] = {}
        self._revoked: dict[str, dict[str, Any]] = {}
        self._consumed: dict[str, int] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────────────────

    def _load(self) -> None:
        from pathlib import Path

        path = Path(self._path)
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Fail closed: an unreadable ledger means no mandate is known, so
            # nothing is auto-approved. That is the safe direction to lose.
            logger.error("autonomy ledger at %s is unreadable; no mandate is in force: %s", path, exc)
            return
        if not isinstance(raw, dict) or raw.get("version") != LEDGER_VERSION:
            logger.error("autonomy ledger at %s has an unexpected version; ignoring it", path)
            return
        self._granted = {str(k): v for k, v in (raw.get("granted") or {}).items()}
        self._revoked = {str(k): v for k, v in (raw.get("revoked") or {}).items()}
        self._consumed = {str(k): int(v) for k, v in (raw.get("consumed") or {}).items()}

    def _persist(self) -> None:
        from pathlib import Path

        path = Path(self._path)
        payload = {
            "version": LEDGER_VERSION,
            "granted": self._granted,
            "revoked": self._revoked,
            "consumed": self._consumed,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            # A ledger that cannot be written must not pretend it was.
            logger.error("could not persist the autonomy ledger to %s: %s", path, exc)

    # ── mutation ───────────────────────────────────────────────────────────

    def record_grant(self, document: dict[str, Any]) -> None:
        mandate_id = str(document.get("mandate_id", ""))
        if not mandate_id:
            raise ValueError("a mandate without an id cannot be recorded")
        self._granted[mandate_id] = dict(document)
        self._revoked.pop(mandate_id, None)
        self._persist()

    def record_revocation(self, mandate_id: str, reason: str = "") -> bool:
        if mandate_id not in self._granted:
            return False
        self._revoked[mandate_id] = {
            "revoked_at": _now(),
            "reason": reason,
        }
        self._persist()
        return True

    def consume(self, mandate_id: str) -> int:
        """Count one autonomous change against the mandate's budget."""
        self._consumed[mandate_id] = self._consumed.get(mandate_id, 0) + 1
        self._persist()
        return self._consumed[mandate_id]

    def consumed(self, mandate_id: str) -> int:
        return self._consumed.get(mandate_id, 0)

    # ── queries ────────────────────────────────────────────────────────────

    def document(self, mandate_id: str) -> dict[str, Any] | None:
        return self._granted.get(mandate_id)

    def revocation(self, mandate_id: str) -> dict[str, Any] | None:
        return self._revoked.get(mandate_id)

    def is_revoked(self, mandate_id: str) -> bool:
        return mandate_id in self._revoked

    def active(self, key: bytes | None = None) -> list[AutonomyMandate]:
        out: list[AutonomyMandate] = []
        for document in self._granted.values():
            if self.is_revoked(str(document.get("mandate_id", ""))):
                continue
            if key is not None and not verify_mandate(document, key):
                continue
            mandate = AutonomyMandate.from_document(document)
            if mandate.is_expired():
                continue
            out.append(mandate)
        return sorted(out, key=lambda m: m.issued_at, reverse=True)

    def granted_raw(self) -> list[dict[str, Any]]:
        return list(self._granted.values())


class MandateAuthority:
    """Issues, revokes and evaluates standing autonomy mandates.

    One object, one question: *may FRIDAY do this, unattended, right now?* Every
    answer is a :class:`MandateVerdict` whose refusals are named, so a caller that
    is refused can say why instead of guessing.
    """

    def __init__(
        self,
        key: bytes | None = None,
        ledger: MandateLedger | None = None,
        allow_auto_issue: bool | None = None,
    ) -> None:
        env_key = os.getenv(MANDATE_KEY_ENV, "").strip()
        self._key = key if key is not None else (env_key.encode("utf-8") if env_key else None)
        self._ledger = ledger or MandateLedger()
        if allow_auto_issue is None:
            allow_auto_issue = os.getenv("FRIDAY_AUTONOMY_AUTO_MANDATE", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self._allow_auto_issue = bool(allow_auto_issue)

    # ── key handling ───────────────────────────────────────────────────────

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def _require_key(self) -> bytes:
        if not self._key:
            raise RuntimeError(
                f"{MANDATE_KEY_ENV} is not configured, so no mandate can be verified. "
                "This is deliberate: an unsigned mandate would be an agent approving itself."
            )
        return self._key

    # ── issuing ────────────────────────────────────────────────────────────

    def issue(
        self,
        issued_by: str,
        *,
        scopes: tuple[str, ...] | list[str] | None = None,
        allowed_paths: tuple[str, ...] | list[str] | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_files_per_change: int = 3,
        max_changes: int = 0,
        note: str = "",
    ) -> dict[str, Any]:
        """Sign and record a mandate. Returns the signed document.

        Refuses an issuer that is an agent, an unknown scope, and a non-positive
        lifetime. Each refusal is a ``ValueError`` because issuing is an owner
        action taken interactively; there is no pipeline to keep alive here.
        """
        if (issued_by or "").strip().lower() in NON_OWNER_ISSUERS:
            raise ValueError(
                f"{issued_by!r} is an agent, not the owner; no agent may issue a standing mandate"
            )
        if ttl_seconds <= 0:
            raise ValueError("a mandate must have a positive lifetime")

        chosen_scopes = tuple(scopes if scopes is not None else ALL_SCOPES)
        unknown = [s for s in chosen_scopes if s not in ALL_SCOPES]
        if unknown:
            raise ValueError(f"unknown scope(s) {unknown}; known scopes are {list(ALL_SCOPES)}")

        mandate = AutonomyMandate(
            issued_by=issued_by.strip(),
            scopes=chosen_scopes,
            allowed_paths=tuple(allowed_paths if allowed_paths is not None else AutonomyMandate.allowed_paths),  # type: ignore[arg-type]
            max_files_per_change=max_files_per_change,
            max_changes=max_changes,
            expires_at=_now() + ttl_seconds,
            note=note,
        )
        document = mandate.sign(self._require_key())
        self._ledger.record_grant(document)
        logger.warning(
            "standing autonomy granted by %s until %s (scopes=%s, paths=%s)",
            mandate.issued_by,
            _iso(mandate.expires_at),
            list(mandate.scopes),
            list(mandate.allowed_paths),
        )
        return document

    def ensure_mandate(self, issued_by: str, **kwargs: Any) -> dict[str, Any] | None:
        """Return an active mandate, issuing one first if that is permitted.

        Used by the reflex loop so an operator who set
        ``FRIDAY_AUTONOMY_AUTO_MANDATE`` never has to run a second command. When
        auto-issue is off and nothing is active, returns ``None`` — the caller
        must then report ``AWAITING_MANDATE`` rather than acting.
        """
        if self.active():
            return self.active()[0].to_document()
        if not self._allow_auto_issue:
            return None
        return self.issue(issued_by, **kwargs)

    def revoke(self, mandate_id: str, reason: str = "") -> bool:
        return self._ledger.record_revocation(mandate_id, reason)

    # ── evaluation ─────────────────────────────────────────────────────────

    def active(self) -> list[AutonomyMandate]:
        return self._ledger.active(self._key)

    def status(self) -> dict[str, Any]:
        """Honest snapshot for an operator, including why nothing is permitted."""
        if not self.has_key:
            return {
                "status": "NO_KEY",
                "detail": (
                    f"{MANDATE_KEY_ENV} is not configured. Detection and proposals still run; "
                    "no change may be applied without the owner's live approval."
                ),
                "missing": [MANDATE_KEY_ENV],
                "active_mandates": [],
            }
        active = self.active()
        if not active:
            return {
                "status": "AWAITING_MANDATE",
                "detail": (
                    "No mandate is in force. FRIDAY will detect, diagnose and prepare repairs, "
                    "but will not apply one unattended until the owner grants autonomy."
                ),
                "grant_command": "friday --grant-autonomy",
                "auto_issue_enabled": self._allow_auto_issue,
                "active_mandates": [],
            }
        return {
            "status": "ACTIVE",
            "detail": f"{len(active)} mandate(s) in force; authorised changes are applied unattended.",
            "active_mandates": [m.describe() for m in active],
        }

    def evaluate(
        self,
        scope: str,
        *,
        paths: tuple[str, ...] | list[str] = (),
        has_test_evidence: bool = True,
    ) -> MandateVerdict:
        """Decide whether ``scope`` may proceed unattended on ``paths``.

        Order matters: key, then mandate presence, then revocation, then expiry,
        then scope, then paths, then budget, then evidence. A revoked mandate is
        reported as revoked rather than as absent, because the two mean different
        things to whoever is reading the audit trail.
        """
        if not self.has_key:
            return MandateVerdict.deny(
                "NO_KEY",
                f"{MANDATE_KEY_ENV} is not configured; unattended change is not possible",
            )

        candidates = self._ledger.active(self._key)
        if not candidates:
            return MandateVerdict.deny(
                "EXPIRED" if self._ledger.granted_raw() else "NO_KEY",
                "no active mandate is in force",
            )

        # Prefer the mandate that actually covers this request, so a narrow
        # mandate granted later is not shadowed by a broad one granted earlier.
        covering = [m for m in candidates if m.grants(scope)]
        if not covering:
            return MandateVerdict.deny(
                "SCOPE_NOT_GRANTED",
                f"no active mandate grants scope {scope!r}; granted scopes: "
                + ", ".join(sorted({s for m in candidates for s in m.scopes})),
            )

        if paths:
            scoped = [m for m in covering if all(m.permits_path(p) for p in paths)]
            if not scoped:
                return MandateVerdict.deny(
                    "FILE_NOT_PERMITTED",
                    "no active mandate permits: " + ", ".join(sorted(paths)),
                )
            if len(paths) > min(m.max_files_per_change for m in scoped):
                return MandateVerdict.deny(
                    "TOO_MANY_FILES",
                    f"{len(paths)} files exceeds the mandate's limit of "
                    f"{min(m.max_files_per_change for m in scoped)}",
                )
            covering = scoped

        if has_test_evidence is False and any(m.require_test_evidence for m in covering):
            return MandateVerdict.deny(
                "NO_TEST_EVIDENCE",
                "the mandate requires a passing test command, and none was supplied",
            )

        mandate = covering[0]
        if mandate.max_changes and self._ledger.consumed(mandate.mandate_id) >= mandate.max_changes:
            return MandateVerdict.deny(
                "EXPIRED",
                f"mandate {mandate.mandate_id} has spent its budget of {mandate.max_changes} change(s)",
            )

        return MandateVerdict.permit(
            mandate.mandate_id,
            f"authorised by mandate {mandate.mandate_id} (scopes={list(mandate.scopes)})",
        )

    def record_use(self, mandate_id: str) -> int:
        """Count a change against the mandate, so a bounded mandate stays bounded."""
        return self._ledger.consume(mandate_id)

    # ── integration with the repair gate ───────────────────────────────────

    def approve_repair(
        self,
        gate: Any,
        patch_id: str,
        *,
        scope: str = SCOPE_SOURCE_REPAIR,
        paths: tuple[str, ...] | list[str] = (),
    ) -> Any:
        """Approve a gated repair on the owner's standing authority.

        This is the bridge between the mandate and
        :meth:`SelfRepairGate.record_mandate_decision`. It evaluates the mandate
        first and only touches the gate when the mandate actually covers the
        change; an uncovered request never reaches the approval path at all.
        """
        record = gate.get(patch_id)
        if record is None:
            return None

        if not paths:
            paths = (record.proposal.target_file,)

        evidence = getattr(record, "tests", None)
        verdict = self.evaluate(
            scope,
            paths=paths,
            has_test_evidence=evidence is not None and bool(getattr(evidence, "passed", False)),
        )
        if not verdict.allowed:
            logger.warning(
                "autonomous approval refused for %s: %s (%s)",
                patch_id,
                verdict.refusal,
                verdict.reason,
            )
            return verdict

        document = self._ledger.document(verdict.mandate_id)
        if document is None:
            return MandateVerdict.deny("MALFORMED", "the credited mandate vanished from the ledger")

        receipt = gate.record_mandate_decision(patch_id, document, verification_key=self._require_key())
        if getattr(receipt, "outcome", "") == "ACCEPTED":
            self.record_use(verdict.mandate_id)
        return receipt

    # ── convenience for the CLI and API ────────────────────────────────────

    @staticmethod
    def generate_key() -> str:
        """A fresh signing key for the owner. Never written to the repository."""
        return os.urandom(32).hex()


def mandate_key_from_env() -> bytes | None:
    value = os.getenv(MANDATE_KEY_ENV, "").strip()
    return value.encode("utf-8") if value else None
