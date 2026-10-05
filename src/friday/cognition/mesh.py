"""The mesh: typed, receipt-verified work sent between FRIDAY and her peers.

`fleet_client.FleetClient` already speaks to all eight specialist agents. What it
cannot do is tell the truth about *why* a call failed, and it cannot be tested
without a network. Two consequences the truth audit recorded:

* every connection error inside a health probe becomes ``DEGRADED``, which claims
  the peer answered and is unhealthy. A peer that never answered is **UNREACHABLE**,
  and that is a different fact.
* ``dispatch_task`` catches every exception and returns ``TaskStatus.ERROR``, so a
  DNS failure, a TLS refusal and a peer that ran the task and failed are the same
  value. They are not the same fact either.

This module adds the missing vocabulary and the missing seam:

* :class:`OutcomeState` separates ``UNREACHABLE`` (no response at all) from
  ``DEGRADED`` (the peer answered and is unhealthy), ``REFUSED`` (the peer
  rejected us), ``UNVERIFIED`` (the peer answered 200 but produced no evidence),
  and ``COMPLETED`` (a receipt that checks out).
* :func:`verify_receipt` is the only thing that may produce ``COMPLETED``. An
  HTTP 200 is never enough on its own.
* :class:`Transport` is the seam. :class:`HttpTransport` is the real one;
  :class:`ContractTransport` is an in-process harness that speaks the *real*
  paths and payload shapes, so the whole pipeline is proven locally instead of
  asserted from a documentation comment.

Honesty note for the handoff: with no egress from this machine, every live call
through :class:`HttpTransport` is CONFIGURED-BUT-UNVERIFIED. The contracts are
copied from the code that has been calling these peers in production
(``fleet_client``), and the harness proves this module's logic against them —
but a real peer's response has not been observed here.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from friday.core.logging import get_logger
from friday.core.task_envelope import ActionReceipt, TaskEnvelope, TaskResult, TaskStatus

logger = get_logger("cognition.mesh")


class OutcomeState(str, Enum):
    """What actually happened. Every value is a distinct fact."""

    COMPLETED = "COMPLETED"      # a receipt was returned and it verifies
    PENDING = "PENDING"          # the peer accepted the task; completion unproven
    UNVERIFIED = "UNVERIFIED"    # the peer answered 2xx but returned no usable receipt
    REFUSED = "REFUSED"          # the peer (or our own policy) declined
    DEGRADED = "DEGRADED"        # the peer answered, and is not healthy
    UNREACHABLE = "UNREACHABLE"  # no response was ever received
    BLOCKED = "BLOCKED"          # not attempted, and why
    ERROR = "ERROR"              # the peer ran it and reported a failure


#: States that mean "the peer never answered". Retrying these is meaningful.
RETRYABLE_STATES = frozenset({OutcomeState.UNREACHABLE})


@dataclass
class PeerContract:
    """One peer's wire contract, read from the settings the live client uses."""

    name: str
    role: str
    base_url: str
    api_key: str = ""
    task_path: str = "/v1/task/execute"
    task_method: str = "POST"
    fallback_path: str = ""
    fallback_method: str = "POST"
    health_path: str = "/health"
    auth_style: str = "bearer"  # bearer | x-friday-api-key | x-api-key | cortex
    capability_prefix: str = ""

    def headers(self, *, agent: str = "friday") -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_style == "x-friday-api-key" and self.api_key:
            headers["X-FRIDAY-API-Key"] = self.api_key
        elif self.auth_style == "x-api-key":
            headers["X-Agent-Name"] = agent
            if self.api_key:
                headers["X-API-Key"] = self.api_key
                headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.auth_style == "cortex":
            headers["X-Friday-Api-Key"] = self.api_key
        elif self.auth_style == "bearer" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.auth_style == "bearer":
            headers["X-Agent-Name"] = agent
        return headers

    def url_for(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "base_url": self.base_url,
            "task_path": self.task_path,
            "health_path": self.health_path,
            "has_key": bool(self.api_key),
        }


