# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY FORGE Task Manager & Deep Integration."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.core.doctor import DiagnosticStatus, FridayDoctor
from friday.integrations.forge_auth import ForgeAuthClient
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.forge_health_operator import ForgeHealthOperator
from friday.operators.forge_supervisor_operator import ForgeSupervisorOperator
from friday.skills.forge_manager import ForgeManagerSkill
from friday.skills.forge_templates import ForgeTemplateLibrary, TaskTemplateType
from friday.workflows.forge_review_workflow import ForgeReviewWorkflow


@pytest.fixture
def forge_manager_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    auth_client = ForgeAuthClient(rate_limit_per_min=10)

    forge_manager = ForgeManagerSkill(auth_client=auth_client, memory=memory)
    supervisor = ForgeSupervisorOperator(forge_manager=forge_manager, alert_manager=alert_mgr, memory=memory)
    health_op = ForgeHealthOperator(forge_manager=forge_manager, alert_manager=alert_mgr, memory=memory)
    review_wf = ForgeReviewWorkflow(forge_manager=forge_manager)
    doctor = FridayDoctor()

    return forge_manager, supervisor, health_op, review_wf, doctor, alert_mgr


# =========================================================================
# 1. FORGE Template Library Tests
# =========================================================================

def test_forge_template_library_expansion():
    """Verify template detection and structured specification expansion."""
    assert ForgeTemplateLibrary.detect_template_type("Build a portfolio website") == TaskTemplateType.WEBSITE
    assert ForgeTemplateLibrary.detect_template_type("Create a CLI log analyzer") == TaskTemplateType.CLI_TOOL
    assert ForgeTemplateLibrary.detect_template_type("Build a FastAPI order router") == TaskTemplateType.API_SERVICE
    assert ForgeTemplateLibrary.detect_template_type("Build a real-time risk dashboard") == TaskTemplateType.DASHBOARD
    assert ForgeTemplateLibrary.detect_template_type("Write a Python script for backup") == TaskTemplateType.SCRIPT

    expanded_site = ForgeTemplateLibrary.expand_goal("Build a portfolio website")
    assert "semantic HTML5" in expanded_site
    assert "dark mode toggle" in expanded_site

    expanded_cli = ForgeTemplateLibrary.expand_goal("Create a CLI tool", {"name": "risk_cli"})
    assert "argparse" in expanded_cli


# =========================================================================
# 2. FORGE Manager Skill Core Methods Tests
# =========================================================================

def test_forge_manager_core_methods(forge_manager_setup):
    """Verify all REST API manager methods: submit, status, logs, inspect, list, artifacts, cancel, health."""
    forge_mgr, supervisor, health_op, review_wf, doctor, alert_mgr = forge_manager_setup

    # 1. submit_build_request
    res = forge_mgr.submit_build_request("Build a FastAPI service for options pricing", options={"priority": "HIGH"})
    tid = res["task_id"]
    assert "forge_task_" in tid
    assert res["status"] == "READY"
    assert "FastAPI" in res["expanded_specification"]

    # 2. get_task_status
    status = forge_mgr.get_task_status(tid)
    assert status["task_id"] == tid
    assert status["state"] == "READY"

    # 3. get_task_logs
    logs = forge_mgr.get_task_logs(tid)
    assert len(logs["logs"]) >= 1

    # 4. inspect_task
    insp = forge_mgr.inspect_task("forge_task_01")
    assert insp["state"] == "COMPLETED"
    assert insp["test_coverage_pct"] == 96.0
    assert len(insp["files_created"]) == 4

    # 5. list_tasks
    task_list = forge_mgr.list_tasks(limit=10)
    assert task_list["total_tasks_count"] >= 3

    # 6. get_artifacts
    arts = forge_mgr.get_artifacts("forge_task_01")
    assert "dist/portfolio_website_v1.0.zip" in arts["delivery_package_path"]

    # 7. cancel_task
    cancel_res = forge_mgr.cancel_task(tid)
    assert cancel_res["cancelled"] is True
    assert forge_mgr.get_task_status(tid)["state"] == "CANCELLED"

    # 8. get_forge_health
    health = forge_mgr.get_forge_health()
    assert health["status"] == "HEALTHY"
    assert health["ai_universe_connection"] == "CONNECTED"


