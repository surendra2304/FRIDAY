import httpx
import pytest

from friday.core.task_envelope import TaskEnvelope, TaskStatus
from friday.ecosystem.fleet_client import FleetClient


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def post(self, url, **kwargs):
        return self.response(url)


def _response(url, status, payload):
    return httpx.Response(status, json=payload, headers={"content-type": "application/json"}, request=httpx.Request("POST", url))


@pytest.mark.asyncio
async def test_http_200_without_completion_evidence_is_degraded(monkeypatch):
    client = FleetClient(settings=object())
    monkeypatch.setattr(client, "get_shared_client", lambda: FakeClient(lambda url: _response(url, 200, {"status": "ok"})))
    result = await client.dispatch_task(TaskEnvelope(target_agent="forge", action="build", payload={"goal": "change code"}))

    assert result.status == TaskStatus.DEGRADED
    assert result.error == "task_completion_unverified"


@pytest.mark.asyncio
async def test_http_202_is_pending_until_completion_is_verified(monkeypatch):
    client = FleetClient(settings=object())
    monkeypatch.setattr(client, "get_shared_client", lambda: FakeClient(lambda url: _response(url, 202, {"status": "queued"})))
    result = await client.dispatch_task(TaskEnvelope(target_agent="forge", action="build", payload={"goal": "change code"}))

    assert result.status == TaskStatus.PENDING
    assert "pending verification" in result.summary


@pytest.mark.asyncio
async def test_explicit_completed_state_is_success(monkeypatch):
    client = FleetClient(settings=object())
    monkeypatch.setattr(client, "get_shared_client", lambda: FakeClient(lambda url: _response(url, 200, {"state": "completed", "artifact": "diff-123"})))
    result = await client.dispatch_task(TaskEnvelope(target_agent="forge", action="build", payload={"goal": "change code"}))

    assert result.status == TaskStatus.SUCCESS
    assert "completed by forge" in result.summary
