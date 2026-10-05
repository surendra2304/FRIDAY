"""BUG-005: eight unreachable peers were reported as eight observed responses.

The audit found the controller producing ``{"status": "OBSERVED", "responses": 8}``
on a machine where no peer could be reached at all. Two layers had to agree for
that to happen, and both are pinned here:

* every ``probe_*`` in `fleet_client` returned ``status="DEGRADED"`` when the
  connection itself failed, which asserts that the peer answered and is
  unhealthy - the opposite of what a connection error means;
* the controller counted the returned objects rather than the answers, so eight
  non-answers became eight "responses".

Either half alone is enough to invert the evidence, so both are asserted.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from friday.autonomous import controller as controller_module
from friday.ecosystem import fleet_client as fleet_client_module
from friday.ecosystem.fleet_client import FleetClient


@pytest.mark.parametrize(
    "probe_name",
    [
        "probe_inference",
        "probe_memora",
        "probe_stratex",
        "probe_intelx",
        "probe_futuris",
        "probe_cortex",
        "probe_forge",
        "probe_sentinel",
    ],
)
def test_a_connection_error_is_unreachable_not_degraded(
    probe_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEGRADED claims the peer answered. A connection error means it did not."""
    client = FleetClient()

    class DeadClient:
        async def get(self, *args, **kwargs):
            raise ConnectionError("name resolution failed")

        async def post(self, *args, **kwargs):
            raise ConnectionError("name resolution failed")

    status = __import__("asyncio").run(getattr(client, probe_name)(DeadClient()))

    assert status.status == "UNREACHABLE", (
        f"{probe_name} reported {status.status!r} for a peer that never answered"
    )
    assert "DEGRADED" != status.status


@pytest.mark.asyncio
async def test_the_diagnostic_does_not_count_non_answers_as_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact inversion the audit recorded: eight unreachable, eight reported."""

    async def all_unreachable(force_refresh: bool = False):
        return [
            SimpleNamespace(id=name, status="UNREACHABLE")
            for name in (
                "inference",
                "memora",
                "stratex",
                "intelx",
                "futuris",
                "cortex",
                "forge",
                "sentinel",
            )
        ]

    monkeypatch.setattr(controller_module.fleet_client, "get_all_statuses", all_unreachable)
    result = await controller_module.AutonomousController().execute_self_repair()

    fleet = next(
        check for check in result["metadata"]["checks"] if check["name"] == "peer_health_endpoints"
    )
    assert fleet["status"] == "UNAVAILABLE", "no peer answered, so this cannot be OBSERVED"
    assert fleet["evidence"]["responded"] == 0
    assert fleet["evidence"]["unreachable"] == 8
    assert set(fleet["evidence"]["unreachable_peers"]) == {
        "inference",
        "memora",
        "stratex",
        "intelx",
        "futuris",
        "cortex",
        "forge",
        "sentinel",
    }
    assert "responses" not in fleet["evidence"], "a non-answer is not a response"


@pytest.mark.asyncio
async def test_a_partly_reachable_fleet_reports_both_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mixed(force_refresh: bool = False):
        return [
            SimpleNamespace(id="inference", status="ONLINE"),
            SimpleNamespace(id="memora", status="UNREACHABLE"),
        ]

    monkeypatch.setattr(controller_module.fleet_client, "get_all_statuses", mixed)
    result = await controller_module.AutonomousController().execute_self_repair()

    fleet = next(
        check for check in result["metadata"]["checks"] if check["name"] == "peer_health_endpoints"
    )
    assert fleet["status"] == "OBSERVED"
    assert fleet["evidence"]["responded"] == 1
    assert fleet["evidence"]["unreachable"] == 1
    assert fleet["evidence"]["unreachable_peers"] == ["memora"]


def test_the_agent_status_vocabulary_names_the_fifth_state() -> None:
    """The dataclass comment is the contract other code reads before trusting it."""
    source = (
        __import__("pathlib").Path(fleet_client_module.__file__).read_text(encoding="utf-8")
    )
    assert "ONLINE, REACHABLE, DEGRADED, UNREACHABLE, or OFFLINE" in source
