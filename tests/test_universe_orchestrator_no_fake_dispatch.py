"""TASK-CORE-002: the live path must not report a dispatch it did not perform."""

from friday.integrations.universe_orchestrator import UniverseOrchestrator


class _Fleet:
    def __init__(self, summary=None, error: Exception | None = None) -> None:
        self.summary = summary
        self.error = error
        self.calls = 0

    async def get_fleet_summary(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.summary


def test_live_path_probes_fleet_and_does_not_claim_dispatch():
    fleet = _Fleet(
        summary={
            "reply": "probe",
            "metadata": {"online_count": 3, "total_count": 9, "agents": []},
        }
    )
    orchestrator = UniverseOrchestrator()
    orchestrator.fleet = fleet

    result = orchestrator.execute_universe_goal("delegate to forge: review the auth middleware")

    assert fleet.calls == 1
    assert result["raw_result"]["status"] == "not_executed"
    assert result["raw_result"]["reason"] == "no_universe_api"
    assert result["raw_result"]["status"] != "dispatched"
    assert "fleet_sync" not in result["metrics"]
    assert result["agent_count"] == 3
    assert result["metrics"]["online_count"] == 3
    assert result["metrics"]["total_count"] == 9
    assert result["metrics"]["real_agents"] == 3
    assert result["total_steps"] == 0
    assert result["world_id"] is None
    assert "not executed" in result["synthesis"].lower()
    assert "8 Specialist" not in result["synthesis"]


def test_live_path_probe_failure_is_not_success():
    fleet = _Fleet(error=ConnectionError("peers down"))
    orchestrator = UniverseOrchestrator()
    orchestrator.fleet = fleet

    result = orchestrator.execute_universe_goal("fleet status of all agents")

    assert fleet.calls == 1
    assert result["raw_result"]["status"] == "not_executed"
    assert result["agent_count"] == 0
    assert result["metrics"] == {}
    assert "peers down" in result["raw_result"]["error"]
    assert "not executed" in result["synthesis"].lower()
