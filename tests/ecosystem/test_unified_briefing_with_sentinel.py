"""Master briefing must use measured local data and label unprobed services."""

from friday.ecosystem.registry import EcosystemRegistry
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow


def test_master_morning_briefing_includes_sentinel_security():
    registry = EcosystemRegistry()
    workflow = MasterDailyBriefingWorkflow(registry=registry)

    snapshot = workflow.generate_morning_briefing()
    assert snapshot.briefing_type == "MORNING"

    # Default registry entries have no live probes; they must not invent telemetry.
    spoken = snapshot.spoken_summary
    assert "8 registered Friday Universe services" in spoken
    assert "unverified because no live probe is configured" in spoken
    assert "no verified trading, lead, research, or forecast figures" in spoken

    md = snapshot.markdown_report
    assert "Stratex" in md
    assert "Sentinel" in md
    assert "UNVERIFIED" in md
    assert "$10,450" not in md
    assert "1,420" not in md
    assert "412.0ms" not in md
