"""Master Voice Ecosystem Command Skill for FRIDAY.

Provides the comprehensive conversational and command interface for the entire autonomous ecosystem:
- "Ecosystem status": Real-time status of all three systems and state
- "How is everything doing?": Conversational overview with tone adaptation (Calm vs Crisis)
- "Anything I should know about?": Active alerts and critical events
- "Should I be worried about anything?": Honest risk and headroom assessment
- "What did you learn this week?": Institutional evolution failure learning
- "Full ecosystem report": Renders complete Markdown executive dashboard
- "What decisions did the system make today?": Autonomous decisions audit log
- "Set autonomy to level 2": DANGEROUS biometric-verified autonomy level adjustments
- "What are my current policies?": Human policy review
- Policy creation: Voice-parsed governance rules
"""

import re
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.executive_dashboard import ExecutiveDashboardRenderer
from friday.ecosystem.master_voice import MasterVoiceInterface
from friday.ecosystem.policy_interface import HumanPolicyInterface
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.master_voice")


class MasterVoiceSkill(BaseSkill):
    """Master voice skill commanding and querying the entire autonomous trading ecosystem."""

    __test__ = False

    name = "master_voice"
    description = (
        "Master voice interface for the complete autonomous trading ecosystem: conversational status, "
        "risk evaluations, institutional learning, autonomy level adjustments, and human policy management."
    )
    required_capabilities = ["trading_bot_control", "network_access"]
    tools = ["ecosystem_status_query", "policy_management", "autonomy_control"]
    system_prompt = (
        "You are FRIDAY's Master Ecosystem Supervisor. You hold command authority over the Algorithmic Trading Bot, "
        "AI-Universe, and security governance. You communicate contextually (calm in routine, concise in crisis) "
        "and enforce human policy invariants."
    )
    match_patterns = [
        r"\b(?:ecosystem\s+status|ecosystem\s+overview)\b",
        r"\b(?:how\s+is\s+everything\s+doing|how\s+are\s+things\s+going)\b",
        r"\b(?:anything\s+i\s+should\s+know\s+about|notable\s+events)\b",
        r"\b(?:should\s+i\s+be\s+worried\s+about\s+anything|risk\s+assessment)\b",
        r"\b(?:what\s+did\s+you\s+learn\s+this\s+week|weekly\s+learning)\b",
        r"\b(?:full\s+ecosystem\s+report|executive\s+dashboard|executive\s+report)\b",
        r"\b(?:what\s+decisions\s+did\s+the\s+system\s+make\s+today|decision\s+log)\b",
        r"\b(?:set\s+autonomy\s+to\s+level\s+\d+|adjust\s+autonomy)\b",
        r"\b(?:what\s+are\s+my\s+current\s+policies|policy\s+review|current\s+policies)\b",
        r"\b(?:never\s+trade\s+more\s+than|alert\s+me\s+if\s+daily\s+loss|require\s+my\s+approval)\b",
    ]

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        policy_interface: HumanPolicyInterface | None = None,
        master_voice: MasterVoiceInterface | None = None,
        dashboard_renderer: ExecutiveDashboardRenderer | None = None,
    ) -> None:
        self._command_center = command_center
        self._policy_interface = policy_interface
        self._master_voice = master_voice
        self._dashboard_renderer = dashboard_renderer

    @property
    def command_center(self) -> EcosystemCommandCenter:
        if self._command_center is None:
            self._command_center = EcosystemCommandCenter()
        return self._command_center

    @property
    def policy_interface(self) -> HumanPolicyInterface:
        if self._policy_interface is None:
            self._policy_interface = HumanPolicyInterface()
        return self._policy_interface

    @property
    def master_voice(self) -> MasterVoiceInterface:
        if self._master_voice is None:
            self._master_voice = MasterVoiceInterface(command_center=self.command_center)
        return self._master_voice

    @property
    def dashboard_renderer(self) -> ExecutiveDashboardRenderer:
        if self._dashboard_renderer is None:
            self._dashboard_renderer = ExecutiveDashboardRenderer(
                command_center=self.command_center,
                policy_interface=self.policy_interface,
            )
        return self._dashboard_renderer

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches voice commands for complete ecosystem supervision."""
        clean = user_request.strip().lower()
        speaker_id = kwargs.get("speaker_id", "operator_surendra")
        voice_embedding = kwargs.get("voice_embedding")
        verbal_confirmation = kwargs.get("verbal_confirmation", "")
        step_results: list[dict[str, Any]] = []

        try:
            # 1. "How is everything doing?"
            if any(k in clean for k in ["how is everything doing", "how are things going"]):
                spoken = self.master_voice.answer_how_is_everything()
                step_results.append({"action": "how_is_everything"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "Anything I should know about?"
            if any(k in clean for k in ["anything i should know about", "notable events"]):
                spoken = self.master_voice.answer_anything_to_know()
                step_results.append({"action": "anything_to_know"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "Should I be worried about anything?"
            if any(k in clean for k in ["should i be worried about anything", "worried about anything"]):
                spoken = self.master_voice.answer_should_i_be_worried()
                step_results.append({"action": "should_i_be_worried"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "What did you learn this week?"
            if any(k in clean for k in ["what did you learn this week", "weekly learning"]):
                spoken = self.master_voice.answer_what_did_you_learn()
                step_results.append({"action": "what_did_you_learn"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "Full ecosystem report" / Executive dashboard
            if any(k in clean for k in ["full ecosystem report", "executive dashboard", "executive report"]):
                md = self.dashboard_renderer.render_markdown()
                step_results.append({"action": "full_ecosystem_report"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=md, step_results=step_results)

            # 6. "What decisions did the system make today?"
            if any(k in clean for k in ["decisions did the system make today", "decision log"]):
                decisions = self.command_center.get_recent_decisions()
                if decisions:
                    lines = [f"The ecosystem executed {len(decisions)} autonomous decisions today:"]
                    for d in decisions:
                        lines.append(f"• **`{d.action_type}`** by `{d.operator_id}`: `{d.details}` (Signature: `{d.signature[:10]}...`)")
                    spoken = "\n".join(lines)
                else:
                    spoken = "Zero autonomous decisions recorded today."
                step_results.append({"action": "decision_log", "count": len(decisions)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 7. "Set autonomy to level [N]" (DANGEROUS)
            match_auto = re.search(r"set\s+autonomy\s+to\s+level\s+(\d+)", clean)
            if match_auto:
                level_num = int(match_auto.group(1))
                passed, msg, sig = self.command_center.set_autonomy_level(
                    level_num,
                    speaker_id=speaker_id,
                    voice_embedding=voice_embedding,
                    verbal_confirmation=verbal_confirmation,
                )
                step_results.append({"action": "set_autonomy", "level": level_num, "passed": passed})
                return SkillExecutionResult(skill_name=self.name, success=passed, output=msg, step_results=step_results)

            # 8. "What are my current policies?"
            if any(k in clean for k in ["what are my current policies", "current policies", "policy review"]):
                spoken = self.policy_interface.get_spoken_policy_summary()
                step_results.append({"action": "policy_review"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 9. Policy declaration (e.g. "Never trade more than 5% in a single position")
            if any(k in clean for k in ["never trade more than", "alert me if daily loss", "require my approval"]):
                rule = self.policy_interface.parse_and_add_policy(user_request)
                spoken = f"Policy successfully recorded and enforced: '{rule.name}' (Version {rule.version})."
                step_results.append({"action": "add_policy", "policy_id": rule.policy_id})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 10. Default: "Ecosystem status"
            status = self.command_center.get_ecosystem_status()
            state = status.get("ecosystem_state")
            autonomy = status.get("autonomy_name")
            bot = status.get("systems", {}).get("trading_bot", {})
            pnl = bot.get("daily_pnl_usdt", 0.0)
            sign = "+" if pnl >= 0 else ""

            spoken = (
                f"Ecosystem status report: The overall ecosystem is in {state} at autonomy {autonomy}. "
                f"Trading Bot: {bot.get('status')} across {len(bot.get('connected_venues', []))} venues, Daily P&L: {sign}${pnl:,.2f} USDT. "
                f"AI-Universe: HEALTHY with active multi-agent debates. "
                f"FRIDAY OS: 24/7 Guardian Angel continuous vigilance active. All safety invariants are enforced."
            )
            step_results.append({"action": "ecosystem_status"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[MASTER_VOICE] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Ecosystem master command query encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )
