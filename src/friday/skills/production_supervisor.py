"""Production Supervisor Skill for FRIDAY.

Integrates voice and text commands for production operations:
- "System status" -> Overall system health check & dashboard
- "Trading performance" -> Current trading metrics
- "AI advisory status" -> AI recommendation health & recent activity
- "Emergency halt" -> Authoritative kill-switch activation
- "Rollback parameters" -> Revert AI parameter overlays to baseline safe defaults
- "Show alerts" -> Display active alerts
- "Acknowledge alert [ID]" -> Acknowledge specific alert
"""

import re
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.production_supervisor")


class ProductionSupervisorSkill(BaseSkill):
    """Production supervision skill handling high-level ops commands and emergency interventions."""

    __test__ = False

    name = "production_supervisor"
    description = (
        "Provides production supervision commands: system health checks, trading performance, "
        "AI advisory status, alert management, and emergency procedures (halt, rollback)."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Production Operations Supervisor. You provide unified multi-system "
        "health status, trading metrics, alert acknowledgment, and execute authoritative emergency response protocols."
    )
    match_patterns = [
        r"\b(?:system\s+status|overall\s+status|production\s+dashboard|production\s+health)\b",
        r"\b(?:trading\s+performance|current\s+trading\s+metrics|portfolio\s+performance)\b",
        r"\b(?:ai\s+advisory\s+status|advisory\s+health)\b",
        r"\b(?:emergency\s+halt|emergency\s+stop|halt\s+trading|panic\s+halt)\b",
        r"\b(?:rollback\s+parameters|revert\s+parameters|parameter\s+rollback)\b",
        r"\b(?:show\s+alerts|list\s+alerts|active\s+alerts|current\s+alerts)\b",
        r"\b(?:acknowledge\s+alert\s+([a-zA-Z0-9_\-]+))\b",
    ]

    def __init__(
        self,
        bot_operator: Any | None = None,
        alert_manager: Any | None = None,
        emergency_manager: Any | None = None,
        dashboard: Any | None = None,
    ) -> None:
        self._bot_operator = bot_operator
        self._alert_manager = alert_manager
        self._emergency_manager = emergency_manager
        self._dashboard = dashboard

    @property
    def bot_operator(self) -> Any:
        if self._bot_operator is None:
            from friday.skills.trading_bot_operator import TradingBotOperator
            self._bot_operator = TradingBotOperator()
        return self._bot_operator

    @property
    def alert_manager(self) -> Any:
        if self._alert_manager is None:
            from friday.alert_manager import ProductionAlertManager
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    @property
    def emergency_manager(self) -> Any:
        if self._emergency_manager is None:
            from friday.emergency_procedures import EmergencyProcedureManager
            self._emergency_manager = EmergencyProcedureManager(
                bot_operator=self.bot_operator, alert_manager=self.alert_manager
            )
        return self._emergency_manager

    @property
    def dashboard(self) -> Any:
        if self._dashboard is None:
            from friday.production_dashboard import ProductionDashboard
            self._dashboard = ProductionDashboard(
                bot_operator=self.bot_operator,
                alert_manager=self.alert_manager,
                emergency_manager=self.emergency_manager,
            )
        return self._dashboard

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches natural language production operations commands."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. Emergency Halt
            if any(k in clean_req for k in ["emergency halt", "emergency stop", "halt trading", "panic halt"]):
                res = self.emergency_manager.trading_halt(
                    reason="Voice/Text Command: Emergency Halt",
                    authorizer=authorizer,
                )
                step_results.append({"action": "emergency_halt", "success": res["success"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=res["success"],
                    output=res["message"],
                    step_results=step_results,
                    metadata=res,
                )

            # 2. Rollback Parameters
            if any(k in clean_req for k in ["rollback parameters", "revert parameters", "parameter rollback"]):
                res = self.emergency_manager.parameter_rollback(
                    reason="Voice/Text Command: Parameter Rollback",
                    authorizer=authorizer,
                )
                step_results.append({"action": "parameter_rollback", "success": res["success"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=res["success"],
                    output=res["message"],
                    step_results=step_results,
                    metadata=res,
                )

            # 3. Acknowledge Alert [ID]
            match_ack = re.search(r"\backnowledge\s+alert\s+([a-zA-Z0-9_\-]+)\b", clean_req)
            if match_ack:
                alert_id = match_ack.group(1)
                ok = self.alert_manager.acknowledge_alert(alert_id)
                msg = f"Alert `{alert_id}` has been successfully acknowledged." if ok else f"Alert `{alert_id}` could not be found."
                step_results.append({"action": "acknowledge_alert", "alert_id": alert_id, "success": ok})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=ok,
                    output=msg,
                    step_results=step_results,
                )

            # 4. Show Alerts
            if any(k in clean_req for k in ["show alerts", "list alerts", "active alerts", "current alerts"]):
                out = self.dashboard.render_alerts_summary()
                step_results.append({"action": "show_alerts", "alerts_count": len(self.alert_manager.get_active_alerts())})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=out,
                    step_results=step_results,
                )

            # 5. Trading Performance
            if any(k in clean_req for k in ["trading performance", "current trading metrics", "portfolio performance"]):
                out = self.dashboard.render_trading_performance_summary()
                step_results.append({"action": "trading_performance"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=out,
                    step_results=step_results,
                )

            # 6. AI Advisory Status
            if any(k in clean_req for k in ["ai advisory status", "advisory health"]):
                out = self.dashboard.render_ai_advisory_status()
                step_results.append({"action": "ai_advisory_status"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=out,
                    step_results=step_results,
                )

            # 7. Default: System Status / Production Dashboard
            out = self.dashboard.render_markdown_dashboard()
            step_results.append({"action": "system_status"})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=out,
                step_results=step_results,
            )

        except Exception as e:
            logger.error(f"[PROD_SUPERVISOR] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Production supervisor encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )
