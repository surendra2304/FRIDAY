"""FRIDAY's tenth-agent adapter must honor VyralX's documented task contract."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from friday.core.task_envelope import TaskEnvelope, TaskStatus
from friday.ecosystem.fleet_client import FleetClient


def _fleet() -> FleetClient:
    return FleetClient(
        settings=SimpleNamespace(
            vyralx_url="http://vyralx:8000",
            vyralx_api_key="unit-test-key",
        )
    )


@pytest.mark.asyncio
async def test_vyralx_health_probe_is_online_but_does_not_claim_worker_readiness():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        return httpx.Response(
            200,
            json={"status": "ok", "service": "vyralx", "version": "0.2.0"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    status = await _fleet().probe_vyralx(client)
    await client.aclose()

    assert captured["url"] == "http://vyralx:8000/health"
    assert status.id == "vyralx"
    assert status.status == "ONLINE"
    assert "worker heartbeat" in status.details
    assert "not verified" in status.details.lower()


@pytest.mark.asyncio
async def test_dispatch_vyralx_uses_authenticated_idempotent_task_contract(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            202,
            json={
                "task_id": "video-task-123",
                "status": "queued",
                "status_url": "/api/v1/tasks/video-task-123",
                "idempotent_replay": False,
            },
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fleet = _fleet()
    monkeypatch.setattr(fleet, "get_shared_client", lambda: client)
    envelope = TaskEnvelope(
        task_id="video-task-123",
        trace_id="trace-for-video-123",
        target_agent="vyralx",
        action="content.generate",
        payload={
            "topic": "How solar panels generate electricity",
            "video_format": "shorts",
            "target_seconds": 30,
        },
    )

    try:
        result = await fleet.dispatch_task(envelope)
    finally:
        await client.aclose()

    assert captured["url"] == "http://vyralx:8000/api/v1/tasks"
    assert captured["headers"]["authorization"] == "Bearer unit-test-key"
    assert captured["headers"]["x-api-key"] == "unit-test-key"
    assert captured["payload"] == {
        "task_id": "video-task-123",
        "task_type": "content.generate",
        "correlation_id": "trace-for-video-123",
        "input": {
            "topic": "How solar panels generate electricity",
            "video_format": "shorts",
            "target_seconds": 30,
        },
    }
    assert result.status == TaskStatus.PENDING
    assert result.task_id == "video-task-123"
    assert result.result["status_url"] == "/api/v1/tasks/video-task-123"
    assert "pending verification" in result.summary


@pytest.mark.asyncio
async def test_unsupported_vyralx_task_type_fails_closed_without_network(monkeypatch):
    fleet = _fleet()
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("no network request expected"))
    ))
    monkeypatch.setattr(fleet, "get_shared_client", lambda: client)
    envelope = TaskEnvelope(
        task_id="blocked-video-task",
        target_agent="vyralx",
        action="youtube.upload_now",
        payload={"video_id": "unreviewed-video"},
    )

    try:
        result = await fleet.dispatch_task(envelope)
    finally:
        await client.aclose()

    assert result.status == TaskStatus.BLOCKED
    assert "Unsupported VyralX task type" in (result.error or "")
    assert "No task was submitted" in (result.error or "")


@pytest.mark.asyncio
async def test_vyralx_status_query_reads_queue_but_never_submits_a_task(monkeypatch):
    requested = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(
                200, json={"status": "ok", "service": "vyralx"},
                request=request,
            )
        if request.url.path == "/api/v1/tasks":
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "items": [{"status": "queued"}, {"status": "running"}],
                },
                request=request,
            )
        raise AssertionError(f"unexpected request path: {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fleet = _fleet()
    monkeypatch.setattr(fleet, "get_shared_client", lambda: client)

    try:
        result = await fleet.ask_vyralx("VyralX status")
    finally:
        await client.aclose()

    assert requested == [("GET", "/health"), ("GET", "/api/v1/tasks")]
    assert result["metadata"]["task_count"] == 2
    assert result["metadata"]["recent_task_statuses"] == ["queued", "running"]
    assert result["metadata"]["content_task_submitted"] is False
    assert result["metadata"]["publishing_performed"] is False