def build_contracts(fleet: Any | None = None, settings: Any | None = None) -> dict[str, PeerContract]:
    """Read every peer's contract from the same fields the live client uses.

    Deriving these from :class:`~friday.ecosystem.fleet_client.FleetClient` rather
    than retyping them is deliberate: two lists of endpoints would drift, and the
    one nobody tests would be the wrong one.
    """
    import os

    if fleet is None:
        from friday.ecosystem.fleet_client import FleetClient

        fleet = FleetClient(settings=settings) if settings is not None else FleetClient()

    stratex_health = os.getenv("FRIDAY_STRATEX_HEALTH_PATH", "/api/status")
    return {
        "inference": PeerContract(
            name="inference",
            role="Multi-Model Consensus AI Gateway",
            base_url=fleet.inference_url,
            api_key=fleet.inference_key,
            task_path="/v1/task/execute",
            fallback_path="/v1/agent/assist",
            health_path="/health",
            auth_style="x-friday-api-key",
            capability_prefix="inference",
        ),
        "memora": PeerContract(
            name="memora",
            role="Persistent Cloud Vector Memory Fabric",
            base_url=fleet.memora_url,
            api_key=fleet.memora_key,
            task_path="/v1/task/execute",
            fallback_path="/v1/context",
            health_path="/health",
            auth_style="bearer",
            capability_prefix="memora",
        ),
        "stratex": PeerContract(
            name="stratex",
            role="24/7 Algorithmic Trading Platform",
            base_url=fleet.stratex_url,
            api_key=fleet.stratex_key,
            task_path="/v1/task/execute",
            fallback_path="/api/engine-health",
            fallback_method="GET",
            health_path=stratex_health,
            auth_style="x-api-key",
            capability_prefix="stratex",
        ),
        "intelx": PeerContract(
            name="intelx",
            role="Macro Intelligence & Evidence Research",
            base_url=fleet.intelx_url,
            api_key=fleet.intelx_key,
            task_path="/v1/task/execute",
            fallback_path="/api/v1/friday-universe/intelligence",
            fallback_method="GET",
            health_path="/api/v1/healthz",
            auth_style="bearer",
            capability_prefix="intelx",
        ),
        "futuris": PeerContract(
            name="futuris",
            role="Calibrated Probabilistic Forecasting",
            base_url=fleet.futuris_local_url or fleet.futuris_url,
            api_key=fleet.futuris_key,
            task_path="/v1/task/execute",
            fallback_path="/v1/friday/calibration",
            fallback_method="GET",
            health_path="/health",
            auth_style="x-api-key",
            capability_prefix="futuris",
        ),
        "cortex": PeerContract(
            name="cortex",
            role="Autonomous Web Operations",
            base_url=fleet.cortex_url,
            api_key=fleet.cortex_key,
            task_path="/v1/task/execute",
            health_path="/health",
            auth_style="cortex",
            capability_prefix="cortex",
        ),
        "forge": PeerContract(
            name="forge",
            role="Autonomous Software Engineering",
            base_url=fleet.forge_url,
            api_key=fleet.forge_key,
            task_path="/api/v1/forge/delegate",
            health_path="/health",
            auth_style="bearer",
            capability_prefix="forge",
        ),
        "sentinel": PeerContract(
            name="sentinel",
            role="Zero-Trust Cybersecurity",
            base_url=fleet.sentinel_url,
            api_key=fleet.sentinel_key,
            task_path="/api/v1/friday/delegate",
            health_path="/health",
            auth_style="x-api-key",
            capability_prefix="sentinel",
        ),
    }


# ── transport ──────────────────────────────────────────────────────────────


class TransportError(Exception):
    """No response was received. The peer's state is unknown, not unhealthy."""


@dataclass
class PeerRequest:
    peer: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None


@dataclass
class PeerResponse:
    status_code: int
    body: Any = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    """How a request reaches a peer. The only thing tests need to substitute."""

    async def send(self, request: PeerRequest) -> PeerResponse: ...


