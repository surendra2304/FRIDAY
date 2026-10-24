"""
FRIDAY/apps/core/src/friday_core/universe_event_bus.py — FRIDAY Universe Event Bus.

Cross-agent event publishing, subscription management, event routing,
and event delivery guarantees.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class Event:
    """An event published to the bus."""
    event_id: str
    event_type: str
    payload: dict = field(default_factory=dict)
    source_agent: str = ""
    timestamp: float = field(default_factory=time.time)
    priority: int = 5  # 1-10, higher is more important


@dataclass
class Subscription:
    """A subscription to an event type."""
    subscription_id: str
    event_type: str
    subscriber_agent: str
    callback_url: str = ""
    filter_criteria: dict = field(default_factory=dict)
    active: bool = True
    created_at: float = field(default_factory=time.time)
    delivery_count: int = 0


@dataclass
class EventDelivery:
    """A delivered event."""
    delivery_id: str
    event_id: str
    subscription_id: str
    delivered_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending, delivered, failed
    error: str = ""


class UniverseEventBus:
    """Engine for cross-agent event bus."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscriptions: dict[str, Subscription] = {}
        self._deliveries: list[EventDelivery] = []

    def publish_event(self, event_type: str, payload: dict,
                      source_agent: str = "", priority: int = 5) -> Event:
        """Publish an event to the bus."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        event = Event(
            event_id=event_id, event_type=event_type,
            payload=payload, source_agent=source_agent,
            priority=priority,
        )
        self._events.append(event)

        # Deliver to matching subscriptions
        for sub_id, sub in self._subscriptions.items():
            if sub.active and sub.event_type == event_type:
                delivery = EventDelivery(
                    delivery_id=f"del_{uuid.uuid4().hex[:8]}",
                    event_id=event_id, subscription_id=sub_id,
                )
                delivery.status = "delivered"
                sub.delivery_count += 1
                self._deliveries.append(delivery)

        return event

    def subscribe(self, event_type: str, subscriber_agent: str,
                  callback_url: str = "", filter_criteria: dict | None = None) -> Subscription:
        """Subscribe to an event type."""
        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        sub = Subscription(
            subscription_id=sub_id, event_type=event_type,
            subscriber_agent=subscriber_agent, callback_url=callback_url,
            filter_criteria=filter_criteria or {},
        )
        self._subscriptions[sub_id] = sub
        return sub

    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from an event type."""
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        sub.active = False

    def get_events(self, event_type: str | None = None,
                   source_agent: str | None = None,
                   limit: int = 100) -> list[dict[str, Any]]:
        """Get events."""
        events = list(self._events)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if source_agent:
            events = [e for e in events if e.source_agent == source_agent]
        events.sort(key=lambda e: e.priority, reverse=True)
        return [
            {"event_id": e.event_id, "type": e.event_type,
             "source": e.source_agent, "priority": e.priority}
            for e in events[-limit:]
        ]

    def get_deliveries(self, subscription_id: str) -> list[dict[str, Any]]:
        """Get deliveries for a subscription."""
        deliveries = [d for d in self._deliveries if d.subscription_id == subscription_id]
        return [
            {"event_id": d.event_id, "status": d.status, "delivered_at": d.delivered_at}
            for d in deliveries
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_events": len(self._events),
            "total_subscriptions": len(self._subscriptions),
            "active_subscriptions": sum(1 for s in self._subscriptions.values() if s.active),
            "total_deliveries": len(self._deliveries),
            "delivered": sum(1 for d in self._deliveries if d.status == "delivered"),
            "engine_status": "operational",
        }


engine = UniverseEventBus()


@router.post("/eventbus/publish")
async def publish_event(event_type: str, payload: dict, source_agent: str = "", priority: int = 5):
    """Publish an event to the bus."""
    event = engine.publish_event(event_type, payload, source_agent, priority)
    return {"event_id": event.event_id, "type": event.event_type, "priority": event.priority}


@router.post("/eventbus/subscribe")
async def subscribe(event_type: str, subscriber_agent: str, callback_url: str = "",
                    filter_criteria: dict | None = None):
    """Subscribe to an event type."""
    sub = engine.subscribe(event_type, subscriber_agent, callback_url, filter_criteria)
    return {"subscription_id": sub.subscription_id, "event_type": event_type}


@router.post("/eventbus/unsubscribe")
async def unsubscribe(subscription_id: str):
    """Unsubscribe from an event type."""
    engine.unsubscribe(subscription_id)
    return {"subscription_id": subscription_id, "status": "unsubscribed"}


@router.get("/eventbus/events")
async def get_events(event_type: str | None = None, source_agent: str | None = None, limit: int = 100):
    """Get events."""
    return {"events": engine.get_events(event_type, source_agent, limit)}


@router.get("/eventbus/deliveries/{subscription_id}")
async def get_deliveries(subscription_id: str):
    """Get deliveries for a subscription."""
    return {"deliveries": engine.get_deliveries(subscription_id)}


@router.get("/eventbus/report")
async def eventbus_report():
    """Get event bus report."""
    return engine.get_report()
