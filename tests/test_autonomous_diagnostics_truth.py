from types import SimpleNamespace

import pytest

from friday.autonomous import controller as controller_module


@pytest.mark.asyncio
async def test_self_diagnostic_never_claims_repairs_without_performing_them(monkeypatch):
    async def statuses(force_refresh=False):
        assert force_refresh is True
        return [SimpleNamespace(status="ONLINE"), SimpleNamespace(status="DEGRADED")]

    monkeypatch.setattr(controller_module.fleet_client, "get_all_statuses", statuses)
    result = await controller_module.AutonomousController().execute_self_repair()

    assert result["metadata"]["repairs_attempted"] == []
    assert result["metadata"]["success"] is False
    assert result["metadata"]["status"] == "UNVERIFIED"
    assert "No repair was attempted" in result["reply"]
    fleet = next(check for check in result["metadata"]["checks"] if check["name"] == "peer_health_endpoints")
    assert fleet["status"] == "OBSERVED"
    assert fleet["evidence"]["scope"].startswith("HTTP health/status endpoint responses only")


@pytest.mark.asyncio
async def test_inference_fallback_is_advisory_and_not_a_scheduled_retry(monkeypatch):
    async def no_answer(_question):
        return {"reply": "", "metadata": {"error": "offline"}}

    monkeypatch.setattr(controller_module.fleet_client, "ask_inference", no_answer)
    result = await controller_module.AutonomousController().autonomous_failover("stratex", "check paper position")

    assert result["metadata"]["success"] is False
    assert result["metadata"]["task_completion_verified"] is False
    assert "not scheduled for retry" in result["reply"]


@pytest.mark.asyncio
async def test_agent_status_response_is_not_reported_as_task_completion(monkeypatch):
    async def status_response(_directive):
        return {"reply": "Health endpoint returned HTTP 200", "metadata": {"agent_id": "intelx"}}

    monkeypatch.setattr(controller_module.fleet_client, "ask_intelx", status_response)
    result = await controller_module.AutonomousController().execute_agent_control("intelx", "research today's news")

    assert result["metadata"]["success"] is False
    assert result["metadata"]["task_completion_verified"] is False
    assert "Requested task completion is not verified" in result["reply"]
