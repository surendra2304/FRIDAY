"""Real-time activity stream registry for FRIDAY dashboard WebSocket clients.

Kept deliberately simple: a process-global set of connected WebSocket clients and a
direct broadcast helper. No pub/sub, no broker.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from friday.core.logging import get_logger

logger = get_logger("api.activity_stream")

_clients: set[WebSocket] = set()


def register(websocket: WebSocket) -> None:
    _clients.add(websocket)


def unregister(websocket: WebSocket) -> None:
    _clients.discard(websocket)


async def broadcast(event: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in list(_clients):
        try:
            await ws.send_json(event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Activity stream send failed: %s", exc)
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def emit(event: dict[str, Any]) -> None:
    """Fire-and-forget broadcast from sync or async contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop.is_running():
        loop.create_task(broadcast(event))


def client_count() -> int:
    return len(_clients)
