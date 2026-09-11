"""Instinct Management Built-in Skill for FRIDAY (Adapted from ECC Continuous Learning v2)."""

from typing import Any

from friday.core.logging import get_logger
from friday.learning.instinct_engine import InstinctEngine
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.instinct_management")


class InstinctManagementSkill(BaseSkill):
    """Inspects, exports, imports, and manages continuous learning behavioral instincts."""

    name = "instinct_management"
    description = "Manages learned instincts: list, inspect confidence, export, and import behavioral knowledge."
    required_capabilities = ["file_read"]
    tools = ["read_file", "synthesize_information"]
    system_prompt = (
        "You are FRIDAY's Instinct Management Specialist. Present learned behaviors, track confidence "
        "scores across domains, and assist with knowledge import and export."
    )
    match_patterns = [
        r"\b(?:list|show|view|check)\s+(?:learned\s+)?instincts\b",
        r"\bcontinuous\s+learning\s+status\b",
        r"\b(?:export|import)\s+instincts\b",
        r"\bwhat\s+have\s+you\s+learned\b",
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
        engine = kwargs.get("instinct_engine") or InstinctEngine()
        clean_req = user_request.lower()

        step_results: list[dict[str, Any]] = []

        if "export" in clean_req:
            export_file = "data/instincts_export.json"
            success = engine.export_to_json(export_file)
            msg = f"✅ Exported {len(engine.list_instincts())} instincts to `{export_file}`." if success else "❌ Failed to export instincts."
            return SkillExecutionResult(
                skill_name=self.name,
                success=success,
                output=msg,
                step_results=[{"action": "export", "success": success}],
            )

        # Default: list instincts
        instincts = engine.list_instincts()
        step_results.append({"action": "list", "count": len(instincts)})

        if not instincts:
            output = (
                "🧠 Continuous Learning Instinct Engine:\n"
                "No instincts recorded yet. As tasks, corrections, and verifications occur, "
                "FRIDAY automatically synthesizes atomic instincts."
            )
        else:
            lines = [
                f"🧠 Continuous Learning Instinct Engine ({len(instincts)} Active Instincts):",
                "==================================================",
            ]
            for idx, inst in enumerate(instincts, 1):
                lines.append(
                    f"{idx}. [{inst.domain.upper()}] When {inst.trigger}\n"
                    f"   → Action: {inst.action}\n"
                    f"   → Confidence: {inst.confidence} | Scope: {inst.scope} | Evidence items: {len(inst.evidence)}"
                )
            output = "\n".join(lines)

        return SkillExecutionResult(
            skill_name=self.name,
            success=True,
            output=output,
            step_results=step_results,
            metadata={"count": len(instincts)},
        )
