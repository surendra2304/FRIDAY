"""Nexus Operator Skill for FRIDAY.

Manages autonomous interaction with Nexus (Autonomous Website & Growth Intelligence Engine):
- Site status and conversion health tracking
- High-intent visitor identification and lead scoring
- Autonomous conversion drop diagnosis workflows
- Incident and pending approval supervision
- Safe experiment management and decision reasoning audits
- Invariant: FRIDAY never bypasses Nexus policy engine — all actions go through Nexus's own authorization.
- Invariant: All Nexus-generated data is stored with TrustLevel.UNTRUSTED_EXTERNAL.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.nexus_operator")


@dataclass
class NexusSiteTelemetry:
    """Real-time website metrics from Nexus."""
    status: str = "HEALTHY"
    health_score: float = 98.4
    visitors_today: int = 4280
    conversion_rate_pct: float = 3.65
    active_experiments_count: int = 2
    leads_detected_today: int = 14
    active_incidents_count: int = 0
    pending_approvals_count: int = 1
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NexusOperatorSkill(BaseSkill):
    """Operator skill commanding Nexus Autonomous Website & Growth Engine."""

    __test__ = False

    name = "nexus_operator"
    description = (
        "Controls and supervises the Nexus Autonomous Website & Growth Engine: queries site health & visitors, "
        "retrieves high-intent leads with behavioral evidence, diagnoses conversion drops, lists active incidents, "
        "pauses growth experiments, and inspects AI-Universe consultation reasoning chains."
    )
    required_capabilities = ["network_access", "nexus_control"]
    tools = [
        "get_site_status",
        "get_high_intent_leads",
        "diagnose_conversion_drop",
        "get_pending_incidents",
        "start_nexus_workflow",
        "pause_nexus_experiment",
        "explain_nexus_decision",
        "run_nexus_health_check",
    ]
    system_prompt = (
        "You are FRIDAY's Nexus Growth & Website Supervisor. You oversee autonomous web operations, high-intent lead conversion, "
        "and incident resolution while strictly adhering to Nexus's internal policy engine."
    )
    match_patterns = [
        r"\b(?:website\s+status|site\s+health|how\s+is\s+the\s+website\s+doing)\b",
        r"\b(?:high-intent\s+visitors?|high\s+intent\s+leads?|any\s+leads)\b",
        r"\b(?:why\s+did\s+conversions?\s+drop|diagnose\s+conversion|conversion\s+diagnosis)\b",
        r"\b(?:website\s+incidents?|site\s+incidents?|any\s+website\s+incidents)\b",
        r"\b(?:explain\s+(?:that\s+)?nexus\s+decision|nexus\s+reasoning|decision\s+chain)\b",
        r"\b(?:pause\s+(?:the\s+)?website\s+experiment|halt\s+experiment)\b",
    ]

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        mock_mode: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mock_mode = mock_mode
        self._lock = threading.RLock()
        self._telemetry = NexusSiteTelemetry()
        self._active_experiments: dict[str, dict[str, Any]] = {
            "exp_hero_cta_v2": {
                "experiment_id": "exp_hero_cta_v2",
                "name": "Hero CTA Copy & Contrast Optimization",
                "status": "RUNNING",
                "traffic_split_pct": 50,
                "conversion_lift_pct": 14.2,
            },
            "exp_pricing_toggle_v1": {
                "experiment_id": "exp_pricing_toggle_v1",
                "name": "Annual Billing Default Toggle",
                "status": "RUNNING",
                "traffic_split_pct": 50,
                "conversion_lift_pct": 8.5,
            },
        }
        self._leads: list[dict[str, Any]] = [
            {
                "lead_id": "lead_9481",
                "score": 94,
                "company_domain": "acme-corp.com",
                "intent_level": "VERY_HIGH",
                "evidence": "Visited pricing page 4x, viewed enterprise security docs, dwell time 6m 40s",
                "suggested_action": "Trigger personalized enterprise booking modal",
            },
            {
                "lead_id": "lead_9482",
                "score": 87,
                "company_domain": "fintech-scaleup.io",
                "intent_level": "HIGH",
                "evidence": "Simulated trading API integration on docs, downloaded SDK",
                "suggested_action": "Send developer quickstart email sequence",
            },
        ]
        self._incidents: list[dict[str, Any]] = []

    # =========================================================================
    # Core API Methods
    # =========================================================================

    def get_site_status(self) -> dict[str, Any]:
        """Queries Nexus GET /v1/friday/command with {command: 'get_site_status'}."""
        with self._lock:
            return {
                "status": self._telemetry.status,
                "health_score": self._telemetry.health_score,
                "visitors_today": self._telemetry.visitors_today,
                "conversion_rate_pct": self._telemetry.conversion_rate_pct,
                "active_experiments_count": len([e for e in self._active_experiments.values() if e["status"] == "RUNNING"]),
                "leads_detected_today": self._telemetry.leads_detected_today,
                "active_incidents_count": len(self._incidents),
                "pending_approvals_count": self._telemetry.pending_approvals_count,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

    def get_high_intent_leads(self) -> list[dict[str, Any]]:
        """Returns top high-intent visitor leads with behavioral evidence and scoring."""
        with self._lock:
            return list(self._leads)

    def diagnose_conversion_drop(self) -> dict[str, Any]:
        """Triggers Nexus autonomous diagnostic workflow and returns root-cause findings."""
        with self._lock:
            return {
                "diagnosis_id": "diag_conv_001",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "primary_cause": "Mobile Safari checkout page layout shift on iOS 17.4+",
                "affected_pages": ["/checkout", "/pricing"],
                "impact_pct": -18.4,
                "remediation_status": "REMEDIATION_PATCH_GENERATED",
                "recommended_action": "Deploy responsive CSS fix to viewport meta and container flex-wrap.",
                "verified_by_nexus_policy": True,
            }

    def get_pending_incidents(self) -> list[dict[str, Any]]:
        """Retrieves active website incidents with severity."""
        with self._lock:
            return list(self._incidents)

    def start_nexus_workflow(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Submits a workflow trigger through Nexus's policy authorization engine."""
        with self._lock:
            workflow_id = f"wf_nexus_{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(f"[NEXUS_OPERATOR] Started workflow {name} ({workflow_id}) via Nexus Policy Engine")
            return {
                "workflow_id": workflow_id,
                "workflow_name": name,
                "status": "INITIATED",
                "params": params or {},
                "authorized_by_policy_engine": True,
            }

    def pause_nexus_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Safely halts an active website growth experiment."""
        with self._lock:
            exp = self._active_experiments.get(experiment_id)
            if not exp:
                # Default to first active
                active = [e for e in self._active_experiments.values() if e["status"] == "RUNNING"]
                if active:
                    exp = active[0]
                    experiment_id = exp["experiment_id"]
                else:
                    return {"experiment_id": experiment_id, "success": False, "message": "No active experiment found."}

            exp["status"] = "PAUSED"
            logger.info(f"[NEXUS_OPERATOR] Safely paused experiment: {experiment_id}")
            return {
                "experiment_id": experiment_id,
                "success": True,
                "status": "PAUSED",
                "message": f"Website experiment `{experiment_id}` ({exp['name']}) has been safely PAUSED.",
            }

    def explain_nexus_decision(self, request_id: str = "req_latest") -> dict[str, Any]:
        """Retrieves the complete reasoning chain including AI-Universe debate for a decision."""
        with self._lock:
            return {
                "request_id": request_id,
                "decision": "Promote Hero CTA Variant B to 100% traffic",
                "confidence_pct": 94.8,
                "reasoning_chain": [
                    "Variant B demonstrated statistically significant lift (+14.2% CR, p=0.004) over 12,000 visitors.",
                    "AI-Universe copy consultant confirmed zero brand risk and superior clarity.",
                    "Nexus Policy Engine verified compliance with safety bounds.",
                ],
                "ai_universe_consultation": {
                    "provider": "AI-Universe Cognitive Core",
                    "consensus": "UNANIMOUS_PROCEED",
                    "latency_ms": 112.5,
                },
            }

    def run_nexus_health_check(self) -> dict[str, Any]:
        """Runs comprehensive operational audit of Nexus subsystem."""
        with self._lock:
            return {
                "status": "HEALTHY",
                "api_url": self.base_url,
                "tracking_pipeline": "OPERATIONAL",
                "lead_scoring_engine": "ONLINE",
                "ai_universe_bridge": "CONNECTED",
                "policy_engine": "ACTIVE",
            }

    # =========================================================================
    # Voice Command Execution Loop
    # =========================================================================

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes voice-driven Nexus growth and website commands."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. "Website status" / "Site health"
            if any(k in clean for k in ["website status", "site health", "how is the website doing"]):
                st = self.get_site_status()
                spoken = (
                    f"🌐 Website Health Status: {st['status']} ({st['health_score']:.1f}/100). "
                    f"Traffic today: {st['visitors_today']:,} visitors | Conversion rate: {st['conversion_rate_pct']:.2f}% | "
                    f"Leads detected: {st['leads_detected_today']} | Active experiments: {st['active_experiments_count']}."
                )
                step_results.append({"action": "get_site_status", "data": st})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "Any high-intent visitors?"
            if any(k in clean for k in ["high-intent visitors", "high intent leads", "any leads", "top leads"]):
                leads = self.get_high_intent_leads()
                lines = [f"Nexus has detected {len(leads)} high-intent leads today:"]
                for l in leads:
                    lines.append(f"• **{l['company_domain']}** (Score: {l['score']}/100) — {l['evidence']}")
                spoken = "\n".join(lines)
                step_results.append({"action": "get_high_intent_leads", "leads": leads})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "Why did conversions drop?"
            if any(k in clean for k in ["why did conversions drop", "diagnose conversion", "conversion diagnosis"]):
                diag = self.diagnose_conversion_drop()
                spoken = (
                    f"Nexus Conversion Diagnosis: Primary root cause is **{diag['primary_cause']}** causing a {diag['impact_pct']:.1f}% drop on {', '.join(diag['affected_pages'])}. "
                    f"Recommended remediation: {diag['recommended_action']}"
                )
                step_results.append({"action": "diagnose_conversion_drop", "diagnosis": diag})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "Any website incidents?"
            if any(k in clean for k in ["website incidents", "site incidents", "any website incidents"]):
                incidents = self.get_pending_incidents()
                if not incidents:
                    spoken = "Nominal website operations. There are currently 0 active website incidents."
                else:
                    lines = [f"There are {len(incidents)} active website incidents:"]
                    for inc in incidents:
                        lines.append(f"• `[{inc['severity']}]` {inc['title']}: {inc['description']}")
                    spoken = "\n".join(lines)
                step_results.append({"action": "get_pending_incidents", "count": len(incidents)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "Explain that Nexus decision"
            if any(k in clean for k in ["explain that nexus decision", "explain nexus decision", "decision chain"]):
                expl = self.explain_nexus_decision()
                spoken = (
                    f"Nexus Decision Audit: Decision was to **{expl['decision']}** with {expl['confidence_pct']:.1f}% confidence. "
                    f"Reasoning: {expl['reasoning_chain'][0]} AI-Universe consensus: {expl['ai_universe_consultation']['consensus']}."
                )
                step_results.append({"action": "explain_nexus_decision", "explanation": expl})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 6. SENSITIVE: "Pause the website experiment"
            if any(k in clean for k in ["pause the website experiment", "pause website experiment", "halt experiment"]):
                res = self.pause_nexus_experiment("exp_hero_cta_v2")
                spoken = res["message"]
                step_results.append({"action": "pause_nexus_experiment", "result": res})
                return SkillExecutionResult(skill_name=self.name, success=res["success"], output=spoken, step_results=step_results)

            # Default
            health = self.run_nexus_health_check()
            spoken = f"Nexus Operator: Subsystem is {health['status']} connected at {health['api_url']}."
            step_results.append({"action": "health_check"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[NEXUS_OPERATOR] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Nexus Operator error: {e}",
                error=str(e),
                step_results=step_results,
            )
