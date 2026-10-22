"""The shared async peer client must not outlive its owner."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from friday.ecosystem.fleet_client import FleetClient


def test_shared_async_client_can_be_closed_and_lazily_recreated() -> None:
    """A closed pool is released, and the next operation gets a fresh client."""
    fleet = FleetClient(settings=SimpleNamespace())
    first = fleet.get_shared_client()

    assert first.is_closed is False
    asyncio.run(fleet.aclose())

    assert first.is_closed is True
    assert fleet._shared_client is None

    second = fleet.get_shared_client()
    assert second is not first
    assert second.is_closed is False
    asyncio.run(fleet.aclose())
    assert second.is_closed is True


@pytest.mark.asyncio
async def test_api_lifespan_closes_its_shared_fleet_client(monkeypatch) -> None:
    """Shutdown waits for supervised tasks, then closes the shared HTTP pool."""
    from friday.api import server

    fleet = FleetClient(settings=SimpleNamespace())
    monkeypatch.setattr(server, "fleet_client", fleet)

    async def wait_for_cancellation() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(server, "_fleet_supervision_loop", wait_for_cancellation)
    monkeypatch.setattr(server, "_memora_event_loop", wait_for_cancellation)
    monkeypatch.setattr(server, "_reflex_loop", wait_for_cancellation)
    monkeypatch.setattr(server, "_configure_memory_mirror", wait_for_cancellation)
    monkeypatch.setattr(server.repair_loop, "run_forever", wait_for_cancellation)

    client = fleet.get_shared_client()
    async with server.app.router.lifespan_context(server.app):
        assert client.is_closed is False

    assert client.is_closed is True
    assert fleet._shared_client is None
