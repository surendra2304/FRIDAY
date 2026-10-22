"""Skill Registry for registering, discovering, and dispatching FRIDAY skills."""

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill

logger = get_logger("skills.registry")


class SkillRegistry:
    """Central registry for managing installable, reusable FRIDAY skills."""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a new skill instance."""
        if not isinstance(skill, BaseSkill):
            raise TypeError(f"Expected BaseSkill instance, got {type(skill).__name__}")
        self._skills[skill.name] = skill
        logger.info(f"Registered skill '{skill.name}' with required capabilities {skill.required_capabilities}")

    def unregister(self, skill_name: str) -> bool:
        """Remove a skill from the registry."""
        if skill_name in self._skills:
            del self._skills[skill_name]
            logger.info(f"Unregistered skill '{skill_name}'")
            return True
        return False

    def get(self, skill_name: str) -> BaseSkill | None:
        """Retrieve a registered skill by name."""
        return self._skills.get(skill_name)

    def list_skills(self) -> list[BaseSkill]:
        """Return a list of all registered skills."""
        return list(self._skills.values())

    def find_matching_skill(self, user_request: str, threshold: float = 0.80) -> tuple[BaseSkill, float] | None:
        """Find the best matching skill for a user request above confidence threshold."""
        best_skill: BaseSkill | None = None
        best_score = 0.0

        for skill in self._skills.values():
            score = skill.match_score(user_request)
            if score > best_score and score >= threshold:
                best_score = score
                best_skill = skill

        if best_skill:
            return best_skill, best_score
        return None

    def load_builtins(self) -> None:
        """Automatically import and register all default built-in skills."""
        from friday.skills.ab_test_monitor import ABTestMonitorSkill
        from friday.skills.advisory_supervisor import AdvisorySupervisorSkill
        from friday.skills.builtins.file_search_and_read import FileSearchAndReadSkill
        from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill
        from friday.skills.builtins.system_health_audit import SystemHealthAuditSkill
        from friday.skills.conversational_ecosystem import ConversationalEcosystemQuery
        from friday.skills.ecosystem_status import EcosystemStatusSkill
        from friday.skills.evolution_approval import EvolutionApprovalSkill
        from friday.skills.forge_manager import ForgeManagerSkill
        from friday.skills.futuris_manager import FuturisManagerSkill
        from friday.skills.help_system import HelpSystemSkill
        from friday.skills.intelligence_briefing import IntelligenceBriefingSkill
        from friday.skills.intelx_manager import IntelXManagerSkill
        from friday.skills.master_voice_skill import MasterVoiceSkill
        from friday.skills.nexus_manager import NexusManagerSkill
        from friday.skills.nexus_operator import NexusOperatorSkill
        from friday.skills.production_supervisor import ProductionSupervisorSkill
        from friday.skills.sentinel_manager import SentinelManagerSkill
        from friday.skills.testnet_advisory_monitor import TestnetAdvisoryMonitorSkill
        from friday.skills.trading_bot_operator import TradingBotOperator
        from friday.skills.voice_ecosystem import VoiceEcosystemSkill
        from friday.skills.voice_live_trading import VoiceLiveTradingSkill
        from friday.skills.voice_multi_exchange import VoiceMultiExchangeSkill
        from friday.skills.voice_trading import VoiceTradingSkill

        builtins = [
            NetworkDiagnosticSkill(),
            SystemHealthAuditSkill(),
            FileSearchAndReadSkill(),
            TradingBotOperator(),
            AdvisorySupervisorSkill(),
            ABTestMonitorSkill(),
            TestnetAdvisoryMonitorSkill(),
            ProductionSupervisorSkill(),
            VoiceTradingSkill(),
            VoiceLiveTradingSkill(),
            VoiceMultiExchangeSkill(),
            EvolutionApprovalSkill(),
            IntelligenceBriefingSkill(),
            MasterVoiceSkill(),
            ForgeManagerSkill(),
            VoiceEcosystemSkill(),
            EcosystemStatusSkill(),
            NexusOperatorSkill(),
            NexusManagerSkill(),
            ConversationalEcosystemQuery(),
            HelpSystemSkill(),
            SentinelManagerSkill(),
            IntelXManagerSkill(),
            FuturisManagerSkill(),
        ]
        for s in builtins:
            if s.name not in self._skills:
                self.register(s)


# Process-level default skill registry
skill_registry = SkillRegistry()
skill_registry.load_builtins()
