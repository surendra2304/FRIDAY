# -*- coding: utf-8 -*-
"""End-to-End Test: Master Daily Briefing with Sentinel Security Integration.

Validates:
1. MasterDailyBriefingWorkflow synthesizes 5 core pillars:
   - Trading Bot quantitative performance
   - Forge software deliveries
   - Nexus website traffic & incidents
   - Sentinel security posture score & vulnerabilities
   - AI-Universe predictive advisory
2. Spoken debrief contains security posture.
3. Markdown report renders full security section.
"""

from friday.ecosystem.registry import EcosystemRegistry
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow


def test_master_morning_briefing_includes_sentinel_security():
    registry = EcosystemRegistry()
    workflow = MasterDailyBriefingWorkflow(registry=registry)

    snapshot = workflow.generate_morning_briefing()
    assert snapshot.briefing_type == "MORNING"

    # 1. Verify spoken summary includes security
    spoken = snapshot.spoken_summary
    assert "Trading Bot is" in spoken
    assert "Forge is" in spoken
    assert "Nexus website" in spoken
    assert "Sentinel security posture is" in spoken

    # 2. Verify Markdown report includes Section 4 (Sentinel) and Section 5 (IntelX)
    md = snapshot.markdown_report
    assert "1. Quantitative Trading Overview" in md
    assert "2. FORGE Software Engineering Status" in md
    assert "3. Nexus Website & Growth Intelligence" in md
    assert "4. Sentinel Autonomous Security & Vulnerability Posture" in md
    assert "5. IntelX Autonomous Deep Research" in md
    assert "6. AI-Universe Intelligence & Advisory" in md