# =========================================================================
# 3. Voice Commands Integration (SAFE & SENSITIVE)
# =========================================================================

def test_forge_manager_voice_commands(forge_manager_setup):
    """Verify SAFE and SENSITIVE voice command execution."""
    forge_mgr, supervisor, health_op, review_wf, doctor, alert_mgr = forge_manager_setup

    # SAFE: Forge status
    res_status = forge_mgr.execute("Forge status")
    assert res_status.success is True
    assert "FORGE Software Engineering Engine status: HEALTHY" in res_status.output

    # SAFE: List tasks
    res_list = forge_mgr.execute("What tasks has Forge been assigned?")
    assert res_list.success is True
    assert "FORGE has been assigned" in res_list.output

    # SAFE: How is the build going
    res_going = forge_mgr.execute("How is the portfolio build going?")
    assert res_going.success is True
    assert "is currently in state COMPLETED" in res_going.output

    # SAFE: Show what forge built
    res_built = forge_mgr.execute("Show me what Forge built")
    assert res_built.success is True
    assert "Inspection for completed build" in res_built.output

    # SAFE: Forge logs
    res_logs = forge_mgr.execute("Forge logs")
    assert res_logs.success is True
    assert "Recent FORGE logs" in res_logs.output

    # SAFE: What did forge deliver
    res_deliv = forge_mgr.execute("What did Forge deliver?")
    assert res_deliv.success is True
    assert "FORGE has delivered" in res_deliv.output

    # SENSITIVE: Ask Forge to build
    res_build = forge_mgr.execute("Forge, build me a portfolio website")
    assert res_build.success is True
    assert "Understood. I have expanded your goal" in res_build.output

    # SENSITIVE: Cancel the task
    res_cancel = forge_mgr.execute("Cancel the Forge task")
    assert res_cancel.success is True
    assert "successfully CANCELLED" in res_cancel.output


# =========================================================================
# 4. Supervisor Operator, Health Operator & Doctor Tests
# =========================================================================

def test_forge_supervisor_and_health_operator(forge_manager_setup):
    """Verify supervisor operator alerts, health operator uptime tracking, and doctor integration."""
    forge_mgr, supervisor, health_op, review_wf, doctor, alert_mgr = forge_manager_setup

    # Supervisor Operator tick
    events = supervisor.tick()
    assert isinstance(events, list)
    assert any(e["type"] == "TASK_COMPLETED" for e in events)

    # Health Operator tick
    health_events = health_op.tick()
    assert isinstance(health_events, list)
    assert health_op.get_uptime_ratio() == 100.0

    # FridayDoctor diagnose_forge
    diag = doctor.diagnose_forge()
    assert diag.status == DiagnosticStatus.AVAILABLE
    assert "http://localhost:8001" in diag.message

    full_report = doctor.run_full_diagnostics()
    assert "forge_engine" in full_report.components
    assert full_report.components["forge_engine"].status == DiagnosticStatus.AVAILABLE


# =========================================================================
# 5. Deliverable Review Workflow Tests
# =========================================================================

def test_forge_review_workflow(forge_manager_setup):
    """Verify automated inspection and review summary generation."""
    forge_mgr, supervisor, health_op, review_wf, doctor, alert_mgr = forge_manager_setup

    assert review_wf.can_handle("review what forge built") is True
    assert review_wf.can_handle("unrelated query") is False

    snapshot = review_wf.generate_review("forge_task_01")
    assert snapshot.task_id == "forge_task_01"
    assert snapshot.all_verification_passed is True
    assert "all verification checks passed" in snapshot.spoken_summary
    assert "# 🛠️ FORGE Deliverable Review" in snapshot.markdown_report
    assert "🟢 ALL PASSED" in snapshot.markdown_report
