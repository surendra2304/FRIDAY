"""Nexus Operator Skill for FRIDAY.

Manages interaction with Nexus (Autonomous Website & Growth Intelligence Engine):
- Site status and conversion health tracking
- High-intent visitor identification and lead scoring
- Autonomous conversion drop diagnosis workflows
- Incident and pending approval supervision
- Safe experiment management and decision reasoning audits
- Invariant: FRIDAY never bypasses Nexus policy engine — all actions go through Nexus's own authorization.
- Invariant: All Nexus-generated data is stored with TrustLevel.UNTRUSTED_EXTERNAL.

Honesty contract
----------------
Every ``Queries Nexus GET /v1/friday/command`` docstring in this file used to
describe a request that was never made: the methods returned a hardcoded
telemetry object (a **98.4/100** site health, 4,280 visitors, a 3.65% conversion
rate, two running experiments, a 94.8%-confidence decision audit with a
"UNANIMOUS_PROCEED" AI-Universe consultation) and a health check that reported
``HEALTHY``/``OPERATIONAL``/``ONLINE``/``CONNECTED``/``ACTIVE`` without touching
the network. The registry builds this skill by default, so those literals were
one voice command away from being spoken as live website telemetry.

Now: ``mock_mode=False`` (the default) speaks HTTP to ``{base_url}/v1/friday/command``
and reports the endpoint's own answer, or ``UNREACHABLE`` with the error.
``mock_mode=True`` serves the sample payloads, each tagged ``sample_data: True``,
and exists for tests and demos that ask for it by name.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.readings import UNKNOWN_LABEL, format_number
from friday.integrations.nexus_client import NexusCommandClient
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.nexus_operator")


@dataclass
class NexusSiteTelemetry:
    """Sample website metrics, served only in ``mock_mode``."""

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
        "Commands the Nexus Website & Growth Engine: site health, high-intent leads, "
        "conversion diagnosis, incident supervision, experiment control and decision audits."
    )
    required_capabilities = ["network_access"]
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
        mock_mode: bool = False,
        timeout_sec: float = 4.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mock_mode = bool(mock_mode)
        self.timeout_sec = timeout_sec
        self._lock = threading.RLock()
        # One transport for both Nexus skills (see integrations/nexus_client.py):
        # this class used to claim it queried Nexus and never opened a socket.
        self._client = NexusCommandClient(base_url=self.base_url, timeout_sec=timeout_sec)
        self._last_result: dict[str, Any] = {"ok": None, "sample_data": self.mock_mode}
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
    # Transport
    # =========================================================================

    @property
    def command_url(self) -> str:
        """The endpoint every live command goes to."""
        return self._client.command_url

    def _nexus_command(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Issues one command through the shared client. Never raises."""
        if self.mock_mode:
            result = {
                "ok": True,
                "command": command,
                "url": self._client.command_url,
                "http_status": None,
                "error": None,
                "payload": {},
                "sample_data": True,
            }
            with self._lock:
                self._last_result = result
            return result

        result = dict(self._client.command(command, payload))
        result["sample_data"] = False
        with self._lock:
            self._last_result = result
        return result

    def last_result(self) -> dict[str, Any]:
        """The outcome of the most recent command (success, error, endpoint)."""
        with self._lock:
            return dict(self._last_result)

    def _unavailable(self) -> dict[str, Any] | None:
        """A uniform 'Nexus did not answer' payload, or None when it did."""
        last = self.last_result()
        if last.get("ok") is False:
            return {
                "available": False,
                "status": "UNREACHABLE",
                "error": last.get("error") or "no response",
                "endpoint": last.get("url"),
                "sample_data": False,
            }
        return None

    # =========================================================================
    # Core API Methods
    # =========================================================================

    def get_site_status(self) -> dict[str, Any]:
        """POSTs the ``get_site_status`` command and returns Nexus's own reply."""
        if self.mock_mode:
            with self._lock:
                return {
                    "status": self._telemetry.status,
                    "health_score": self._telemetry.health_score,
                    "visitors_today": self._telemetry.visitors_today,
                    "conversion_rate_pct": self._telemetry.conversion_rate_pct,
                    "active_experiments_count": len(
                        [e for e in self._active_experiments.values() if e["status"] == "RUNNING"]
                    ),
                    "leads_detected_today": self._telemetry.leads_detected_today,
                    "active_incidents_count": len(self._incidents),
                    "pending_approvals_count": self._telemetry.pending_approvals_count,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "sample_data": True,
                }

        result = self._nexus_command("get_site_status")
        if not result["ok"]:
            return self._unavailable() or {"available": False, "status": "UNREACHABLE"}
        payload = dict(result["payload"])
        payload.setdefault("status", "UNREPORTED")
        payload["sample_data"] = False
        payload["endpoint"] = result["url"]
        return payload

    def get_high_intent_leads(self) -> list[dict[str, Any]]:
        """Returns the high-intent leads Nexus reports (sample list in mock mode)."""
        if self.mock_mode:
            with self._lock:
                return list(self._leads)

        result = self._nexus_command("get_high_intent_leads")
        if not result["ok"]:
            return []
        payload = result["payload"]
        leads = payload.get("leads", payload.get("high_intent_leads"))
        if leads is None and isinstance(payload.get("data"), list):
            leads = payload["data"]
        return [entry for entry in (leads or []) if isinstance(entry, dict)]

    def diagnose_conversion_drop(self) -> dict[str, Any]:
        """Runs Nexus's own conversion-drop diagnostic and returns its findings."""
        if self.mock_mode:
            return {
                "diagnosis_id": "diag_conv_001",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "primary_cause": "Mobile Safari checkout page layout shift on iOS 17.4+",
                "affected_pages": ["/checkout", "/pricing"],
                "impact_pct": -18.4,
                "remediation_status": "REMEDIATION_PATCH_GENERATED",
                "recommended_action": "Deploy responsive CSS fix to viewport meta and container flex-wrap.",
                "verified_by_nexus_policy": True,
                "sample_data": True,
            }

        result = self._nexus_command("diagnose_conversion_drop")
        if not result["ok"]:
            return self._unavailable() or {"available": False, "status": "UNREACHABLE"}
        payload = dict(result["payload"])
        payload["sample_data"] = False
        payload["endpoint"] = result["url"]
        return payload

    def get_pending_incidents(self) -> list[dict[str, Any]]:
        """Returns the incidents Nexus reports (none seeded unless mock mode)."""
        if self.mock_mode:
            with self._lock:
                return list(self._incidents)

        result = self._nexus_command("get_pending_incidents")
        if not result["ok"]:
            return []
        payload = result["payload"]
        incidents = payload.get("incidents", payload.get("pending_incidents"))
        if incidents is None and isinstance(payload.get("data"), list):
            incidents = payload["data"]
        return [entry for entry in (incidents or []) if isinstance(entry, dict)]

    def start_nexus_workflow(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Asks Nexus to start a workflow through its policy authorization engine."""
        if self.mock_mode:
            workflow_id = f"wf_nexus_{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(f"[NEXUS_OPERATOR] Started sample workflow {name} ({workflow_id})")
            return {
                "workflow_id": workflow_id,
                "workflow_name": name,
                "status": "INITIATED",
                "params": params or {},
                "authorized_by_policy_engine": True,
                "sample_data": True,
            }

        result = self._nexus_command("start_nexus_workflow", {"workflow_name": name, "params": params or {}})
        if not result["ok"]:
            return self._unavailable() or {"available": False, "status": "UNREACHABLE"}
        payload = dict(result["payload"])
        payload.setdefault("workflow_name", name)
        payload.setdefault("params", params or {})
        # Only the endpoint can say whether its policy engine authorized this.
        payload.setdefault("authorized_by_policy_engine", "not reported")
        payload["sample_data"] = False
        payload["endpoint"] = result["url"]
        return payload

    def pause_nexus_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Asks Nexus to halt an experiment (the sample experiment set is mock-only)."""
        if not self.mock_mode:
            result = self._nexus_command("pause_experiment", {"experiment_id": experiment_id})
            if not result["ok"]:
                return {
                    "experiment_id": experiment_id,
                    "success": False,
                    **({"message": f"Nexus did not apply the pause: {result['error']}"} if result["error"] else {}),
                    **(self._unavailable() or {}),
                }
            payload = dict(result["payload"])
            payload.setdefault("experiment_id", experiment_id)
            payload.setdefault("success", result["ok"])
            payload["sample_data"] = False
            payload["endpoint"] = result["url"]
            return payload

        with self._lock:
            exp = self._active_experiments.get(experiment_id)
            if not exp:
                # The sample set is the only place an experiment id exists here.
                active = [e for e in self._active_experiments.values() if e["status"] == "RUNNING"]
                if active:
                    exp = active[0]
                    experiment_id = exp["experiment_id"]
                else:
                    return {
                        "experiment_id": experiment_id,
                        "success": False,
                        "message": "No experiment with that id is in the sample set.",
                        "sample_data": True,
                    }

            exp["status"] = "PAUSED"
            logger.info(f"[NEXUS_OPERATOR] Paused sample experiment: {experiment_id}")
            return {
                "experiment_id": experiment_id,
                "success": True,
                "status": "PAUSED",
                "message": f"Sample experiment `{experiment_id}` ({exp['name']}) was marked PAUSED in this process.",
                "sample_data": True,
            }

    def explain_nexus_decision(self, request_id: str = "req_latest") -> dict[str, Any]:
        """Returns Nexus's own reasoning chain for a decision, or says it has none."""
        if self.mock_mode:
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
                "sample_data": True,
            }

        result = self._nexus_command("explain_decision", {"request_id": request_id})
        if not result["ok"]:
            return self._unavailable() or {"available": False, "status": "UNREACHABLE"}
        payload = dict(result["payload"])
        payload.setdefault("request_id", request_id)
        payload["sample_data"] = False
        payload["endpoint"] = result["url"]
        return payload

    def run_nexus_health_check(self) -> dict[str, Any]:
        """Probes Nexus and reports what it answered (mock mode reports its sample)."""
        if self.mock_mode:
            return {
                "status": "HEALTHY",
                "api_url": self.base_url,
                "tracking_pipeline": "OPERATIONAL",
                "lead_scoring_engine": "ONLINE",
                "ai_universe_bridge": "CONNECTED",
                "policy_engine": "ACTIVE",
                "sample_data": True,
            }

        result = self._nexus_command("health_check")
        if not result["ok"]:
            unavailable = self._unavailable() or {}
            return {
                "status": "UNREACHABLE",
                "api_url": self.base_url,
                "error": unavailable.get("error") or "no response",
                "sample_data": False,
                **unavailable,
            }
        payload = dict(result["payload"])
        payload.setdefault("status", "UNREPORTED")
        payload.setdefault("api_url", self.base_url)
        payload["sample_data"] = False
        payload["http_status"] = result["http_status"]
        return payload

    # =========================================================================
    # Voice Command Execution Loop
    # =========================================================================

    def _no_reading(self, what: str) -> str:
        last = self.last_result()
        return (
            f"Nexus did not answer {last.get('url') or self.command_url} "
            f"({last.get('error') or 'no response'}), so I have no {what} to report."
        )

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
                if st.get("available") is False:
                    spoken = self._no_reading("site health, visitor count or conversion rate")
                else:
                    spoken = (
                        f"🌐 Website Health Status: {st.get('status') or UNKNOWN_LABEL} "
                        f"({format_number(st.get('health_score'), 1, '/100')}). "
                        f"Traffic today: {st.get('visitors_today', UNKNOWN_LABEL)} visitors | "
                        f"Conversion rate: {format_number(st.get('conversion_rate_pct'), 2, '%')} | "
                        f"Leads detected: {st.get('leads_detected_today', UNKNOWN_LABEL)} | "
                        f"Active experiments: {st.get('active_experiments_count', UNKNOWN_LABEL)}."
                        + (" (sample data)" if st.get("sample_data") else "")
                    )
                step_results.append({"action": "get_site_status", "data": st})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "Any high-intent visitors?"
            if any(k in clean for k in ["high-intent visitors", "high intent leads", "any leads", "top leads"]):
                leads = self.get_high_intent_leads()
                if not leads and self.last_result().get("ok") is False and not self.mock_mode:
                    spoken = self._no_reading("high-intent lead list")
                elif not leads:
                    spoken = "Nexus reports no high-intent leads at the moment."
                else:
                    lines = [f"Nexus reports {len(leads)} high-intent leads:"]
                    for lead in leads:
                        lines.append(
                            f"• **{lead.get('company_domain', UNKNOWN_LABEL)}** "
                            f"(Score: {lead.get('score', UNKNOWN_LABEL)}) — "
                            f"{lead.get('evidence', UNKNOWN_LABEL)}"
                        )
                    spoken = "\n".join(lines)
                step_results.append({"action": "get_high_intent_leads", "leads": leads})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "Why did conversions drop?"
            if any(k in clean for k in ["why did conversions drop", "diagnose conversion", "conversion diagnosis"]):
                diag = self.diagnose_conversion_drop()
                if diag.get("available") is False:
                    spoken = self._no_reading("conversion diagnosis")
                else:
                    pages = ", ".join(diag.get("affected_pages") or []) or UNKNOWN_LABEL
                    spoken = (
                        f"Nexus Conversion Diagnosis: primary root cause is "
                        f"**{diag.get('primary_cause') or UNKNOWN_LABEL}** with a reported impact of "
                        f"{format_number(diag.get('impact_pct'), 1, '%')} on {pages}. "
                        f"Recommended remediation: {diag.get('recommended_action') or UNKNOWN_LABEL}"
                        + (" (sample data)" if diag.get("sample_data") else "")
                    )
                step_results.append({"action": "diagnose_conversion_drop", "diagnosis": diag})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "Any website incidents?"
            if any(k in clean for k in ["website incidents", "site incidents", "any website incidents"]):
                incidents = self.get_pending_incidents()
                if not incidents and self.last_result().get("ok") is False and not self.mock_mode:
                    spoken = self._no_reading("incident list")
                elif not incidents:
                    spoken = "Nexus reports no active website incidents."
                else:
                    lines = [f"Nexus reports {len(incidents)} active website incidents:"]
                    for inc in incidents:
                        lines.append(
                            f"• `[{inc.get('severity', UNKNOWN_LABEL)}]` "
                            f"{inc.get('title') or UNKNOWN_LABEL}: {inc.get('description') or UNKNOWN_LABEL}"
                        )
                    spoken = "\n".join(lines)
                step_results.append({"action": "get_pending_incidents", "count": len(incidents)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "Explain that Nexus decision"
            if any(k in clean for k in ["explain that nexus decision", "explain nexus decision", "decision chain"]):
                expl = self.explain_nexus_decision()
                if expl.get("available") is False:
                    spoken = self._no_reading("decision audit")
                else:
                    chain = expl.get("reasoning_chain") or []
                    consultation = expl.get("ai_universe_consultation") or {}
                    spoken = (
                        f"Nexus Decision Audit: decision was **{expl.get('decision') or UNKNOWN_LABEL}** with "
                        f"{format_number(expl.get('confidence_pct'), 1, '%')} confidence. "
                        f"Reasoning: {chain[0] if chain else UNKNOWN_LABEL} "
                        f"AI-Universe consensus: {consultation.get('consensus') or UNKNOWN_LABEL}."
                        + (" (sample data)" if expl.get("sample_data") else "")
                    )
                step_results.append({"action": "explain_nexus_decision", "explanation": expl})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 6. SENSITIVE: "Pause the website experiment"
            if any(k in clean for k in ["pause the website experiment", "pause website experiment", "halt experiment"]):
                res = self.pause_nexus_experiment("exp_hero_cta_v2")
                spoken = res.get("message") or (
                    f"Nexus reported success={res.get('success')} for pausing {res.get('experiment_id')}."
                )
                step_results.append({"action": "pause_nexus_experiment", "result": res})
                return SkillExecutionResult(skill_name=self.name, success=bool(res.get("success")), output=spoken, step_results=step_results)

            # Default
            health = self.run_nexus_health_check()
            if health.get("status") == "UNREACHABLE":
                spoken = (
                    f"Nexus Operator: I probed {health.get('api_url')} and got no answer "
                    f"({health.get('error')}). I have no subsystem state to report."
                )
            else:
                spoken = (
                    f"Nexus Operator: subsystem reports {health.get('status')} at "
                    f"{health.get('api_url')}"
                    + (" (sample data)." if health.get("sample_data") else ".")
                )
            step_results.append({"action": "health_check", "health": health})
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
