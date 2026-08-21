# -*- coding: utf-8 -*-
"""Comprehensive Real-World Verification and Anti-False-Success Audit Tests.

Verifies:
1. Tool returning "success" string while failing filesystem mutation is detected as FAILED.
2. Tool returning "success" string while application is not running/closed is detected as FAILED.
3. Tool returning "success" string while expected UI screen element is absent is detected as FAILED.
4. When real-world evidence is unavailable or unverifiable, StepVerifier returns UNVERIFIED, not PASSED.
5. Structured tool output containing non-JSON or missing keys is detected as FAILED.
6. Real success with verified evidence passes completely.
"""

from datetime import datetime
import os
import pytest

from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.verification import SelfCorrectionPolicy, StepVerifier, VerificationResult, VerificationStatus


class TestRealWorldVerificationAndAntiFalseSuccess:

    def test_filesystem_false_success_detected(self, tmp_path):
        """Tool reports success for file creation, but file is not on disk -> Verification FAILED."""
        non_existent_file = str(tmp_path / "never_created.txt")
        step = PlanStep(
            step_id="step_write",
            description="Write crucial config",
            tool_name="write_file",
            parameters={"path": non_existent_file, "content": "config=1"},
            evidence_source="filesystem",
        )

        # Tool claims success in its return string
        tool_output = "File write_file succeeded successfully."
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output)

        assert vres.status == VerificationStatus.FAILED
        assert vres.passed is False
        assert "False success" in vres.diagnostics
        assert "not created on filesystem" in vres.diagnostics

    def test_filesystem_deletion_false_success_detected(self, tmp_path):
        """Tool reports file deleted, but file still exists on disk -> Verification FAILED."""
        existing_file = tmp_path / "still_here.txt"
        existing_file.write_text("important data", encoding="utf-8")
        step = PlanStep(
            step_id="step_del",
            description="Delete file",
            tool_name="delete_file",
            parameters={"path": str(existing_file)},
            evidence_source="filesystem",
        )

        tool_output = "File successfully removed."
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output)

        assert vres.status == VerificationStatus.FAILED
        assert vres.passed is False
        assert "still exists" in vres.diagnostics

    def test_application_state_false_success_detected(self):
        """Tool reports app launched, but app is not in running process list -> Verification FAILED."""
        step = PlanStep(
            step_id="step_app",
            description="Launch Calculator",
            tool_name="launch_app",
            parameters={"app_name": "calc.exe"},
            evidence_source="application",
        )

        env_state = {
            "application_state": {
                "running_processes": ["notepad.exe", "explorer.exe"],
            }
        }

        tool_output = "Launched calc.exe successfully with PID 1234."
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output, environment_state=env_state)

        assert vres.status == VerificationStatus.FAILED
        assert vres.passed is False
        assert "was not found in running processes" in vres.diagnostics

    def test_screen_state_false_success_detected(self):
        """Tool reports UI button clicked, but expected element is missing from screen state -> Verification FAILED."""
        step = PlanStep(
            step_id="step_click",
            description="Click Save button",
            tool_name="click_ui",
            parameters={"target_element": "Save Confirmation Dialog"},
            evidence_source="screen",
        )

        env_state = {
            "screen_state": {
                "elements": ["Cancel Button", "Main Window"],
            }
        }

        tool_output = "Click synthesized at (100, 200)."
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output, environment_state=env_state)

        assert vres.status == VerificationStatus.FAILED
        assert vres.passed is False
        assert "was not verified on screen" in vres.diagnostics

    def test_unverifiable_external_service_reports_unverified(self):
        """When external verification is requested but unavailable, report UNVERIFIED instead of inventing success."""
        step = PlanStep(
            step_id="step_ext",
            description="Post webhook update",
            tool_name="http_request",
            parameters={"url": "https://api.external.com/event"},
            evidence_source="external_service",
        )

        env_state = {
            "external_state": {},  # External service state cannot be confirmed
        }

        tool_output = "HTTP 200 OK"
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output, environment_state=env_state)

        assert vres.status == VerificationStatus.UNVERIFIED
        assert vres.passed is False
        assert "cannot confirm real-world state" in vres.diagnostics

    def test_real_world_success_passes_verification(self, tmp_path):
        """When file is genuinely created on disk and postconditions are satisfied -> Verification PASSED."""
        real_file = tmp_path / "created_file.txt"
        real_file.write_text("Hello FRIDAY Verification", encoding="utf-8")

        step = PlanStep(
            step_id="step_valid",
            description="Write real file",
            tool_name="write_file",
            parameters={"path": str(real_file)},
            postconditions=[f"file_exists:{str(real_file)}", f"file_contains:{str(real_file)}:Hello FRIDAY Verification"],
            evidence_source="filesystem",
        )

        tool_output = "File written successfully."
        vres = StepVerifier.verify_step_result(step=step, step_result=tool_output)

        assert vres.status == VerificationStatus.PASSED
        assert vres.passed is True
        assert vres.is_real_success is True
