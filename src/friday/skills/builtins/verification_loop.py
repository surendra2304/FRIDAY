"""Verification Loop Built-in Skill for FRIDAY (Adapted from ECC verification-loop)."""

import subprocess
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.verification_loop")


class VerificationLoopSkill(BaseSkill):
    """Executes automated testing, syntax checks, and regression verification."""

    name = "verification_loop"
    description = "Executes automated test suites, validates passing state, and isolates failures."
    required_capabilities = ["shell_exec", "file_read"]
    tools = ["run_tests", "execute_command", "read_file"]
    system_prompt = (
        "You are FRIDAY's Verification Loop Controller. Run test suites, verify that all assertions "
        "pass cleanly, and diagnose any test regressions or failures."
    )
    match_patterns = [
        r"\b(?:run|execute|check)\s+(?:the\s+)?(?:tests?|verification|pytest|suite)\b",
        r"\bverify\s+(?:the\s+)?(?:code|changes|build|system)\b",
        r"\bverification\s+loop\b",
    ]

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        step_results: list[dict[str, Any]] = []

        # Execute pytest through tool_registry or subprocess fallback
        run_tests_tool = tool_registry.get("run_tests") if tool_registry else None
        if run_tests_tool:
            try:
                res = run_tests_tool.execute()
                output = res.content if hasattr(res, "content") else str(res)
                success = res.success if hasattr(res, "success") else True
                step_results.append({"tool": "run_tests", "output": output[:300]})
            except Exception as err:
                output = str(err)
                success = False
                step_results.append({"tool": "run_tests", "error": output})
        else:
            try:
                proc = subprocess.run(
                    ["pytest", "-q", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = (proc.stdout + "\n" + proc.stderr).strip()
                success = proc.returncode == 0
                step_results.append({"command": "pytest", "returncode": proc.returncode, "output": output[:300]})
            except Exception as err:
                output = f"Verification execution error: {err}"
                success = False
                step_results.append({"error": str(err)})

        summary = (
            "✅ Verification Loop PASSED: All tests succeeded."
            if success
            else f"❌ Verification Loop FAILED: Tests did not pass cleanly.\n\nOutput Summary:\n{output[:500]}"
        )

        return SkillExecutionResult(
            skill_name=self.name,
            success=success,
            output=summary,
            step_results=step_results,
            error=None if success else "Test failures encountered during verification.",
        )
