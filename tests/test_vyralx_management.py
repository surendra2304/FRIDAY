"""Comprehensive unit test suite for VyralX 10th agent management across FRIDAY Core.

Tests cover:
1. SpecialistRouter invariants (approval-governed publishing, bypass denial).
2. SpecialistRouter mesh dispatch (endpoint path, auth headers, HTTP 202 handling).
3. AutonomousController command regex parsing and FLEET_AGENTS metadata.
4. Cognition mesh contracts and peer routing.
5. ServiceRegistry and ecosystem status registration.
6. Identity namespace security quarantine.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from friday.agent.prompts import get_default_system_prompt
from friday.agent.router import (
    SPECIALIST_CONFIGS,
    SafetyGateViolationError,
    SpecialistRouter,
    specialist_router,
)
from friday.autonomous.controller import FLEET_AGENTS, AutonomousController
from friday.autonomous.self_repair import NON_OWNER_ACTORS
from friday.cognition.identity import AGENT_NAMESPACE
from friday.cognition.mesh import build_contracts
from friday.core.config import Settings
from friday.core.service_registry import ServiceRegistry
from friday.core.task_envelope import TaskEnvelope, TaskStatus
from friday.ecosystem.fleet_client import fleet_client
from friday.skills.ecosystem_status import _AGENT_NAMES
from friday.skills.help_system import HelpSystemSkill


def test_vyralx_registered_in_all_subsystem_catalogs():
    """Verify VyralX is registered across all global service registries, help, and status mappings."""
    # 1. Router specialist configs
    assert "vyralx" in SPECIALIST_CONFIGS
    cfg = SPECIALIST_CONFIGS["vyralx"]
    assert cfg["default_url"] == "http://vyralx:8000"
    assert "video" in cfg["keywords"]
    assert "youtube" in cfg["keywords"]

    # 2. Autonomous controller fleet agents
    assert "vyralx" in FLEET_AGENTS
    assert FLEET_AGENTS["vyralx"]["name"] == "VYRALX"

    # 3. Security namespaces
    assert "vyralx" in AGENT_NAMESPACE
    assert "vyralx" in NON_OWNER_ACTORS

    # 4. ServiceRegistry
    registry = ServiceRegistry(env="testing")
    assert registry.get("vyralx") is not None
    assert registry.get("vyralx").url.endswith(":8000")

    # 5. Ecosystem status and help skills
    assert _AGENT_NAMES.get("vyralx") == "VyralX"
    help_skill = HelpSystemSkill()
    roster = help_skill.get_capabilities_roster()
    assert "vyralx" in roster

    # 6. Default system prompt mentions all 10 subsystems
    settings = Settings(env="testing")
    prompt = get_default_system_prompt(settings)
    assert "10 interconnected subsystems" in prompt
    assert "VyralX" in prompt


def test_autonomous_controller_parses_vyralx_directives():
    """Verify AutonomousController correctly extracts vyralx from natural language commands."""
    controller = AutonomousController()

    agent, task = controller.detect_agent_directive("friday, tell vyralx to generate short video on AI")
    assert agent == "vyralx"
    assert "generate short video" in task

    agent2, task2 = controller.detect_agent_directive("delegate to vyralx to render youtube thumbnail")
    assert agent2 == "vyralx"
    assert "render youtube thumbnail" in task2

    agent3, task3 = controller.detect_agent_directive("ask vyralx queue status")
    assert agent3 == "vyralx"
    assert "queue status" in task3


def test_cognition_mesh_contracts_include_vyralx():
    """Verify build_contracts produces verified contract for vyralx targeting :8000."""
    contracts = build_contracts(fleet_client)
    assert "vyralx" in contracts
    v_contract = contracts["vyralx"]
    assert v_contract.name == "vyralx"
    assert v_contract.task_path == "/api/v1/tasks"
    assert v_contract.health_path == "/health"
    assert v_contract.auth_style == "x-api-key"


@pytest.mark.asyncio
async def test_vyralx_publishing_approval_invariant_enforced():
    """Verify Safety Invariant 1: VyralX human approval governance cannot be bypassed."""
    router = SpecialistRouter()

    # Attempt direct upload or approval bypass
    forbidden_envelopes = [
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"bypass_approval": True}),
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"direct_upload": "true"}),
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"skip_human_approval": 1}),
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"auto_publish": "yes"}),
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"force_publish_without_review": True}),
        TaskEnvelope(target_agent="vyralx", action="publish", inputs={"publish_now": True}),
    ]

    for env in forbidden_envelopes:
        res = await router.dispatch_envelope(env)
        assert res.status == TaskStatus.BLOCKED
        assert "Safety Invariant 1 Violation" in (res.error or "")
        assert "VyralX human approval governance" in (res.error or "")


@pytest.mark.asyncio
async def test_vyralx_dispatch_envelope_authenticated_and_handles_http_202(monkeypatch):
    """Verify SpecialistRouter dispatches to /api/v1/tasks, attaches auth, and records HTTP 202 as PENDING."""
    router = SpecialistRouter()
    monkeypatch.setenv("FRIDAY_VYRALX_API_KEY", "test-vyralx-key")

    captured = {}

    async def mock_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {
            "status": "queued",
            "task_id": "vyralx-task-789",
            "result": {"queue_position": 1, "status_url": "/api/v1/tasks/vyralx-task-789"},
            "summary": "Video rendering task queued for approval review.",
        }
        return mock_resp

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=mock_post)):
        envelope = TaskEnvelope(
            target_agent="vyralx",
            action="render.create",
            objective="Render 30s educational short on planetary physics",
            inputs={"topic": "planetary physics", "format": "shorts"},
        )

        result = await router.dispatch_envelope(envelope)

        assert captured["url"] == "http://vyralx:8000/api/v1/tasks"
        assert captured["headers"]["X-API-Key"] == "test-vyralx-key"
        assert captured["headers"]["Authorization"] == "Bearer test-vyralx-key"
        assert result.status == TaskStatus.PENDING
        assert result.target_agent == "vyralx"
        assert result.result["queue_position"] == 1
        assert "queued for approval review" in result.summary
