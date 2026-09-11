"""AgentShield Built-in Security Skill for FRIDAY (Adapted from ECC AgentShield)."""

from typing import Any

from friday.core.logging import get_logger
from friday.security.agent_shield import AgentShield
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.agent_shield")


class AgentShieldSkill(BaseSkill):
    """Executes automated security scanning for secrets, prompt injections, and permission hazards."""

    name = "agent_shield"
    description = "Scans codebase, configuration, tools, and prompts for security vulnerabilities using AgentShield."
    required_capabilities = ["file_read"]
    tools = ["read_file", "list_files", "synthesize_information"]
    system_prompt = (
        "You are FRIDAY's AgentShield Security Officer. Audit system security posture, detect prompt "
        "injection surfaces, locate secret exposures, and recommend immediate mitigations."
    )
    match_patterns = [
        r"\b(?:run\s+)?(?:agent\s*shield|security\s+scan|security\s+audit)\b",
        r"\bscan\s+(?:for\s+)?(?:vulnerabilities|secrets|security\s+issues|threats)\b",
        r"\baudit\s+(?:system\s+)?security\b",
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
        shield = AgentShield()

        # 1. Audit tools if tool_registry provided
        tool_findings = []
        if tool_registry and hasattr(tool_registry, "list_tools"):
            for t in tool_registry.list_tools():
                tool_name = getattr(t, "name", str(t))
                t_findings = shield.scan_tool(tool_name, t)
                tool_findings.extend(t_findings)

        # 2. Audit directory
        target_dir = kwargs.get("target_dir", ".")
        report = shield.audit_directory(directory_path=target_dir, max_files=150)
        report.findings.extend(tool_findings)

        step_results.append({
            "step": "agentshield_scan",
            "grade": report.grade,
            "total_findings": len(report.findings),
            "critical": report.critical_count,
            "high": report.high_count,
        })

        summary = report.format_summary()

        return SkillExecutionResult(
            skill_name=self.name,
            success=report.critical_count == 0,
            output=summary,
            step_results=step_results,
            metadata=report.to_dict(),
        )
