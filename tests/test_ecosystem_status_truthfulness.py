from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from friday.ecosystem.fleet_client import AgentStatus, FleetClient
from friday.core.config import Settings
from friday.skills.ecosystem_status import EcosystemStatusSkill


class _FakeFleet:
    async def get_all_statuses(self, force_refresh=False):
        return [
            AgentStatus(
                id="memora", name="Memora", role="Memory", icon="m", status="ONLINE",
                latency_ms=37, endpoint="https://memora.example", details="HTTP 200 health endpoint; read/write not tested.",
                last_checked="2026-09-26T00:00:00+00:00",
            ),
        ]


def test_live_status_is_evidence_labelled_and_omits_demo_metrics():
    report = EcosystemStatusSkill(fleet=_FakeFleet()).execute("status of all agents")
    assert report.success is True
    assert "Memora | HEALTH_ENDPOINT_OK" in report.output
    assert "Inference | UNVERIFIED" in report.output
    assert "read/write not tested" in report.output
    for fabricated in ("10,450", "0.082", "all systems nominal", "89.2%"):
        assert fabricated not in report.output
    assert "does not verify background jobs" in report.output


def test_status_with_registry_only_never_treats_unverified_as_healthy():
    from friday.ecosystem.registry import EcosystemRegistry

    report = EcosystemStatusSkill(registry=EcosystemRegistry()).execute("health of all systems")
    assert report.success is True
    assert "UNVERIFIED" in report.output
    assert "live reachability was not tested" in report.output
    assert "HEALTHY" not in report.output


def test_fleet_client_uses_settings_and_never_invents_peer_keys(monkeypatch):
    for name in (
        "INFERENCE_API_KEY", "MEMORA_API_KEY", "STRATEX_API_KEY", "INTELX_API_KEY",
        "FUTURIS_API_KEY", "CORTEX_API_KEY", "FORGE_API_KEY", "SENTINEL_API_KEY",
        "INFERENCE_URL", "MEMORA_URL", "STRATEX_URL", "INTELX_URL", "FUTURIS_URL",
        "CORTEX_URL", "FORGE_URL", "SENTINEL_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = SimpleNamespace(
        inference_url="https://inference.example", inference_api_key=None,
        memora_url="https://memora.example", memora_api_key=None,
        stratex_url="https://stratex.example", stratex_api_key=None,
        intelx_url="https://intelx.example", intelx_api_key=None,
        futuris_url="https://futuris.example", futuris_api_key=None,
        cortex_url="https://cortex.example", cortex_api_key=None,
        forge_url="https://forge.example", forge_api_key=None,
        sentinel_url="https://sentinel.example", sentinel_api_key=None,
    )
    client = FleetClient(settings=settings)
    assert client.memora_url == "https://memora.example"
    assert all(not getattr(client, f"{name}_key") for name in (
        "inference", "memora", "stratex", "intelx", "futuris", "cortex", "forge", "sentinel",
    ))


def test_fleet_client_url_resolution_prefers_friday_namespaced_env(monkeypatch):
    monkeypatch.setenv("FRIDAY_MEMORA_URL", "http://127.0.0.1:9300")
    monkeypatch.setenv("MEMORA_URL", "http://127.0.0.1:9301")
    settings = Settings(env="testing", _env_file=None)

    client = FleetClient(settings=settings)

    assert client.memora_url == "http://127.0.0.1:9300"


@pytest.mark.anyio
async def test_memora_health_probe_does_not_send_placeholder_auth():
    client = FleetClient(settings=SimpleNamespace(
        inference_url="", inference_api_key=None, memora_url="https://memora.example", memora_api_key=None,
        stratex_url="", stratex_api_key=None, intelx_url="", intelx_api_key=None,
        futuris_url="", futuris_api_key=None, cortex_url="", cortex_api_key=None,
        forge_url="", forge_api_key=None, sentinel_url="", sentinel_api_key=None,
    ))
    response = SimpleNamespace(status_code=200, json=lambda: {"status": "healthy"})
    http = SimpleNamespace(get=AsyncMock(return_value=response))
    status = await client.probe_memora(http)
    headers = http.get.await_args.kwargs["headers"]
    assert "Authorization" not in headers
    assert status.status == "ONLINE"
