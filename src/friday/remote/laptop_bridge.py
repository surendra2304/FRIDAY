"""Reverse-tunnel registry for the owner's laptop.

The cloud FRIDAY has no route into a laptop behind NAT. The laptop therefore
opens an outbound WebSocket to ``/api/laptop/connect/{laptop_id}`` and this
module keeps that socket, correlates command frames with result frames, and
returns a single evidence record per command.

Security posture:

* The tunnel authenticates with the existing control key / control token before
  the socket is accepted (see ``server.py``).
* Only the commands in :data:`ALLOWED_LAPTOP_COMMANDS` are dispatched.
* ``run_shell`` is additionally gated on ``FRIDAY_LAPTOP_ALLOW_SHELL=true`` on
  this host; the client refuses it again unless the same flag is set locally.
* Every result is bounded to :data:`MAX_OUTPUT_BYTES` so a chatty command cannot
  exhaust cloud memory. The output is evidence, not a transport for files.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("remote.laptop_bridge")

MAX_OUTPUT_BYTES = 16 * 1024
MAX_ERROR_CHARS = 2 * 1024
MAX_ARGS_BYTES = 64 * 1024
DEFAULT_COMMAND_TIMEOUT = 30.0
MAX_COMMAND_TIMEOUT = 300.0
MAX_KNOWN_DEVICES = 64

SHELL_COMMAND = "run_shell"
ALLOWED_LAPTOP_COMMANDS = frozenset(
    {
        "screenshot",
        "open_url",
        "list_files",
        "read_file",
        SHELL_COMMAND,
        "system_info",
        "notify",
    }
)

_TRUNCATION_MARKER = "\n[truncated]"
_LAPTOP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class LaptopBridgeError(RuntimeError):
    """Base class for failures that the API layer maps to an HTTP status."""


class LaptopNotConnected(LaptopBridgeError):
    """No tunnel is currently registered for the requested laptop."""


class LaptopDisconnected(LaptopBridgeError):
    """The tunnel disappeared while a command was in flight."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class LaptopBridgeTimeout(LaptopBridgeError):
    """The laptop did not answer within the requested deadline."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        super().__init__(str(evidence.get("error") or "laptop command timed out"))
        self.evidence = evidence


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shell_flag_enabled() -> bool:
    return os.getenv("FRIDAY_LAPTOP_ALLOW_SHELL", "").strip().lower() in {"1", "true", "yes", "on"}


def shell_execution_enabled() -> bool:
    """Whether ``run_shell`` may be dispatched from this process."""
    return _shell_flag_enabled()


def normalise_laptop_id(value: str) -> str:
    """Return a safe laptop id or raise ``ValueError``.

    The id ends up in a URL path component, a log line and the API response, so
    it is restricted to a small character set rather than escaped later.
    """
    text = (value or "").strip()
    if not _LAPTOP_ID_PATTERN.match(text):
        raise ValueError(
            "laptop_id must be 1-64 characters of letters, digits, dot, colon, dash or underscore"
        )
    return text


def _bounded(value: Any, limit: int = MAX_OUTPUT_BYTES) -> str:
    """Render a value as UTF-8 text no larger than ``limit`` bytes."""
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except (TypeError, ValueError):
            text = str(value)
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text
    marker = _TRUNCATION_MARKER.encode("utf-8")
    keep = max(0, limit - len(marker))
    return raw[:keep].decode("utf-8", errors="ignore") + _TRUNCATION_MARKER


def _normalise_timeout(value: float | int | None) -> float:
    try:
        timeout = float(DEFAULT_COMMAND_TIMEOUT if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a number of seconds") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive number of seconds")
    return min(timeout, MAX_COMMAND_TIMEOUT)


def _normalise_args(args: dict[str, Any] | None) -> dict[str, Any]:
    if args is None:
        return {}
    if not isinstance(args, dict):
        raise ValueError("args must be a JSON object")
    try:
        encoded = json.dumps(args)
    except (TypeError, ValueError) as exc:
        raise ValueError("args must contain only JSON-serialisable values") from exc
    if len(encoded.encode("utf-8")) > MAX_ARGS_BYTES:
        raise ValueError("args is too large")
    return dict(args)


def _evidence(
    *,
    request_id: str,
    laptop_id: str,
    command: str,
    started_at: str,
    finished_at: str,
    ok: bool,
    output: Any,
    error: Any,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "laptop_id": laptop_id,
        "command": command,
        "started_at": started_at,
        "finished_at": finished_at,
        "ok": bool(ok),
        "output": _bounded(output),
        "error": None if error is None else _bounded(error, MAX_ERROR_CHARS),
    }


@dataclass
class LaptopConnection:
    """One live reverse tunnel and the requests waiting on it."""

    laptop_id: str
    websocket: Any
    connected_at: str = field(default_factory=_now_iso)
    last_seen: str = field(default_factory=_now_iso)
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class LaptopBridge:
    """Registry of reverse tunnels, keyed by laptop id.

    All mutations of ``_connections`` and ``_known`` happen under ``_lock``.
    The lock is never held while a frame is written to a socket, so one slow or
    dead laptop cannot stall commands for every other laptop.
    """

    def __init__(self) -> None:
        self._connections: dict[str, LaptopConnection] = {}
        self._known: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def register(self, laptop_id: str, websocket: Any) -> LaptopConnection | None:
        """Attach a tunnel and return the connection it replaced, if any."""
        laptop_id = normalise_laptop_id(laptop_id)
        now = _now_iso()
        previous: LaptopConnection | None = None
        async with self._lock:
            previous = self._connections.get(laptop_id)
            connection = LaptopConnection(laptop_id=laptop_id, websocket=websocket, last_seen=now)
            self._connections[laptop_id] = connection
            self._remember(laptop_id, connection.connected_at, now)
            if previous is not None:
                self._fail_pending(previous, "laptop_replaced")
            self._prune_known()
        log = logger.warning if previous is not None else logger.info
        log("Laptop tunnel registered: %s", laptop_id)
        return previous

    async def unregister(self, laptop_id: str, websocket: Any | None = None) -> None:
        """Remove a tunnel and fail every command still waiting on it.

        ``websocket`` disambiguates a stale route task from a newer tunnel for
        the same laptop: a reconnect registers the replacement first, and the
        old task's cleanup must not evict it.
        """
        try:
            laptop_id = normalise_laptop_id(laptop_id)
        except ValueError:
            return
        async with self._lock:
            connection = self._connections.get(laptop_id)
            if connection is None:
                return
            if websocket is not None and connection.websocket is not websocket:
                return
            self._connections.pop(laptop_id, None)
            self._fail_pending(connection, "laptop_disconnected")
            self._remember(laptop_id, connection.connected_at, _now_iso())
        logger.info("Laptop tunnel unregistered: %s", laptop_id)

    async def touch(self, laptop_id: str) -> None:
        """Record a heartbeat so ``last_seen`` reflects laptop liveness."""
        try:
            laptop_id = normalise_laptop_id(laptop_id)
        except ValueError:
            return
        async with self._lock:
            connection = self._connections.get(laptop_id)
            if connection is None:
                return
            connection.last_seen = _now_iso()
            self._remember(laptop_id, connection.connected_at, connection.last_seen)

    async def resolve_result(self, laptop_id: str, payload: dict[str, Any]) -> bool:
        """Complete the future waiting for ``payload['request_id']``."""
        try:
            laptop_id = normalise_laptop_id(laptop_id)
        except ValueError:
            return False
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            return False
        async with self._lock:
            connection = self._connections.get(laptop_id)
            if connection is None:
                return False
            connection.last_seen = _now_iso()
            future = connection.pending.pop(request_id, None)
            if future is None or future.done():
                return False
            future.set_result(dict(payload))
        return True

    async def list_devices(self) -> list[dict[str, Any]]:
        """Return every known laptop, online first, then alphabetically."""
        async with self._lock:
            devices: dict[str, dict[str, Any]] = {}
            for laptop_id, meta in self._known.items():
                devices[laptop_id] = {
                    "laptop_id": laptop_id,
                    "online": False,
                    "connected_at": None,
                    "last_seen": meta.get("last_seen"),
                    "pending_requests": 0,
                }
            for laptop_id, connection in self._connections.items():
                devices[laptop_id] = {
                    "laptop_id": laptop_id,
                    "online": True,
                    "connected_at": connection.connected_at,
                    "last_seen": connection.last_seen,
                    "pending_requests": len(connection.pending),
                }
        return sorted(devices.values(), key=lambda item: (not item["online"], item["laptop_id"]))

    async def execute(
        self,
        laptop_id: str,
        command: str,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one allowlisted command on ``laptop_id`` and return evidence.

        Raises :class:`LaptopNotConnected` when there is no tunnel,
        :class:`LaptopBridgeTimeout` when the deadline expires, and
        :class:`LaptopDisconnected` when the tunnel closes mid-command.
        """
        laptop_id = normalise_laptop_id(laptop_id)
        command = (command or "").strip()
        if command not in ALLOWED_LAPTOP_COMMANDS:
            raise ValueError(
                f"Unsupported laptop command '{command}'. Allowed: "
                + ", ".join(sorted(ALLOWED_LAPTOP_COMMANDS))
            )
        if command == SHELL_COMMAND and not shell_execution_enabled():
            raise ValueError(
                "run_shell is disabled; set FRIDAY_LAPTOP_ALLOW_SHELL=true on the FRIDAY host "
                "and on the laptop before using it."
            )
        clean_args = _normalise_args(args)
        deadline = _normalise_timeout(timeout)

        request_id = uuid.uuid4().hex
        started_at = _now_iso()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async with self._lock:
            connection = self._connections.get(laptop_id)
            if connection is None:
                raise LaptopNotConnected(f"Laptop '{laptop_id}' is not connected")
            connection.pending[request_id] = future
            connection.last_seen = started_at
            self._remember(laptop_id, connection.connected_at, started_at)

        frame = {
            "type": "command",
            "request_id": request_id,
            "laptop_id": laptop_id,
            "command": command,
            "args": clean_args,
            "timeout": deadline,
        }
        try:
            async with connection.send_lock:
                await connection.websocket.send_json(frame)
        except Exception as exc:
            await self._discard_pending(laptop_id, request_id)
            raise LaptopDisconnected(
                f"Laptop '{laptop_id}' disconnected before the command was sent",
                _evidence(
                    request_id=request_id,
                    laptop_id=laptop_id,
                    command=command,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    ok=False,
                    output="",
                    error=f"laptop_disconnected: {type(exc).__name__}",
                ),
            ) from exc

        try:
            result = await asyncio.wait_for(future, timeout=deadline)
        except asyncio.TimeoutError:
            await self._discard_pending(laptop_id, request_id)
            evidence = _evidence(
                request_id=request_id,
                laptop_id=laptop_id,
                command=command,
                started_at=started_at,
                finished_at=_now_iso(),
                ok=False,
                output="",
                error=f"timeout after {deadline:g}s",
            )
            logger.warning("Laptop command timed out: %s %s (%s)", laptop_id, command, request_id)
            raise LaptopBridgeTimeout(evidence) from None

        bridge_error = result.get("_bridge_error")
        if bridge_error:
            raise LaptopDisconnected(
                f"Laptop '{laptop_id}' disconnected while the command was running",
                _evidence(
                    request_id=request_id,
                    laptop_id=laptop_id,
                    command=command,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    ok=False,
                    output="",
                    error=str(bridge_error),
                ),
            )

        evidence = _evidence(
            request_id=request_id,
            laptop_id=laptop_id,
            command=command,
            started_at=str(result.get("started_at") or started_at),
            finished_at=str(result.get("finished_at") or _now_iso()),
            ok=bool(result.get("ok")),
            output=result.get("output"),
            error=result.get("error"),
        )
        logger.info(
            "Laptop command completed: %s %s ok=%s request=%s",
            laptop_id,
            command,
            evidence["ok"],
            request_id,
        )
        return evidence

    async def _discard_pending(self, laptop_id: str, request_id: str) -> None:
        async with self._lock:
            connection = self._connections.get(laptop_id)
            if connection is not None:
                connection.pending.pop(request_id, None)

    @staticmethod
    def _fail_pending(connection: LaptopConnection, reason: str) -> None:
        pending = connection.pending
        connection.pending = {}
        for future in pending.values():
            if not future.done():
                future.set_result({"_bridge_error": reason})

    def _remember(self, laptop_id: str, connected_at: str, last_seen: str) -> None:
        self._known[laptop_id] = {
            "connected_at": connected_at,
            "last_seen": last_seen,
        }

    def _prune_known(self) -> None:
        if len(self._known) <= MAX_KNOWN_DEVICES:
            return
        offline = [
            laptop_id
            for laptop_id in self._known
            if laptop_id not in self._connections
        ]
        offline.sort(key=lambda laptop_id: self._known[laptop_id].get("last_seen") or "")
        for laptop_id in offline[: len(self._known) - MAX_KNOWN_DEVICES]:
            self._known.pop(laptop_id, None)


# One registry per process. Its mutable state is guarded by ``LaptopBridge._lock``.
laptop_bridge = LaptopBridge()


__all__ = [
    "ALLOWED_LAPTOP_COMMANDS",
    "DEFAULT_COMMAND_TIMEOUT",
    "MAX_OUTPUT_BYTES",
    "LaptopBridge",
    "LaptopBridgeError",
    "LaptopBridgeTimeout",
    "LaptopConnection",
    "LaptopDisconnected",
    "LaptopNotConnected",
    "laptop_bridge",
    "normalise_laptop_id",
    "shell_execution_enabled",
]