class HttpTransport:
    """The real transport. Unverified from this machine (no egress)."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def send(self, request: PeerRequest) -> PeerResponse:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.request(
                    request.method,
                    request.url,
                    headers=request.headers,
                    json=request.json_body,
                )
        except Exception as exc:  # DNS, TCP, TLS, timeout: no response was received
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc

        body: Any = None
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                body = response.json()
            except ValueError:
                body = None
        return PeerResponse(
            status_code=response.status_code,
            body=body,
            text=response.text[:2000],
            headers=dict(response.headers),
        )


@dataclass
class HarnessBehaviour:
    """How a harness peer should behave for this call.

    Every field corresponds to something a real peer can do, so the tests below
    are about this module's reasoning rather than about a mock's convenience.
    """

    status_code: int = 200
    body: Any = None
    raise_transport_error: bool = False
    receipt: bool = True
    latency_ms: int = 0


class ContractTransport:
    """An in-process peer harness that speaks the real contracts.

    It enforces the same things a real service enforces — an unknown path is 404,
    a missing key on a keyed peer is 401, a malformed envelope is 422 — so a test
    that passes here says something about the wire, not just about our own code.
    """

    def __init__(self, contracts: dict[str, PeerContract] | None = None) -> None:
        self.contracts = contracts or {}
        self.behaviours: dict[tuple[str, str], HarnessBehaviour] = {}
        self.calls: list[PeerRequest] = []

    def behave(
        self, peer: str, behaviour: HarnessBehaviour, *, path: str | None = None
    ) -> ContractTransport:
        """Set how a peer behaves. ``path`` targets one endpoint; omit it for all."""
        self.behaviours[(peer, path or "*")] = behaviour
        return self

    def behaviour_for(self, peer: str, path: str) -> HarnessBehaviour:
        return self.behaviours.get(
            (peer, path), self.behaviours.get((peer, "*"), HarnessBehaviour())
        )

    def _known_paths(self, contract: PeerContract) -> set[str]:
        return {contract.task_path, contract.fallback_path, contract.health_path} - {""}

    async def send(self, request: PeerRequest) -> PeerResponse:
        self.calls.append(request)
        contract = self.contracts.get(request.peer)
        if contract is None:
            return PeerResponse(status_code=404, body={"error": f"no harness peer {request.peer!r}"})

        raw_path = request.url[len(contract.base_url.rstrip("/")) :] or "/"
        path = raw_path.split("?", 1)[0]
        behaviour = self.behaviour_for(request.peer, path)
        if behaviour.latency_ms:
            await asyncio.sleep(behaviour.latency_ms / 1000.0)
        if behaviour.raise_transport_error:
            raise TransportError("connection refused (harness)")

        if path not in self._known_paths(contract):
            return PeerResponse(status_code=404, body={"detail": f"unknown path {path}"})

        if contract.api_key and not any(
            key in request.headers
            for key in ("Authorization", "X-API-Key", "X-FRIDAY-API-Key", "X-Friday-Api-Key")
        ):
            return PeerResponse(status_code=401, body={"detail": "missing credentials"})

        if request.method == "POST" and path == contract.task_path:
            body = request.json_body or {}
            if not isinstance(body, dict) or "task_id" not in body or "target_agent" not in body:
                return PeerResponse(status_code=422, body={"detail": "malformed TaskEnvelope"})

        return PeerResponse(
            status_code=behaviour.status_code,
            body=self._body_for(request, contract, behaviour),
        )

    def _body_for(
        self, request: PeerRequest, contract: PeerContract, behaviour: HarnessBehaviour
    ) -> Any:
        if behaviour.body is not None:
            return behaviour.body
        if behaviour.status_code in (401, 403):
            return {"detail": "not authorized"}
        if behaviour.status_code == 404:
            return {"detail": "no such endpoint"}
        if behaviour.status_code >= 500:
            return {"detail": "upstream failure"}
        if behaviour.status_code == 202:
            return {"state": "queued", "task_id": (request.json_body or {}).get("task_id", "")}
        if behaviour.status_code >= 400:
            return {"detail": f"HTTP {behaviour.status_code}"}

        if not behaviour.receipt:
            # A 200 with no receipt. Many services answer like this.
            return {"status": "ok", "response": "done"}

        envelope = request.json_body or {}
        return {
            "task_id": envelope.get("task_id", ""),
            "status": "success",
            "summary": f"{contract.name} completed the task",
            "result": {"echo": envelope.get("objective", "")},
            "receipt": {
                "requested_action": envelope.get("action", ""),
                "target": contract.name,
                "authorization_decision": "AUTHORIZED",
                "result": {"ok": True},
                "verification_evidence": {"checked": "harness", "action": envelope.get("action", "")},
            },
        }


# ── receipt verification ───────────────────────────────────────────────────


@dataclass
class ReceiptVerdict:
    ok: bool
    state: OutcomeState
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "state": self.state.value, "reason": self.reason}


def verify_receipt(envelope: TaskEnvelope, result: TaskResult) -> ReceiptVerdict:
    """Decide whether a peer's answer is evidence that the work happened.

    The rules are strict on purpose. A peer that it is convenient to believe is
    the most expensive kind of peer to have.
    """
    receipt = result.receipt
    if receipt is None:
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.UNVERIFIED,
            reason="the peer returned no receipt, so completion cannot be verified",
        )

    if receipt.authorization_decision == "REJECTED":
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.REFUSED,
            reason=f"the peer rejected the action: {receipt.failure_reason or 'no reason given'}",
        )

    if receipt.requested_action != (envelope.action or envelope.objective):
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.UNVERIFIED,
            reason=(
                f"the receipt names action {receipt.requested_action!r}, but "
                f"{envelope.action!r} was requested"
            ),
        )

    if receipt.target != envelope.target_agent:
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.UNVERIFIED,
            reason=(
                f"the receipt names target {receipt.target!r}, but {envelope.target_agent!r} "
                "was asked"
            ),
        )

    if receipt.failure_reason:
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.ERROR,
            reason=f"the peer reported a failure: {receipt.failure_reason}",
        )

    if not receipt.verification_evidence:
        return ReceiptVerdict(
            ok=False,
            state=OutcomeState.UNVERIFIED,
            reason="the receipt carries no verification evidence, so the claim is unproven",
        )

    return ReceiptVerdict(
        ok=True,
        state=OutcomeState.COMPLETED,
        reason="a receipt for this action and target, with verification evidence, was returned",
    )


# ── outcomes ───────────────────────────────────────────────────────────────


@dataclass
class PeerOutcome:
    peer: str
    state: OutcomeState
    detail: str
    http_status: int | None = None
    latency_ms: int = 0
    attempts: int = 1
    task_id: str = ""
    contract_used: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None

    @property
    def verified(self) -> bool:
        return self.state is OutcomeState.COMPLETED

    @property
    def reached_peer(self) -> bool:
        return self.state is not OutcomeState.UNREACHABLE and self.http_status is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer": self.peer,
            "state": self.state.value,
            "detail": self.detail,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "task_id": self.task_id,
            "contract_used": self.contract_used,
            "evidence": self.evidence,
            "result": self.result,
        }


@dataclass
class ReconnectResult:
    """The answer to "is this peer reachable again?"."""

    peer: str
    recovered: bool
    attempts: int
    state: OutcomeState
    detail: str
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer": self.peer,
            "recovered": self.recovered,
            "attempts": self.attempts,
            "state": self.state.value,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
        }


class CircuitBreaker:
    """Stop hammering a peer that is not answering.

    Only ``UNREACHABLE`` opens the circuit. A peer that answers, even badly, is
    telling us something, and we should keep listening.
    """

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, peer: str) -> bool:
        opened = self._opened_at.get(peer)
        if opened is None:
            return False
        if time.time() - opened >= self.cooldown_seconds:
            self._opened_at.pop(peer, None)
            self._failures.pop(peer, None)
            return False
        return True

    def record(self, peer: str, state: OutcomeState) -> None:
        if state is OutcomeState.BLOCKED:
            # A local decision (no URL, open circuit, unknown peer) says nothing
            # about the peer, so it must neither count against it nor forgive it.
            return
        if state is OutcomeState.UNREACHABLE:
            self._failures[peer] = self._failures.get(peer, 0) + 1
            if self._failures[peer] >= self.threshold:
                self._opened_at[peer] = time.time()
        else:
            self._failures.pop(peer, None)
            self._opened_at.pop(peer, None)

    def retry_in(self, peer: str) -> float:
        opened = self._opened_at.get(peer)
        if opened is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (time.time() - opened))

    def as_dict(self) -> dict[str, Any]:
        return {
            "open": sorted(self._opened_at),
            "failures": dict(self._failures),
            "threshold": self.threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }


# ── the mesh ───────────────────────────────────────────────────────────────


class Mesh:
    """Send work to the peers, and be precise about what came back."""

    def __init__(
        self,
        contracts: dict[str, PeerContract] | None = None,
        transport: Transport | None = None,
        *,
        attempts: int = 2,
        backoff_seconds: float = 0.25,
        breaker: CircuitBreaker | None = None,
        on_outcome: Callable[[PeerOutcome], None] | None = None,
    ) -> None:
        self.contracts = contracts if contracts is not None else build_contracts()
        self.transport: Transport = transport or HttpTransport()
        self.attempts = max(1, attempts)
        self.backoff_seconds = backoff_seconds
        self.breaker = breaker or CircuitBreaker()
        self._on_outcome = on_outcome
        self.history: list[PeerOutcome] = []

    # -- construction helpers ---------------------------------------------

    @classmethod
    def in_process(cls, contracts: dict[str, PeerContract] | None = None, **kwargs: Any) -> tuple[Mesh, ContractTransport]:
        """A mesh wired to the contract harness, for tests and local proof."""
        transport = ContractTransport(contracts)
        mesh = cls(contracts=contracts or transport.contracts, transport=transport, **kwargs)
        return mesh, transport

    def _record(self, outcome: PeerOutcome) -> PeerOutcome:
        self.breaker.record(outcome.peer, outcome.state)
        self.history.append(outcome)
        if len(self.history) > 500:
            del self.history[:250]
        if self._on_outcome is not None:
            try:
                self._on_outcome(outcome)
            except Exception:  # a listener must never break a dispatch
                logger.exception("mesh outcome listener failed")
        return outcome

    # -- dispatch ----------------------------------------------------------

    def build_envelope(
        self,
        peer: str,
        *,
        action: str,
        objective: str = "",
        inputs: dict[str, Any] | None = None,
        capability: str = "",
        actor: str = "friday",
        trust_level: str = "system_internal",
    ) -> TaskEnvelope:
        contract = self.contracts[peer]
        return TaskEnvelope(
            actor=actor,
            source_agent=actor,
            target_agent=peer,
            action=action,
            objective=objective or action,
            capability=capability or f"{contract.capability_prefix}.{action}".strip("."),
            inputs=dict(inputs or {}),
            payload=dict(inputs or {}),
            trust_level=trust_level,
        )

    async def dispatch(
        self,
        peer: str,
        action: str,
        *,
        objective: str = "",
        inputs: dict[str, Any] | None = None,
        capability: str = "",
        actor: str = "friday",
        envelope: TaskEnvelope | None = None,
        attempts: int | None = None,
    ) -> PeerOutcome:
        """Send one typed task to one peer, and classify what came back."""
        started = time.time()
        contract = self.contracts.get(peer)
        if contract is None:
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.BLOCKED,
                    detail=(
                        f"{peer!r} is not a known peer; known peers are "
                        f"{', '.join(sorted(self.contracts))}"
                    ),
                )
            )
        if not contract.base_url:
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.BLOCKED,
                    detail=(
                        f"no {peer} base URL is configured, so nothing was sent. "
                        f"Set FRIDAY_{peer.upper()}_URL to reach it."
                    ),
                )
            )
        if self.breaker.is_open(peer):
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.BLOCKED,
                    detail=(
                        f"{peer} has been unreachable repeatedly; the circuit is open for another "
                        f"{self.breaker.retry_in(peer):.0f}s so it is not hammered"
                    ),
                    evidence={"breaker": self.breaker.as_dict()},
                )
            )

        task = envelope or self.build_envelope(
            peer,
            action=action,
            objective=objective,
            inputs=inputs,
            capability=capability,
            actor=actor,
        )

        budget = self.attempts if attempts is None else max(1, attempts)
        last: PeerOutcome | None = None
        for attempt in range(1, budget + 1):
            outcome = await self._attempt(peer, contract, task, attempt, started)
            last = outcome
            if outcome.state not in RETRYABLE_STATES:
                return self._record(outcome)
            if attempt < budget and self.backoff_seconds:
                await asyncio.sleep(self.backoff_seconds * attempt)
        assert last is not None
        return self._record(last)

    async def _attempt(
        self,
        peer: str,
        contract: PeerContract,
        envelope: TaskEnvelope,
        attempt: int,
        started: float,
    ) -> PeerOutcome:
        headers = contract.headers(agent=envelope.source_agent)
        request = PeerRequest(
            peer=peer,
            method=contract.task_method,
            url=contract.url_for(contract.task_path),
            headers=headers,
            json_body=envelope.model_dump(),
        )

        try:
            response = await self.transport.send(request)
        except TransportError as exc:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.UNREACHABLE,
                detail=f"no response was received from {peer}: {exc}",
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.UNREACHABLE,
                detail=f"the {peer} call failed before a response arrived: {type(exc).__name__}: {exc}",
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
                latency_ms=int((time.time() - started) * 1000),
            )

        latency = int((time.time() - started) * 1000)
        status = response.status_code

        # A peer that does not implement the contract endpoint is a real, common
        # finding. Try the documented fallback once, and say which path answered.
        if status in (404, 405) and contract.fallback_path:
            return await self._try_fallback(peer, contract, envelope, attempt, started, response)

        if status in (401, 403):
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.REFUSED,
                detail=(
                    f"{peer} rejected the credentials (HTTP {status}). The task was not run; "
                    "a key is missing or wrong."
                ),
                http_status=status,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
            )
        if status == 202:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.PENDING,
                detail=f"{peer} accepted the task and has not finished it. Completion is unproven.",
                http_status=status,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
            )
        if status >= 500:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.DEGRADED,
                detail=f"{peer} answered HTTP {status}: it is reachable and unhealthy.",
                http_status=status,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
                evidence={"body": _short(response.body or response.text)},
            )
        if status not in (200, 201):
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.UNVERIFIED,
                detail=f"{peer} answered HTTP {status}, which is not evidence of anything.",
                http_status=status,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.task_path,
                evidence={"body": _short(response.body or response.text)},
            )

        return self._interpret(peer, contract, envelope, response, attempt, latency, contract.task_path)

    async def _try_fallback(
        self,
        peer: str,
        contract: PeerContract,
        envelope: TaskEnvelope,
        attempt: int,
        started: float,
        first_response: PeerResponse,
    ) -> PeerOutcome:
        request = PeerRequest(
            peer=peer,
            method=contract.fallback_method,
            url=contract.url_for(contract.fallback_path),
            headers=contract.headers(agent=envelope.source_agent),
            json_body=envelope.model_dump() if contract.fallback_method == "POST" else None,
        )
        try:
            response = await self.transport.send(request)
        except Exception as exc:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.UNREACHABLE,
                detail=(
                    f"{peer} does not implement {contract.task_path} (HTTP {first_response.status_code}) "
                    f"and the fallback {contract.fallback_path} could not be reached: {exc}"
                ),
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.fallback_path,
            )

        latency = int((time.time() - started) * 1000)
        if response.status_code in (401, 403):
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.REFUSED,
                detail=f"{peer} rejected the fallback credentials (HTTP {response.status_code}).",
                http_status=response.status_code,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.fallback_path,
            )
        if response.status_code in (404, 405):
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.DEGRADED,
                detail=(
                    f"{peer} exposes neither {contract.task_path} nor {contract.fallback_path}: "
                    "the published contract is not deployed there. No task was run."
                ),
                http_status=response.status_code,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.fallback_path,
            )
        if response.status_code >= 500:
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.DEGRADED,
                detail=f"{peer} fallback answered HTTP {response.status_code}: reachable and unhealthy.",
                http_status=response.status_code,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=contract.fallback_path,
            )

        # A legacy status/context endpoint answered. It is evidence that the peer
        # is alive, not evidence that the task was performed.
        return PeerOutcome(
            peer=peer,
            state=OutcomeState.DEGRADED,
            detail=(
                f"{peer} answered on the legacy fallback {contract.fallback_path} instead of the task "
                "contract. The peer is reachable; task execution was NOT performed or verified."
            ),
            http_status=response.status_code,
            latency_ms=latency,
            attempts=attempt,
            task_id=envelope.task_id,
            contract_used=contract.fallback_path,
            evidence={"body": _short(response.body or response.text)},
        )

    def _interpret(
        self,
        peer: str,
        contract: PeerContract,
        envelope: TaskEnvelope,
        response: PeerResponse,
        attempt: int,
        latency: int,
        path_used: str,
    ) -> PeerOutcome:
        body = response.body
        if not isinstance(body, dict):
            return PeerOutcome(
                peer=peer,
                state=OutcomeState.UNVERIFIED,
                detail=(
                    f"{peer} answered HTTP {response.status_code} with a non-JSON body, so no "
                    "receipt could be read."
                ),
                http_status=response.status_code,
                latency_ms=latency,
                attempts=attempt,
                task_id=envelope.task_id,
                contract_used=path_used,
                evidence={"body": _short(response.text)},
            )

        result = _result_from_body(envelope, body, latency)
        verdict = verify_receipt(envelope, result)
        return PeerOutcome(
            peer=peer,
            state=verdict.state,
            detail=f"{peer}: {verdict.reason}",
            http_status=response.status_code,
            latency_ms=latency,
            attempts=attempt,
            task_id=envelope.task_id,
            contract_used=path_used,
            evidence={"receipt": verdict.as_dict(), "summary": result.summary},
            result=body,
        )

    # -- fleet-wide --------------------------------------------------------

    async def dispatch_many(
        self,
        targets: dict[str, tuple[str, dict[str, Any]]],
        **kwargs: Any,
    ) -> dict[str, PeerOutcome]:
        """Dispatch to several peers at once. ``targets`` maps peer -> (action, inputs)."""
        coros = {
            peer: self.dispatch(peer, action, inputs=inputs, **kwargs)
            for peer, (action, inputs) in targets.items()
        }
        results = await asyncio.gather(*coros.values(), return_exceptions=True)
        outcomes: dict[str, PeerOutcome] = {}
        for peer, result in zip(coros.keys(), results, strict=True):
            if isinstance(result, BaseException):
                outcomes[peer] = self._record(
                    PeerOutcome(
                        peer=peer,
                        state=OutcomeState.ERROR,
                        detail=f"dispatch raised {type(result).__name__}: {result}",
                    )
                )
            else:
                outcomes[peer] = result
        return outcomes

    async def health(self, peer: str | None = None) -> dict[str, PeerOutcome]:
        """Probe reachability, without confusing it with health."""
        peers = [peer] if peer else sorted(self.contracts)
        coros = [self._probe(one) for one in peers]
        results = await asyncio.gather(*coros, return_exceptions=True)

        outcomes: dict[str, PeerOutcome] = {}
        for name, result in zip(peers, results, strict=True):
            if isinstance(result, BaseException):
                outcomes[name] = self._record(
                    PeerOutcome(
                        peer=name,
                        state=OutcomeState.ERROR,
                        detail=f"the probe raised {type(result).__name__}: {result}",
                    )
                )
            else:
                outcomes[name] = result
        return outcomes

    async def _probe(self, peer: str) -> PeerOutcome:
        contract = self.contracts[peer]
        if not contract.base_url:
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.BLOCKED,
                    detail=f"no {peer} base URL is configured; nothing was probed",
                )
            )
        if self.breaker.is_open(peer):
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.BLOCKED,
                    detail=(
                        f"{peer} is in circuit-breaker cooldown "
                        f"({self.breaker.retry_in(peer):.0f}s); no probe was sent, so nothing "
                        "new is known about it"
                    ),
                )
            )

        started = time.time()
        request = PeerRequest(
            peer=peer,
            method="GET",
            url=contract.url_for(contract.health_path),
            headers=contract.headers(),
        )
        try:
            response = await self.transport.send(request)
        except Exception as exc:
            return self._record(
                PeerOutcome(
                    peer=peer,
                    state=OutcomeState.UNREACHABLE,
                    detail=f"no response was received from {peer}: {type(exc).__name__}: {exc}",
                    latency_ms=int((time.time() - started) * 1000),
                    contract_used=contract.health_path,
                )
            )

        latency = int((time.time() - started) * 1000)
        status = response.status_code
        if status in (401, 403):
            state, detail = (
                OutcomeState.REFUSED,
                f"{peer} is up and rejected our credentials (HTTP {status})",
            )
        elif status >= 500:
            state, detail = (
                OutcomeState.DEGRADED,
                f"{peer} answered HTTP {status}: reachable and unhealthy",
            )
        elif status in (404, 405):
            state, detail = (
                OutcomeState.DEGRADED,
                f"{peer} is reachable but exposes no {contract.health_path} health endpoint",
            )
        elif status < 400:
            declared = ""
            if isinstance(response.body, dict):
                declared = str(
                    response.body.get("status") or response.body.get("health") or response.body.get("state") or ""
                ).lower()
            unhealthy = declared in {
                "unhealthy",
                "degraded",
                "down",
                "error",
                "unavailable",
                "critical",
            }
            state = OutcomeState.DEGRADED if unhealthy else OutcomeState.PENDING
            detail = (
                f"{peer} answered HTTP {status}"
                + (f" and describes itself as {declared!r}" if declared else "")
                + ". A health endpoint does not prove task execution."
            )
        else:
            state, detail = (
                OutcomeState.UNVERIFIED,
                f"{peer} answered HTTP {status}, which proves only that something answered",
            )
        return self._record(
            PeerOutcome(
                peer=peer,
                state=state,
                detail=detail,
                http_status=status,
                latency_ms=latency,
                contract_used=contract.health_path,
                result=response.body if isinstance(response.body, dict) else None,
            )
        )

    # -- the reflex brain's entry point ------------------------------------

    async def reconnect(self, peer: str, *, attempts: int = 2) -> ReconnectResult:
        """Is this peer reachable again? Answer that, and nothing more."""
        contract = self.contracts.get(peer)
        if contract is None:
            return ReconnectResult(
                peer=peer,
                recovered=False,
                attempts=0,
                state=OutcomeState.BLOCKED,
                detail=f"{peer!r} is not a known peer",
            )
        if not contract.base_url:
            return ReconnectResult(
                peer=peer,
                recovered=False,
                attempts=0,
                state=OutcomeState.BLOCKED,
                detail=f"no {peer} base URL is configured, so there is nothing to reconnect to",
            )

        last: PeerOutcome | None = None
        for attempt in range(1, max(1, attempts) + 1):
            last = await self._probe(peer)
            if last.state is not OutcomeState.UNREACHABLE:
                return ReconnectResult(
                    peer=peer,
                    recovered=True,
                    attempts=attempt,
                    state=last.state,
                    detail=(
                        f"{peer} answered on attempt {attempt} ({last.state.value}). "
                        "Being reachable is not proof that its work is correct or complete."
                    ),
                    latency_ms=last.latency_ms,
                )
            if attempt < attempts:
                await asyncio.sleep(min(2.0, 0.25 * attempt))

        return ReconnectResult(
            peer=peer,
            recovered=False,
            attempts=max(1, attempts),
            state=OutcomeState.UNREACHABLE,
            detail=f"{peer} did not answer after {attempts} attempt(s). It may be down, or blocked here.",
        )

    # -- introspection -----------------------------------------------------

    def status(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for outcome in self.history:
            counts[outcome.state.value] = counts.get(outcome.state.value, 0) + 1
        live = isinstance(self.transport, HttpTransport)
        return {
            "peers": [contract.as_dict() for contract in self.contracts.values()],
            "transport": type(self.transport).__name__,
            "history": len(self.history),
            "state_counts": counts,
            "breaker": self.breaker.as_dict(),
            # Said plainly, because it is the difference between proof and intent.
            "live_verification": (
                "CONFIGURED-BUT-UNVERIFIED: this mesh can make live calls, but no live peer "
                "response has been observed while this status was produced"
                if live
                else "in-process contract harness: the wire contracts are exercised, but no "
                "remote service was contacted"
            ),
            "receipt_trail": [outcome.as_dict() for outcome in self.history[-10:]],
        }


def _result_from_body(envelope: TaskEnvelope, body: dict[str, Any], latency: int) -> TaskResult:
    """Read a TaskResult out of whatever shape the peer answered with."""
    raw_receipt = body.get("receipt")
    receipt = None
    if isinstance(raw_receipt, dict):
        try:
            receipt = ActionReceipt(**raw_receipt)
        except Exception:
            receipt = None

    declared = str(body.get("status") or body.get("state") or "").strip().lower()
    if declared in {"success", "succeeded", "complete", "completed", "done"} or body.get("completed") is True:
        status = TaskStatus.SUCCESS
    elif declared in {"pending", "queued", "running", "accepted", "waiting_approval", "awaiting_approval"}:
        status = TaskStatus.PENDING
    elif declared in {"error", "failed", "failure"}:
        status = TaskStatus.ERROR
    elif declared in {"degraded", "partial"}:
        status = TaskStatus.DEGRADED
    else:
        status = TaskStatus.SUCCESS if receipt is not None else TaskStatus.DEGRADED

    return TaskResult(
        task_id=str(body.get("task_id") or envelope.task_id),
        target_agent=envelope.target_agent,
        status=status,
        result=body.get("result") if isinstance(body.get("result"), dict) else {},
        summary=str(body.get("summary") or body.get("message") or ""),
        error=body.get("error") if isinstance(body.get("error"), str) else None,
        execution_time_ms=latency,
        receipt=receipt,
    )


def _short(value: Any, limit: int = 300) -> Any:
    if isinstance(value, dict):
        return {key: _short(item, limit) for key, item in list(value.items())[:8]}
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    return text[:limit]


def get_mesh(**kwargs: Any) -> Mesh:
    """The mesh singleton, so every part of FRIDAY shares one breaker and history."""
    global _MESH
    if _MESH is None:
        _MESH = Mesh(**kwargs)
    return _MESH


_MESH: Mesh | None = None
