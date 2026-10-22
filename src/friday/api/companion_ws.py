"""Real-Time WebSocket Companion Event Multiplexer for FRIDAY.

Provides bidirectional desktop telemetry streaming, subscription-based event multiplexing,
and ambient awareness event distribution for holographic, desktop overlay, and remote clients.

Supported event topics:
- "telemetry": Real-time CPU, RAM, battery, active window, network I/O
- "reflex": Cognition reflex incidents, self-repair proposals, proof results
- "tasks": TaskGraphScheduler sweeps, autonomous daily goals, execution progress
- "fleet": Specialist agent mesh reachability, circuit breaker states, ping latencies
- "voice": Voice session, audio waveforms, gesture acknowledgments
- "system": Health, alerts, proactive announcements
- "*": Wildcard / all topics
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

from fastapi import WebSocket, WebSocketDisconnect

from friday.core.logging import get_logger

logger = get_logger("api.companion_ws")


@dataclass
class ClientSubscription:
    """Represents an active companion WebSocket client connection."""
    websocket: WebSocket
    client_id: str
    topics: set[str] = field(default_factory=lambda: {"telemetry", "system"})
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages_sent: int = 0
    messages_received: int = 0


class CompanionEventMultiplexer:
    """Thread-safe / asyncio-safe pub-sub event multiplexer for WebSocket clients."""

    def __init__(self, default_topics: Optional[set[str]] = None) -> None:
        self.default_topics = default_topics or {"telemetry", "system"}
        self._clients: dict[WebSocket, ClientSubscription] = {}
        self._lock = asyncio.Lock()
        self._telemetry_task: Optional[asyncio.Task[None]] = None
        self._telemetry_running = False

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str = "",
        initial_topics: Optional[set[str]] = None,
    ) -> ClientSubscription:
        """Register a newly accepted WebSocket connection."""
        topics = set(initial_topics) if initial_topics is not None else set(self.default_topics)
        sub = ClientSubscription(
            websocket=websocket,
            client_id=client_id or f"client_{id(websocket)}",
            topics=topics,
        )
        async with self._lock:
            self._clients[websocket] = sub
        logger.info("Companion WS client '%s' registered with topics %s", sub.client_id, list(topics))
        return sub

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket connection."""
        async with self._lock:
            sub = self._clients.pop(websocket, None)
        if sub:
            logger.info("Companion WS client '%s' disconnected", sub.client_id)

    def subscribe(self, websocket: WebSocket, topics: list[str]) -> set[str]:
        """Subscribe an existing client to one or more topics."""
        sub = self._clients.get(websocket)
        if not sub:
            return set()
        for t in topics:
            norm_t = t.strip().lower()
            if norm_t:
                sub.topics.add(norm_t)
        return set(sub.topics)

    def unsubscribe(self, websocket: WebSocket, topics: list[str]) -> set[str]:
        """Unsubscribe an existing client from one or more topics."""
        sub = self._clients.get(websocket)
        if not sub:
            return set()
        for t in topics:
            norm_t = t.strip().lower()
            sub.topics.discard(norm_t)
        return set(sub.topics)

    def is_subscribed(self, sub: ClientSubscription, topic: str) -> bool:
        """Check if subscription matches target topic (supports wildcard '*')."""
        norm_t = topic.strip().lower()
        return "*" in sub.topics or "all" in sub.topics or norm_t in sub.topics

    async def broadcast(self, topic: str, event_type: str, data: dict[str, Any]) -> int:
        """Broadcast an event payload to all clients subscribed to target topic."""
        norm_topic = topic.strip().lower()
        envelope = {
            "type": event_type,
            "topic": norm_topic,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        async with self._lock:
            eligible_clients = [
                sub for sub in self._clients.values()
                if self.is_subscribed(sub, norm_topic)
            ]

        if not eligible_clients:
            return 0

        dead_connections: list[WebSocket] = []
        delivered = 0

        for sub in eligible_clients:
            try:
                await sub.websocket.send_json(envelope)
                sub.messages_sent += 1
                delivered += 1
            except (WebSocketDisconnect, RuntimeError):
                dead_connections.append(sub.websocket)
            except Exception as exc:
                logger.warning("Error sending WS to '%s': %s", sub.client_id, exc)
                dead_connections.append(sub.websocket)

        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    self._clients.pop(ws, None)

        return delivered

    def emit_event(self, topic: str, event_type: str, data: dict[str, Any]) -> None:
        """Non-blocking fire-and-forget broadcast trigger from sync or async contexts."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(topic, event_type, data))
        except RuntimeError:
            pass

    async def handle_message(
        self,
        websocket: WebSocket,
        msg: dict[str, Any],
        command_executor: Optional[Callable[[str], Coroutine[Any, Any, dict[str, Any]]]] = None,
        snapshot_getter: Optional[Callable[[], dict[str, Any]]] = None,
    ) -> None:
        """Process incoming client message and respond accordingly."""
        sub = self._clients.get(websocket)
        if sub:
            sub.messages_received += 1

        msg_type = str(msg.get("type", "")).strip().lower()

        if msg_type == "ping":
            await websocket.send_json({
                "type": "pong",
                "client_timestamp": msg.get("timestamp"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        elif msg_type == "subscribe":
            raw_topics = msg.get("topics", [])
            if isinstance(raw_topics, str):
                raw_topics = [raw_topics]
            current = self.subscribe(websocket, raw_topics)
            await websocket.send_json({
                "type": "subscription_updated",
                "status": "ok",
                "topics": sorted(list(current)),
            })

        elif msg_type == "unsubscribe":
            raw_topics = msg.get("topics", [])
            if isinstance(raw_topics, str):
                raw_topics = [raw_topics]
            current = self.unsubscribe(websocket, raw_topics)
            await websocket.send_json({
                "type": "subscription_updated",
                "status": "ok",
                "topics": sorted(list(current)),
            })

        elif msg_type == "get_snapshot":
            data = snapshot_getter() if snapshot_getter else {}
            await websocket.send_json({
                "type": "snapshot",
                "status": "ok",
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        elif msg_type == "command" and command_executor:
            cmd = str(msg.get("command", "")).strip()
            if cmd:
                try:
                    res = await command_executor(cmd)
                    await websocket.send_json({
                        "type": "command_reply",
                        "command": cmd,
                        "reply": res.get("reply", ""),
                        "metadata": res.get("metadata", {}),
                    })
                except Exception as exc:
                    await websocket.send_json({
                        "type": "command_reply",
                        "command": cmd,
                        "error": str(exc),
                    })
            else:
                await websocket.send_json({
                    "type": "command_reply",
                    "error": "Empty command string received",
                })

        else:
            await websocket.send_json({
                "type": "ack",
                "message": f"Received event '{msg_type}'",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def _telemetry_loop(
        self,
        telemetry_getter: Callable[[], dict[str, Any]],
        interval_seconds: float,
    ) -> None:
        """Periodic background task pushing system telemetry to subscribed clients."""
        logger.info("Companion telemetry loop started (interval=%.1fs)", interval_seconds)
        self._telemetry_running = True
        try:
            while self._telemetry_running:
                # Only poll and broadcast if there are connected clients subscribed to telemetry
                has_subscribers = any(
                    self.is_subscribed(sub, "telemetry")
                    for sub in self._clients.values()
                )
                if has_subscribers:
                    try:
                        diag = telemetry_getter()
                        await self.broadcast("telemetry", "system_telemetry", diag)
                    except Exception as exc:
                        logger.warning("Telemetry broadcast error: %s", exc)

                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            pass
        finally:
            self._telemetry_running = False
            logger.info("Companion telemetry loop stopped")

    def start_telemetry_streaming(
        self,
        telemetry_getter: Callable[[], dict[str, Any]],
        interval_seconds: float = 2.5,
    ) -> None:
        """Start background telemetry streaming task if not already running."""
        if self._telemetry_running and self._telemetry_task and not self._telemetry_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._telemetry_running = True
            self._telemetry_task = loop.create_task(
                self._telemetry_loop(telemetry_getter, interval_seconds)
            )
        except RuntimeError:
            pass

    def stop_telemetry_streaming(self) -> None:
        """Stop background telemetry streaming task."""
        self._telemetry_running = False
        if self._telemetry_task and not self._telemetry_task.done():
            self._telemetry_task.cancel()

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic metrics of the companion multiplexer."""
        return {
            "active_clients": len(self._clients),
            "telemetry_streaming": self._telemetry_running,
            "clients": [
                {
                    "client_id": sub.client_id,
                    "topics": sorted(list(sub.topics)),
                    "connected_at": sub.connected_at,
                    "messages_sent": sub.messages_sent,
                    "messages_received": sub.messages_received,
                }
                for sub in self._clients.values()
            ],
        }


# Global singleton instance
companion_multiplexer = CompanionEventMultiplexer()
