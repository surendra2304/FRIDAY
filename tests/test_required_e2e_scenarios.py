"""Master Acceptance Test Suite for the 10 Required End-to-End Scenarios.

These 10 scenarios verify end-to-end user directives and agent workflows across
all specialist systems in the FRIDAY Universe:
1. Desktop: "FRIDAY, open Notepad."
2. Ambiguous Application: "FRIDAY, open Chrome."
3. Gmail: "FRIDAY, email Alice that the meeting moved to 3 PM."
4. WhatsApp: "FRIDAY, send Rahul a WhatsApp message saying I will call at 6."
5. Research: "FRIDAY, research this company and give me a cited report."
6. Software Engineering: "FRIDAY, fix the failing login test."
7. Security: "FRIDAY, assess my authorized staging server."
8. Forecasting: "FRIDAY, forecast website traffic for tomorrow."
9. Trading: "FRIDAY, check Stratex performance."
10. Cancellation: "FRIDAY, stop the current task."
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.devices.app_launcher import (
    find_all_installations,
    launch_desktop_app,
)
from friday.devices.windows_friday import windows_friday
from friday.ecosystem.e2e_workflow_coordinator import (
    E2EWorkflowCoordinator,
    global_e2e_coordinator,
)


@pytest.fixture
def agent():
    """Construct a testing FridayAgent."""
    settings = Settings(
        env="testing",
        llm_provider="mock",
        agent_name="FRIDAY",
        voice_tts_enabled=False,
    )
    return FridayAgent(settings=settings)


# ==============================================================================
# Scenario 1: Desktop ("FRIDAY, open Notepad.")
# voice capture -> intent -> target resolution -> Windows action ->
# process/window verification -> spoken confirmation
# ==============================================================================
def test_01_desktop_open_notepad_flow(agent):
    """Scenario 1: Open Notepad via voice/text directive with verification."""
    directive = "FRIDAY, open Notepad."

    with patch("friday.devices.app_launcher.launch_desktop_app") as mock_launch:
        mock_launch.return_value = (True, "Opened Windows Notepad.")
        resp = agent.process_message(directive)

        assert resp.is_done is True
        assert "Notepad" in resp.content or "Opened" in resp.content
        assert resp.metadata.get("direct_desktop_action") in ("open_notepad", "open_app")
        assert resp.metadata.get("success") is True
        mock_launch.assert_called_once_with("notepad")


# ==============================================================================
# Scenario 2: Ambiguous Application ("FRIDAY, open Chrome.")
# When multiple installations exist: FRIDAY asks which installation to use;
# MUST NOT open a random executable.
# ==============================================================================
def test_02_ambiguous_application_chrome_flow(agent, monkeypatch):
    """Scenario 2: Detect multiple installations and prompt for clarification."""
    mock_installs = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Users\Surendra\AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
    }
    monkeypatch.setenv("FRIDAY_MOCK_INSTALLATIONS", json.dumps(mock_installs))

    # 1. Verify find_all_installations detects both paths
    candidates = find_all_installations("chrome")
    assert len(candidates) == 2
    assert mock_installs["chrome"][0] in candidates
    assert mock_installs["chrome"][1] in candidates

    # 2. Verify launch_desktop_app refuses to spawn random executable
    with patch("subprocess.Popen") as mock_popen, patch("os.startfile", create=True) as mock_startfile:
        success, msg = launch_desktop_app("chrome")
        assert success is False
        assert "Multiple installations of Google Chrome were found" in msg
        assert "Which installation would you like to use?" in msg
        # Must NOT launch any process
        mock_popen.assert_not_called()
        if hasattr(mock_startfile, "assert_not_called"):
            mock_startfile.assert_not_called()

    # 3. Verify Agent process_message returns the clarification prompt
    directive = "FRIDAY, open Chrome."
    resp = agent.process_message(directive)
    assert resp.is_done is True
    assert "Multiple installations" in resp.content
    assert "Which installation would you like to use?" in resp.content


# ==============================================================================
# Scenario 3: Gmail ("FRIDAY, email Alice that the meeting moved to 3 PM.")
# resolve Alice -> show recipient and generated body -> request or use scoped
# approval -> send through configured provider -> return provider/message result -> store receipt
# ==============================================================================
def test_03_gmail_email_alice_flow(agent):
    """Scenario 3: Direct email directive with contact resolution and receipt."""
    directive = "FRIDAY, email Alice that the meeting moved to 3 PM."

    with patch.object(windows_friday, "open_gmail") as mock_open_gmail:
        mock_open_gmail.return_value = (True, "Opened Gmail compose window in Google Chrome.")

        resp = agent.process_message(directive)
        assert resp.is_done is True

        # Check contact resolution to Alice's email
        assert "alice@example.com" in resp.content or "Alice" in resp.content
        assert "3 PM" in resp.content
        assert "Scoped approval confirmed" in resp.content
        assert "Receipt:" in resp.content

        meta = resp.metadata
        assert meta.get("direct_desktop_action") == "send_email"
        assert meta.get("success") is True


def test_03b_gmail_action_receipt_structure():
    """Verify Gmail produces valid ActionReceipt with audit trail."""
    handled, reply, meta = windows_friday.handle_directive(
        "FRIDAY, email Alice that the meeting moved to 3 PM."
    )
    assert handled is True
    assert "receipt" in meta
    receipt = meta["receipt"]
    assert receipt["action"] == "send_email"
    assert receipt["recipient"] == "alice@example.com"
    assert receipt["status"] == "SENT"
    assert receipt["provider"] == "smtp.gmail.com"
    assert "the meeting moved to 3 pm" in receipt["body"].lower()


# ==============================================================================
# Scenario 4: WhatsApp ("FRIDAY, send Rahul a WhatsApp message saying I will call at 6.")
# resolve Rahul -> confirm contact if ambiguous -> show exact message ->
# use configured authorized bridge -> verify send result -> return receipt
# ==============================================================================
def test_04_whatsapp_message_rahul_flow(agent):
    """Scenario 4: Send WhatsApp message via authorized bridge with receipt."""
    directive = "FRIDAY, send Rahul a WhatsApp message saying I will call at 6."

    with patch.object(windows_friday, "open_whatsapp") as mock_open_wa:
        mock_open_wa.return_value = (True, "Opened WhatsApp Web and dispatched.")

        resp = agent.process_message(directive)
        assert resp.is_done is True
        assert "Rahul" in resp.content
        assert "I will call at 6" in resp.content
        assert "authorized WhatsApp bridge" in resp.content
        assert "Receipt:" in resp.content

        meta = resp.metadata
        assert meta.get("direct_desktop_action") == "send_whatsapp"


def test_04b_whatsapp_contact_ambiguity(agent):
    """Scenario 4 Ambiguity: If multiple Rahuls exist, ask for confirmation."""
    with patch.object(windows_friday, "_lookup_contact_matches") as mock_matches:
        mock_matches.return_value = [
            {"name": "Rahul Sharma", "phone": "+919876543210"},
            {"name": "Rahul Verma", "phone": "+919876543211"},
        ]
        with patch.object(windows_friday, "open_whatsapp") as mock_open_wa:
            mock_open_wa.return_value = (True, "Dispatched.")
            handled, reply, meta = windows_friday.handle_directive(
                "send Rahul a WhatsApp message saying I will call at 6"
            )
            assert handled is True
            assert meta.get("is_ambiguous") is True
            assert "Multiple contacts matching 'Rahul' were found" in reply
            assert "Please confirm which contact to message" in reply
            # Must NOT dispatch to arbitrary phone
            mock_open_wa.assert_not_called()


# ==============================================================================
# Scenario 5: Research ("FRIDAY, research this company and give me a cited report.")
# FRIDAY -> IntelX -> evidence & contradiction analysis -> cited report ->
# optional Memora writeback
# ==============================================================================
def test_05_research_company_cited_report_flow(agent):
    """Scenario 5: IntelX deep research with contradiction analysis and report."""
    directive = "FRIDAY, research this company and give me a cited report."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "IntelX Deep Research Report" in resp.content
    assert "Verified Evidence & Findings" in resp.content
    assert "Contradiction & Disputed Signals" in resp.content
    assert "sec.gov" in resp.content or "http" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "research"
    result = meta.get("result")
    assert result["status"] == "SUCCESS"
    assert len(result["findings"]) >= 2
    assert len(result["contradictions"]) >= 1
    assert result["memora_written"] is True


# ==============================================================================
# Scenario 6: Software Engineering ("FRIDAY, fix the failing login test.")
# FRIDAY -> Inference/ASTRA for plan and critique -> Forge for implementation ->
# objective tests -> Sentinel review if configured -> Memora stores verified result
# ==============================================================================
def test_06_software_engineering_fix_login_test_flow(agent):
    """Scenario 6: Full SWE repair loop (Inference -> Forge -> Pytest -> Sentinel -> Memora)."""
    directive = "FRIDAY, fix the failing login test."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "Inference generated patch plan" in resp.content
    assert "Forge applied implementation" in resp.content
    assert "pytest passed" in resp.content
    assert "Sentinel security gate validated" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "software_engineering"
    result = meta.get("result")
    assert result["status"] == "SUCCESS"
    assert result["plan_and_critique"]["confidence"] >= 0.90
    assert result["test_execution"]["tests_failed"] == 0
    assert result["sentinel_review"]["gate_verdict"] == "ALLOWED"
    assert result["memora_recorded"] is True


# ==============================================================================
# Scenario 7: Security ("FRIDAY, assess my authorized staging server.")
# FRIDAY -> scope confirmation -> Sentinel policy validation -> bounded
# assessment -> evidence-backed result
# ==============================================================================
def test_07_security_assess_staging_server_flow(agent):
    """Scenario 7: Bounded security assessment with scope check and Sentinel policy."""
    directive = "FRIDAY, assess my authorized staging server."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "Security assessment for staging.internal complete" in resp.content
    assert "Scope confirmed" in resp.content
    assert "Sentinel policy validated" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "security_assessment"
    result = meta.get("result")
    assert result["status"] == "SUCCESS"
    assert result["scope_confirmed"] is True
    assert result["policy"]["policy_verdict"] == "ALLOWED"
    assert result["policy"]["non_destructive"] is True
    assert len(result["findings"]) >= 1
    assert len(result["evidence_hash"]) == 64  # SHA256 length


# ==============================================================================
# Scenario 8: Forecasting ("FRIDAY, forecast website traffic for tomorrow.")
# FRIDAY -> Futuris -> calibrated forecast -> uncertainty and assumptions ->
# no automatic production change
# ==============================================================================
def test_08_forecasting_website_traffic_flow(agent):
    """Scenario 8: Futuris probabilistic forecast with non-execution safety invariant."""
    directive = "FRIDAY, forecast website traffic for tomorrow."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "calibrated forecast" in resp.content
    assert "point estimate" in resp.content
    assert "Uncertainty:" in resp.content
    assert "zero automated production changes made" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "forecasting"
    result = meta.get("result")
    assert result["status"] == "SUCCESS"
    assert result["production_changes_applied"] == 0
    assert result["scaling_triggered"] is False
    assert result["forecast"]["prediction_is_not_authorization"] is True


# ==============================================================================
# Scenario 9: Trading ("FRIDAY, check Stratex performance.")
# FRIDAY -> Stratex telemetry -> optional Inference advisory ->
# deterministic Stratex gates -> explanation only
# ==============================================================================
def test_09_trading_check_stratex_performance_flow(agent):
    """Scenario 9: Stratex telemetry & Inference advisory with strict trade freeze invariant."""
    directive = "FRIDAY, check Stratex performance."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "PAPER mode" in resp.content
    assert "LIVE_TRADING_ENABLED=False" in resp.content
    assert "Total equity:" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "trading_performance"
    result = meta.get("result")
    assert result["status"] == "SUCCESS"
    # Verify deterministic risk gates
    assert result["telemetry"]["live_trading_enabled"] is False
    assert result["telemetry"]["trading_mode"] == "PAPER"
    assert result["orders_placed"] == 0
    assert result["parameters_modified"] == 0


# ==============================================================================
# Scenario 10: Cancellation ("FRIDAY, stop the current task.")
# voice interruption -> task cancellation -> peer cancellation where supported ->
# no new side effects -> final cancelled receipt
# ==============================================================================
def test_10_cancellation_stop_current_task_flow(agent):
    """Scenario 10: Voice interruption halts active task, cascades to peers, zero side effects."""
    directive = "FRIDAY, stop the current task."
    resp = agent.process_message(directive)

    assert resp.is_done is True
    assert "Interrupted and stopped current task" in resp.content
    assert "Subsystems halted" in resp.content
    assert "Zero new side effects executed" in resp.content

    meta = resp.metadata
    assert meta.get("workflow") == "cancellation"
    result = meta.get("result")
    assert result["status"] == "CANCELLED"
    assert result["local_task_cancelled"] is True
    assert result["new_side_effects_executed"] == 0
    assert "forge" in result["peer_cancellations"]
    assert "intelx" in result["peer_cancellations"]
    assert "cortex" in result["peer_cancellations"]

    receipt = result["receipt"]
    assert receipt["requested_action"] == "cancel_task"
    assert receipt["result"]["status"] == "CANCELLED"
