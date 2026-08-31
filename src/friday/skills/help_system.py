# -*- coding: utf-8 -*-
"""Interactive Help & Capability Discovery Skill for FRIDAY.

Assists the operator with natural language inquiries about available commands:
1. "What can you do?" -> Global capability roster across all 5 subsystems
2. "How do I check trades?" -> Trading Bot domain guide and sample queries
3. "What commands for Nexus?" -> Nexus Growth & Website Engine domain list
4. "What should I ask about my website?" -> Proactive, contextual suggestions
5. Contextual help triggered when user confusion or ambiguous requests are detected
"""

from typing import Any, Dict, List, Optional
import re
import threading

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.help_system")


class HelpSystemSkill(BaseSkill):
    """Interactive help and capability guide across all FRIDAY ecosystem subsystems."""

    __test__ = False

    name = "help_system"
    description = (
        "Provides interactive help, capability discovery, and domain-specific command suggestions across "
        "Trading Bot, Forge SWE Engine, Nexus Website Engine, and AI-Universe."
    )
    required_capabilities = []
    tools = ["get_capabilities", "get_domain_help", "suggest_commands"]
    system_prompt = (
        "You are FRIDAY's Interactive Help Guide. You explain system capabilities and offer structured, "
        "actionable command suggestions to the operator."
    )
    match_patterns = [
        r"\b(?:what\s+can\s+you\s+do|list\s+capabilities|help\s+me|system\s+capabilities)\b",
        r"\b(?:how\s+do\s+i\s+check\s+trades|trading\s+commands|help\s+trading)\b",
        r"\b(?:what\s+commands\s+for\s+nexus|nexus\s+commands|help\s+nexus)\b",
        r"\b(?:what\s+commands\s+for\s+forge|forge\s+commands|help\s+forge)\b",
        r"\b(?:what\s+should\s+i\s+ask\s+about\s+my\s+website|website\s+suggestions)\b",
        r"\b(?:change\s+my\s+preferences|update\s+preferences)\b",
    ]

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def get_capabilities_roster(self) -> Dict[str, Any]:
        """Returns structured capability roster spanning the full FRIDAY Universe and Laptop Control."""
        return {
            "laptop_control": {
                "name": "💻 Autonomous Laptop & Desktop Control",
                "description": "Full Windows control: opening apps, typing, mouse navigation, file management, volume, settings, and command execution.",
                "sample_commands": ["Open Notepad and type hello", "Open Chrome and search for AI", "What are my laptop specs?", "Adjust volume to 50%"],
            },
            "inference": {
                "name": "⚡ Inference Multi-Agent AI Gateway",
                "description": "10 specialist agents (Researcher, Architect, Coder, Critic, Synthesizer, etc.) with multi-model consensus debates.",
                "sample_commands": ["Ask Inference what is 2+2", "Debate with Inference on microservices vs monolith", "How many agents in Inference?"],
            },
            "stratex": {
                "name": "📈 Stratex 24/7 Algorithmic Trading Platform",
                "description": "Binance Futures automated trading, real-time risk mitigation, and panic liquidation halts.",
                "sample_commands": ["Trading status", "How are my positions?", "Emergency stop trading"],
            },
            "intelx": {
                "name": "🧠 IntelX Evidence & Research Engine",
                "description": "Macro research, volatility evidence gathering, and real-time sentiment analysis.",
                "sample_commands": ["IntelX research on BTC volatility", "Summarize latest macro market news"],
            },
            "futuris": {
                "name": "🔮 Futuris Predictive Forecasting Engine",
                "description": "Calibrated probabilistic forecasting, volatility models, and regime transition predictions.",
                "sample_commands": ["Futuris forecast for BTCUSDT", "Show prediction accuracy metrics"],
            },
            "memora": {
                "name": "🧠 Memora Persistent Cloud Memory",
                "description": "9 GB Turso AWS Mumbai long-term memory fabric, vector semantic recall, and episodic storage.",
                "sample_commands": ["Search memory for project notes", "What did we discuss yesterday?"],
            },
            "cortex": {
                "name": "🌐 Cortex Web Operations Engine",
                "description": "Autonomous web operations, visitor analytics, lead tracking, and integrations (Stripe, Twilio, SendGrid).",
                "sample_commands": ["Website status", "Who is on my website?", "Any new leads?"],
            },
            "forge": {
                "name": "🛠️ FORGE Software Engineering Engine",
                "description": "Autonomous full-stack code generator, automated testing, and software package delivery.",
                "sample_commands": ["Forge status", "Ask Forge to build a CLI tool", "Show me what Forge built"],
            },
            "sentinel": {
                "name": "🛡️ Sentinel Cybersecurity & Threat Defense",
                "description": "Autonomous threat detection, capability gating, audit logging, and security verification.",
                "sample_commands": ["Security status", "Run system security audit"],
            },
        }

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes interactive help and command guidance queries."""
        clean = user_request.strip().lower()
        step_results: List[Dict[str, Any]] = []

        try:
            # 1. "What can you do?" / Global capabilities
            if any(k in clean for k in ["what can you do", "list capabilities", "help me", "system capabilities", "what do you do"]):
                roster = self.get_capabilities_roster()
                spoken = (
                    "I am FRIDAY, your Autonomous AI Operating System. Here is what I can do across your laptop and the FRIDAY Universe:\n\n"
                    "💻 **Laptop & Desktop Control**: Open applications, type text, navigate windows, execute commands, and manage files on your PC.\n"
                    "⚡ **Inference AI Gateway (AI-Universe)**: Consult specialist agents for multi-model reasoning and debate.\n"
                    "📈 **Trading Bot (Stratex)**: 24/7 Binance Futures algorithmic trading, portfolio tracking, and instant panic halts.\n"
                    "🛠️ **Forge SWE Engine (FORGE)**: Autonomous full-stack software development, code generation, and test validation.\n"
                    "🌐 **Nexus Growth Engine (Cortex)**: Autonomous website operations, visitor analytics, and conversion intelligence.\n"
                    "🧠 **IntelX & Futuris**: Deep macro research, sentiment scanning, and calibrated market predictions.\n"
                    "🧠 **Memora Memory Fabric**: Persistent cloud memory and semantic recall across all conversations.\n"
                    "🛡️ **Sentinel Cybersecurity**: Autonomous threat defense, security verification, and audit logging.\n\n"
                    "Try saying: *'Open Notepad and type hello'*, *'Ask Inference [question]'*, or *'Status of everything'*."
                )
                step_results.append({"action": "get_capabilities_roster", "roster": roster})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "How do I check trades?" / Trading commands
            if any(k in clean for k in ["how do i check trades", "trading commands", "help trading"]):
                spoken = (
                    "📈 **Trading Bot Commands Guide**:\n"
                    "• *'Trading status'* — Real-time equity, P&L, and open positions.\n"
                    "• *'How are my positions?'* — Detailed breakdown across Binance, Bybit, and OKX.\n"
                    "• *'Emergency stop trading'* — SENSITIVE: Cancels all orders and flattens active positions."
                )
                step_results.append({"action": "help_trading"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "What commands for Nexus?" / Nexus commands
            if any(k in clean for k in ["what commands for nexus", "nexus commands", "help nexus"]):
                spoken = (
                    "🌐 **Nexus Website & Growth Commands Guide**:\n"
                    "• *'Website status'* — Comprehensive health, visitors, and conversion rates.\n"
                    "• *'Who's on my website?'* — Live visitor sessions with behavioral intent scores.\n"
                    "• *'Any new leads?'* — Prospective enterprise leads grouped by sales funnel stage.\n"
                    "• *'Why did Nexus recommend that?'* — Full AI Universe reasoning debate chain.\n"
                    "• *'Approve that Nexus action'* — SENSITIVE: Confirms optimization deployment."
                )
                step_results.append({"action": "help_nexus"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "What commands for Forge?" / Forge commands
            if any(k in clean for k in ["what commands for forge", "forge commands", "help forge"]):
                spoken = (
                    "🛠️ **FORGE Software Engineering Commands Guide**:\n"
                    "• *'Forge status'* — Engine state, active builds, and total packages delivered.\n"
                    "• *'Ask Forge to build [goal]'* — Submits parameterized software task.\n"
                    "• *'Forge, build a CLI tool for [desc]'* — Expands CLI template with argparse and logging.\n"
                    "• *'Show me what Forge built'* — Inspects generated code, test coverage, and zip artifacts.\n"
                    "• *'Cancel the Forge task'* — SENSITIVE: Cancels running build."
                )
                step_results.append({"action": "help_forge"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "What should I ask about my website?"
            if any(k in clean for k in ["what should i ask about my website", "website suggestions"]):
                spoken = (
                    "💡 **Suggested Questions for Nexus Website Intelligence**:\n"
                    "1. *'Who's on my website right now?'* (To see high-intent visitors on pricing/docs)\n"
                    "2. *'What's my conversion rate today?'* (To inspect daily trend and visitor volume)\n"
                    "3. *'Why did conversions drop?'* (To run autonomous root-cause layout diagnosis)\n"
                    "4. *'Show the lead pipeline'* (To see leads in Decision, Evaluation, or Discovery)\n"
                    "5. *'What has Nexus learned?'* (To inspect win rates across growth strategies)"
                )
                step_results.append({"action": "suggest_website_commands"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 6. "Change my preferences"
            if any(k in clean for k in ["change my preferences", "update preferences"]):
                spoken = (
                    "⚙️ To change your preferences, speak your desired mode:\n"
                    "• *'Set response detail to brief'* or *'Set response detail to detailed'*\n"
                    "• *'Set alert delivery to immediate'* or *'Set alert delivery to batched digest'*"
                )
                step_results.append({"action": "preferences_guide"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # Default
            spoken = "I am ready to assist. You can ask for 'Website status', 'Trading status', 'Forge status', or 'Status of everything'."
            step_results.append({"action": "default"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[HELP_SYSTEM] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Help system error: {e}",
                error=str(e),
                step_results=step_results,
            )
