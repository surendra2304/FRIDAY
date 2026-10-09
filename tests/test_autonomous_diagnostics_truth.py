from types import SimpleNamespace

import pytest

from friday.autonomous import controller as controller_module


@pytest.mark.asyncio
async def test_self_diagnostic_never_claims_repairs_without_performing_them(monkeypatch):
    monkeypatch.setattr(controller_module.psutil, "process_iter", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        controller_module.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=50.0, available=2 * 1024**3),
    )

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
async def test_peer_task_without_receipt_is_not_reported_as_task_completion(monkeypatch):
    from friday.cognition.mesh import HarnessBehaviour, Mesh, build_contracts

    contracts = build_contracts(controller_module.fleet_client)
    mesh, transport = Mesh.in_process(contracts, attempts=1, backoff_seconds=0.0)
    transport.behave("intelx", HarnessBehaviour(receipt=False))
    controller = controller_module.AutonomousController()
    monkeypatch.setattr(controller, "_peer_mesh", mesh, raising=False)

    result = await controller.execute_agent_control("intelx", "research today's news")

    assert result["metadata"]["success"] is False
    assert result["metadata"]["task_completion_verified"] is False
    assert result["metadata"]["task_state"] == "UNVERIFIED"
    assert "no receipt" in result["reply"].lower()
    assert len(transport.calls) == 1
    assert transport.calls[0].json_body["objective"] == "research today's news"
