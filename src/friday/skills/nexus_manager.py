"""Nexus Manager Skill for FRIDAY.

Management and supervision of the Nexus Autonomous Website & Growth Engine:
- Site overview, live visitors, lead pipeline, incidents, approvals, strategy performance
- AI Universe consultation intelligence logging and decision reasoning audits
- Natural language analytics queries and website health audits
- SENSITIVE action approvals/rejections with evidence readouts
- Invariant: All Nexus-generated data is stored and tagged with TrustLevel.UNTRUSTED_EXTERNAL.

Honesty contract
----------------
This module used to serve a complete, self-consistent picture of a website that
had not been contacted: a 98.6/100 health score, 5,120 visitors, a 3.82%
conversion rate ("+4.6% vs yesterday"), "3 agents active (CRO Analyst, Lead
Scorer, UX Guard)", three named live visitor sessions, four named pipeline leads
with scores, a pending CSS approval with p=0.012 evidence, three strategy
learnings at a 100% win rate, and an analytics endpoint that answered *any*
question with invented figures ("Average sitewide bounce rate is 32.4%") at
"confidence 0.95". ``mock_mode`` was stored and never read.

Now: ``mock_mode=False`` (the default) sends the matching command to Nexus over
HTTP and reports its answer, or ``UNREACHABLE`` with the error. The sample data
is still available — for tests and demos — behind ``mock_mode=True``, where every
response is tagged ``sample_data: True``.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.readings import UNKNOWN_LABEL, format_number
from friday.integrations.nexus_client import NexusCommandClient
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.nexus_manager")


@dataclass
class NexusVisitorSession:
    """Active visitor session on the website (sample data unless live mode fills it)."""

    session_id: str
    visitor_ip_hash: str
    current_page: str
    dwell_time_seconds: int
    intent_score: float  # 0.0 to 1.0
    intent_level: str  # LOW, MEDIUM, HIGH, VERY_HIGH
    inferred_company: str | None = None
    key_actions: list[str] = field(default_factory=list)


@dataclass
class NexusPipelineLead:
    """Lead tracked across funnel stages."""

    lead_id: str
    company_domain: str
    score: int  # 0 to 100
    stage: str  # DISCOVERY, EVALUATION, DECISION, CLOSED_WON
    intent_score: float  # 0.0 to 1.0
    evidence: str
    recommended_next_action: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class NexusApprovalAction:
    """Optimization or growth action awaiting operator approval."""

    action_id: str
    title: str
    action_type: str  # COPY_CHANGE, PRICING_TEST, POPUP_TRIGGER, CSS_HOTFIX
    target_page: str
    hypothesis: str
    evidence: str
    expected_lift_pct: float
    confidence_score: float
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    decision_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NexusManagerSkill(BaseSkill):
    """Full API client and voice skill for Nexus Website & Growth Intelligence."""

    __test__ = False

    name = "nexus_manager"
    description = (
        "Complete management interface for Nexus Autonomous Website & Growth Engine: monitors live visitors, "
        "tracks lead pipelines by stage, manages active incidents and pending approvals with evidence readouts, "
        "inspects AI-Universe consultation logs, measures strategy performance, and runs site health checks."
    )
    required_capabilities = ["network_access", "nexus_control"]
    tools = [
        "get_site_overview",
        "get_live_visitors",
        "get_lead_pipeline",
        "get_incidents",
        "get_pending_approvals",
        "approve_nexus_action",
        "reject_nexus_action",
        "start_nexus_workflow",
        "get_intelligence_log",
        "get_strategy_performance",
        "query_nexus_analytics",
        "run_website_health_check",
    ]
    system_prompt = (
        "You are FRIDAY's Nexus Website & Growth Manager. You provide real-time website intelligence, lead insights, "
        "incident triage, and optimization workflows while strictly tagging all external data as UNTRUSTED_EXTERNAL."
    )
    match_patterns = [
        r"\b(?:website\s+status|site\s+overview|how\s+is\s+the\s+website\s+doing)\b",
        r"\b(?:who(?:'s|\s+is)\s+on\s+my\s+website|live\s+visitors?|active\s+visitors?)\b",
        r"\b(?:any\s+new\s+leads|recent\s+leads|website\s+leads)\b",
        r"\b(?:what(?:'s|\s+is)\s+my\s+conversion\s+rate|conversion\s+rate\s+today|conversion\s+trend)\b",
        r"\b(?:any\s+website\s+problems|website\s+incidents|site\s+errors)\b",
        r"\b(?:show\s+(?:the\s+)?lead\s+pipeline|lead\s+pipeline\s+by\s+stage)\b",
        r"\b(?:approve\s+(?:that\s+)?nexus\s+action|confirm\s+nexus\s+action)\b",
        r"\b(?:why\s+did\s+nexus\s+recommend\s+that|nexus\s+reasoning\s+chain|nexus\s+decision\s+audit)\b",
        r"\b(?:what\s+has\s+nexus\s+learned|strategy\s+performance|growth\s+learnings)\b",
        r"\b(?:run\s+website\s+health\s+check|site\s+audit|website\s+audit)\b",
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
        self._client = NexusCommandClient(base_url=self.base_url, timeout_sec=timeout_sec)

        # Live-mode state starts empty: nothing here is a reading about the site.
        self._site_health_score: float | None = None
        self._conversion_rate_today: float | None = None
        self._conversion_rate_yesterday: float | None = None
        self._conversion_rate_trend: str | None = None
        self._visitors_today_count: int | None = None
        self._sessions_today_count: int | None = None
        self._agent_activity_status: str | None = None
        self._live_visitors: list[NexusVisitorSession] = []
        self._pipeline_leads: list[NexusPipelineLead] = []
        self._active_incidents: list[dict[str, Any]] = []
        self._pending_approvals: list[NexusApprovalAction] = []
        self._strategy_learnings: list[dict[str, Any]] = []
        self._intelligence_log: list[dict[str, Any]] = []

        if self.mock_mode:
            self._init_sample_state()

    # =========================================================================
    # Sample state (served only in mock mode)
    # =========================================================================

    def _init_sample_state(self) -> None:
        """The sample website. Served only when mock_mode is on."""
        self._site_health_score = 98.6
        self._conversion_rate_today = 3.82
        self._conversion_rate_yesterday = 3.65
        self._conversion_rate_trend = "+4.6% vs yesterday"
        self._visitors_today_count = 5120
        self._sessions_today_count = 6480
        self._agent_activity_status = "3 agents active (CRO Analyst, Lead Scorer, UX Guard)"

        self._live_visitors = [
            NexusVisitorSession(
                session_id="sess_8901",
                visitor_ip_hash="ip_hash_a1b2",
                current_page="/pricing",
                dwell_time_seconds=340,
                intent_score=0.92,
                intent_level="VERY_HIGH",
                inferred_company="acme-corp.com",
                key_actions=["Viewed Enterprise tier", "Downloaded Security Whitepaper", "Expanded FAQ"],
            ),
            NexusVisitorSession(
                session_id="sess_8902",
                visitor_ip_hash="ip_hash_c3d4",
                current_page="/docs/trading-api",
                dwell_time_seconds=185,
                intent_score=0.84,
                intent_level="HIGH",
                inferred_company="fintech-scaleup.io",
                key_actions=["Tested API endpoint in sandbox", "Copied Python SDK snippet"],
            ),
            NexusVisitorSession(
                session_id="sess_8903",
                visitor_ip_hash="ip_hash_e5f6",
                current_page="/blog/ai-agents-2026",
                dwell_time_seconds=45,
                intent_score=0.25,
                intent_level="LOW",
                inferred_company=None,
                key_actions=["Read intro paragraph"],
            ),
        ]

        self._pipeline_leads = [
            NexusPipelineLead(
                lead_id="lead_1001",
                company_domain="acme-corp.com",
                score=94,
                stage="DECISION",
                intent_score=0.92,
                evidence="4 visits to pricing, visited SLA docs, security whitepaper downloaded",
                recommended_next_action="Trigger personalized Enterprise demo booking modal",
            ),
            NexusPipelineLead(
                lead_id="lead_1002",
                company_domain="fintech-scaleup.io",
                score=87,
                stage="EVALUATION",
                intent_score=0.84,
                evidence="Tested live trading API endpoint in interactive sandbox",
                recommended_next_action="Send automated developer quickstart onboarding email",
            ),
            NexusPipelineLead(
                lead_id="lead_1003",
                company_domain="global-ventures.co",
                score=76,
                stage="DISCOVERY",
                intent_score=0.71,
                evidence="Organic search entry on AI agent architecture, viewed 3 product pages",
                recommended_next_action="Show case study notification popup on next visit",
            ),
            NexusPipelineLead(
                lead_id="lead_1004",
                company_domain="cloud-nexus.net",
                score=98,
                stage="CLOSED_WON",
                intent_score=0.99,
                evidence="Completed self-serve Pro annual subscription checkout",
                recommended_next_action="Schedule automated VIP customer success check-in",
            ),
        ]

        self._pending_approvals = [
            NexusApprovalAction(
                action_id="act_hero_contrast_v3",
                title="Deploy Hero CTA Contrast Enhancement",
                action_type="CSS_HOTFIX",
                target_page="/",
                hypothesis=(
                    "Increasing primary CTA button luminance from 4.2:1 to 7.1:1 contrast will increase "
                    "click-throughs on mobile devices."
                ),
                evidence="A/B test variant showed +11.4% click-through rate over 4,500 mobile visits with p=0.012 significance.",
                expected_lift_pct=11.4,
                confidence_score=0.96,
                status="PENDING",
            )
        ]

        self._strategy_learnings = [
            {
                "strategy_name": "Dynamic Social Proof Badging",
                "status": "PROMOTED_TO_PRODUCTION",
                "win_rate_pct": 100.0,
                "measured_lift_pct": 14.8,
                "learning": "Displaying real-time enterprise logo badging on /pricing increases demo requests by 14.8%.",
            },
            {
                "strategy_name": "Annual Billing Pre-Selection",
                "status": "PROMOTED_TO_PRODUCTION",
                "win_rate_pct": 100.0,
                "measured_lift_pct": 8.2,
                "learning": "Defaulting annual billing toggle with 'Save 20%' banner increases annual plan selection by 8.2%.",
            },
            {
                "strategy_name": "Aggressive Exit-Intent Popup",
                "status": "DISCARDED",
                "win_rate_pct": 0.0,
                "measured_lift_pct": -6.4,
                "learning": "Immediate exit popups caused bounce rates to spike and reduced return visits by 6.4%.",
            },
        ]

        self._intelligence_log = [
            {
                "consultation_id": "ai_cons_901",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "query": "Review copy variations for hero section headline targeting enterprise CTOs",
                "ai_universe_model": "claude-3-7-sonnet / reasoning-core",
                "recommendation": "Adopt 'Autonomous Intelligence Built for Mission-Critical Operations' headline",
                "confidence": 0.94,
                "reasoning_chain": [
                    "Analyzed enterprise B2B conversion data across high-intent segments.",
                    "Identified 'Mission-Critical' phrasing aligns with security and compliance buyers.",
                    "AI-Universe copy consultant confirmed zero brand risk.",
                ],
                "trust_level": "UNTRUSTED_EXTERNAL",
            }
        ]

    # =========================================================================
    # Transport
    # =========================================================================

    @property
    def command_url(self) -> str:
        return self._client.command_url

    def last_result(self) -> dict[str, Any]:
        """Outcome of the most recent live command (mock mode reports the sample)."""
        if self.mock_mode:
            return {"ok": True, "sample_data": True, "url": self.command_url, "error": None}
        return self._client.last_result()

    def _no_reading(self, what: str) -> str:
        last = self.last_result()
        return (
            f"Nexus did not answer {last.get('url') or self.command_url} "
            f"({last.get('error') or 'no response'}), so I have no {what} to report."
        )

    def _live(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Runs one live command and returns the client's result dict."""
        return self._client.command(command, payload)

    def _list_from(self, payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        """Reads a reported list; missing or malformed fields are not an empty list."""
        for key in keys:
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, list):
                self._client.mark_invalid_response(f"Invalid Nexus response: '{key}' was not a list")
                return []
            if any(not isinstance(entry, dict) for entry in value):
                self._client.mark_invalid_response(f"Invalid Nexus response: '{key}' contained a non-object entry")
                return []
            return value

        if "data" in payload:
            data = payload["data"]
            if isinstance(data, list) and all(isinstance(entry, dict) for entry in data):
                return data
            self._client.mark_invalid_response("Invalid Nexus response: 'data' was not a list of objects")
            return []

        expected = " or ".join(f"'{key}'" for key in keys)
        self._client.mark_invalid_response(f"Invalid Nexus response: missing list field {expected}")
        return []

    # =========================================================================
    # Core API Methods
    # =========================================================================

    def get_site_overview(self) -> dict[str, Any]:
        """Returns Nexus's site overview, or says it has none (sample in mock mode)."""
        if self.mock_mode:
            with self._lock:
                visitors_today = self._visitors_today_count
                leads = [lead for lead in self._pipeline_leads if lead.stage != "CLOSED_WON"]
                pending = [a for a in self._pending_approvals if a.status == "PENDING"]
                return {
                    "health_score": self._site_health_score,
                    "status": "HEALTHY" if not self._active_incidents else "DEGRADED",
                    "visitors_today": visitors_today,
                    "sessions_today": self._sessions_today_count,
                    "live_active_visitors": len(self._live_visitors),
                    "conversion_rate_today": self._conversion_rate_today,
                    "conversion_rate_yesterday": self._conversion_rate_yesterday,
                    "conversion_trend": self._conversion_rate_trend,
                    "leads_today_count": len(leads),
                    "active_incidents_count": len(self._active_incidents),
                    "pending_approvals_count": len(pending),
                    "agent_activity": self._agent_activity_status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trust_level": "UNTRUSTED_EXTERNAL",
                    "sample_data": True,
                }

        result = self._live("get_site_overview")
        if not result["ok"]:
            return self._client.unavailable()
        overview = dict(result["payload"])
        overview.setdefault("status", "UNREPORTED")
        overview["trust_level"] = "UNTRUSTED_EXTERNAL"
        overview["sample_data"] = False
        overview["endpoint"] = result["url"]
        return overview

    def get_live_visitors(self) -> list[dict[str, Any]]:
        """Returns the visitor sessions Nexus reports (sample list in mock mode)."""
        if self.mock_mode:
            with self._lock:
                return [
                    {
                        "session_id": v.session_id,
                        "current_page": v.current_page,
                        "dwell_time_seconds": v.dwell_time_seconds,
                        "intent_score": v.intent_score,
                        "intent_level": v.intent_level,
                        "inferred_company": v.inferred_company,
                        "key_actions": list(v.key_actions),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                        "sample_data": True,
                    }
                    for v in self._live_visitors
                ]

        result = self._live("get_live_visitors")
        if not result["ok"]:
            return []
        return [
            dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=False)
            for entry in self._list_from(result["payload"], "visitors", "live_visitors", "sessions")
        ]

    def get_lead_pipeline(self) -> dict[str, list[dict[str, Any]]]:
        """Returns pipeline leads grouped by funnel stage, as Nexus reports them."""
        stages: dict[str, list[dict[str, Any]]] = {
            "DISCOVERY": [],
            "EVALUATION": [],
            "DECISION": [],
            "CLOSED_WON": [],
        }

        if self.mock_mode:
            with self._lock:
                for lead in self._pipeline_leads:
                    lead_dict = {
                        "lead_id": lead.lead_id,
                        "company_domain": lead.company_domain,
                        "score": lead.score,
                        "stage": lead.stage,
                        "intent_score": lead.intent_score,
                        "evidence": lead.evidence,
                        "recommended_next_action": lead.recommended_next_action,
                        "created_at": lead.created_at,
                        "trust_level": "UNTRUSTED_EXTERNAL",
                        "sample_data": True,
                    }
                    stages.setdefault(lead.stage, stages["DISCOVERY"]).append(lead_dict)
                return stages

        result = self._live("get_lead_pipeline")
        if not result["ok"]:
            stages["UNREPORTED"] = []
            return stages
        for lead_entry in self._list_from(result["payload"], "leads", "pipeline"):
            stage = str(lead_entry.get("stage") or "UNSTAGED").upper()
            entry = dict(lead_entry)
            entry["trust_level"] = "UNTRUSTED_EXTERNAL"
            entry["sample_data"] = False
            stages.setdefault(stage, []).append(entry)
        return stages

    def get_incidents(self) -> list[dict[str, Any]]:
        """Returns reported incidents; inspect ``last_result()`` to distinguish unavailable from empty."""
        if self.mock_mode:
            with self._lock:
                return [dict(inc, trust_level="UNTRUSTED_EXTERNAL", sample_data=True) for inc in self._active_incidents]

        result = self._live("get_incidents")
        if not result["ok"]:
            return []
        return [
            dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=False)
            for entry in self._list_from(result["payload"], "incidents", "active_incidents")
        ]

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Returns pending optimization actions Nexus reports (sample in mock mode)."""
        if self.mock_mode:
            with self._lock:
                return [
                    {
                        "action_id": a.action_id,
                        "title": a.title,
                        "action_type": a.action_type,
                        "target_page": a.target_page,
                        "hypothesis": a.hypothesis,
                        "evidence": a.evidence,
                        "expected_lift_pct": a.expected_lift_pct,
                        "confidence_score": a.confidence_score,
                        "status": a.status,
                        "created_at": a.created_at,
                        "trust_level": "UNTRUSTED_EXTERNAL",
                        "sample_data": True,
                    }
                    for a in self._pending_approvals
                    if a.status == "PENDING"
                ]

        result = self._live("get_pending_approvals")
        if not result["ok"]:
            return []
        return [
            dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=False)
            for entry in self._list_from(result["payload"], "approvals", "pending_approvals")
        ]

    def approve_nexus_action(self, action_id: str) -> dict[str, Any]:
        """Asks Nexus to approve a pending action (mock mode flips the sample flag).

        The message used to end "Deployed to production.", which nothing in this
        process did or could verify.
        """
        if not self.mock_mode:
            result = self._live("approve_action", {"action_id": action_id})
            if not result["ok"]:
                return {
                    "success": False,
                    "action_id": action_id,
                    **self._client.unavailable(),
                    "message": f"Nexus did not apply the approval: {result['error']}",
                }
            payload = dict(result["payload"])
            response_action_id = payload.get("action_id")
            response_status = str(payload.get("status") or "").upper()
            reported_success = payload.get("success")
            matches_requested_action = response_action_id in (None, action_id)
            status_matches_request = not response_status or response_status == "APPROVED"
            confirmed = matches_requested_action and status_matches_request and (
                reported_success is True or response_status == "APPROVED"
            )
            payload.setdefault("action_id", action_id)
            payload["requested_action_id"] = action_id
            payload["success"] = confirmed
            if not confirmed:
                if response_status:
                    payload["nexus_reported_status"] = response_status
                payload["status"] = "UNCONFIRMED"
                payload.setdefault(
                    "message",
                    "Nexus answered the approval request but did not confirm that this action was approved.",
                )
                if not matches_requested_action:
                    payload["message"] = "Nexus responded for a different action; this approval was not confirmed."
            payload["trust_level"] = "UNTRUSTED_EXTERNAL"
            payload["sample_data"] = False
            return payload

        with self._lock:
            action = next((a for a in self._pending_approvals if a.action_id == action_id), None)
            if not action:
                pending = [a for a in self._pending_approvals if a.status == "PENDING"]
                if pending:
                    action = pending[0]
                    action_id = action.action_id
                else:
                    return {
                        "success": False,
                        "action_id": action_id,
                        "status": "NOT_FOUND",
                        "message": "No pending action found to approve.",
                    }

            action.status = "APPROVED"
            action.decision_reason = "Approved by human operator via FRIDAY command."
            logger.info(f"[NEXUS_MANAGER] Approved sample action {action_id}: {action.title}")
            return {
                "success": True,
                "action_id": action_id,
                "title": action.title,
                "status": "APPROVED",
                "message": (
                    f"Sample action `{action_id}` ({action.title}) is now marked APPROVED in this process. "
                    f"No deployment was performed here; Nexus applies it, if it exists."
                ),
                "trust_level": "UNTRUSTED_EXTERNAL",
                "sample_data": True,
            }

    def reject_nexus_action(self, action_id: str, reason: str = "Operator declined") -> dict[str, Any]:
        """Asks Nexus to reject a pending action with recorded reasoning."""
        if not self.mock_mode:
            result = self._live("reject_action", {"action_id": action_id, "reason": reason})
            if not result["ok"]:
                return {
                    "success": False,
                    "action_id": action_id,
                    "reason": reason,
                    **self._client.unavailable(),
                    "message": f"Nexus did not apply the rejection: {result['error']}",
                }
            payload = dict(result["payload"])
            response_action_id = payload.get("action_id")
            response_status = str(payload.get("status") or "").upper()
            reported_success = payload.get("success")
            matches_requested_action = response_action_id in (None, action_id)
            status_matches_request = not response_status or response_status == "REJECTED"
            confirmed = matches_requested_action and status_matches_request and (
                reported_success is True or response_status == "REJECTED"
            )
            payload.setdefault("action_id", action_id)
            payload["requested_action_id"] = action_id
            payload["success"] = confirmed
            if not confirmed:
                if response_status:
                    payload["nexus_reported_status"] = response_status
                payload["status"] = "UNCONFIRMED"
                payload.setdefault(
                    "message",
                    "Nexus answered the rejection request but did not confirm that this action was rejected.",
                )
                if not matches_requested_action:
                    payload["message"] = "Nexus responded for a different action; this rejection was not confirmed."
            payload["trust_level"] = "UNTRUSTED_EXTERNAL"
            payload["sample_data"] = False
            return payload

        with self._lock:
            action = next((a for a in self._pending_approvals if a.action_id == action_id), None)
            if not action:
                pending = [a for a in self._pending_approvals if a.status == "PENDING"]
                if pending:
                    action = pending[0]
                    action_id = action.action_id
                else:
                    return {
                        "success": False,
                        "action_id": action_id,
                        "status": "NOT_FOUND",
                        "message": "No pending action found to reject.",
                    }

            action.status = "REJECTED"
            action.decision_reason = reason
            logger.info(f"[NEXUS_MANAGER] Rejected sample action {action_id}: {reason}")
            return {
                "success": True,
                "action_id": action_id,
                "title": action.title,
                "status": "REJECTED",
                "reason": reason,
                "message": f"Sample action `{action_id}` is now marked REJECTED in this process. Reason: {reason}",
                "trust_level": "UNTRUSTED_EXTERNAL",
                "sample_data": True,
            }

    def start_nexus_workflow(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Asks Nexus to start a growth/optimization workflow through its policy engine."""
        if not self.mock_mode:
            result = self._live("start_workflow", {"workflow_name": name, "params": params or {}})
            if not result["ok"]:
                return {
                    "success": False,
                    "workflow_name": name,
                    **self._client.unavailable(),
                    "message": f"Nexus did not start the workflow: {result['error']}",
                }
            payload = dict(result["payload"])
            payload.setdefault("workflow_name", name)
            payload.setdefault("params", params or {})
            # Only Nexus can say whether its policy engine authorized this.
            payload.setdefault("authorized_by_policy_engine", "not reported")
            payload["trust_level"] = "UNTRUSTED_EXTERNAL"
            payload["sample_data"] = False
            return payload

        wf_id = f"wf_nx_{int(datetime.now(timezone.utc).timestamp())}"
        logger.info(f"[NEXUS_MANAGER] Started sample workflow {name} ({wf_id})")
        return {
            "workflow_id": wf_id,
            "workflow_name": name,
            "status": "INITIATED",
            "params": params or {},
            "authorized_by_policy_engine": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trust_level": "UNTRUSTED_EXTERNAL",
            "sample_data": True,
        }

    def get_intelligence_log(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieves recent AI-Universe consultation records Nexus reports."""
        if self.mock_mode:
            with self._lock:
                return [
                    dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=True)
                    for entry in self._intelligence_log[:limit]
                ]

        result = self._live("get_intelligence_log", {"limit": limit})
        if not result["ok"]:
            return []
        return [
            dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=False)
            for entry in self._list_from(result["payload"], "consultations", "intelligence_log", "log")[:limit]
        ]

    def get_strategy_performance(self) -> list[dict[str, Any]]:
        """Retrieves measured strategy performance Nexus reports."""
        if self.mock_mode:
            with self._lock:
                return [
                    dict(s, trust_level="UNTRUSTED_EXTERNAL", sample_data=True) for s in self._strategy_learnings
                ]

        result = self._live("get_strategy_performance")
        if not result["ok"]:
            return []
        return [
            dict(entry, trust_level="UNTRUSTED_EXTERNAL", sample_data=False)
            for entry in self._list_from(result["payload"], "strategies", "strategy_performance", "learnings")
        ]

    def query_nexus_analytics(self, question: str) -> dict[str, Any]:
        """Asks Nexus a natural-language analytics question.

        The answers used to be literals — a 32.4% bounce rate, 1,240 pricing
        views, "112ms avg" response time — returned at "confidence 0.95" for any
        question at all.
        """
        if not self.mock_mode:
            result = self._live("query_analytics", {"question": question})
            if not result["ok"]:
                return {
                    "question": question,
                    "answer": self._no_reading("analytics answer"),
                    "confidence": None,
                    "available": False,
                    "status": "UNREACHABLE",
                    "error": result["error"],
                    "trust_level": "UNTRUSTED_EXTERNAL",
                    "sample_data": False,
                }
            payload = dict(result["payload"])
            payload.setdefault("question", question)
            payload.setdefault("answer", "Nexus answered without an 'answer' field.")
            payload["trust_level"] = "UNTRUSTED_EXTERNAL"
            payload["sample_data"] = False
            return payload

        with self._lock:
            clean = question.lower()
            if "bounce" in clean:
                answer = "Average sitewide bounce rate is 32.4%, with blog pages at 44% and checkout at 12.1%."
            elif "traffic" in clean or "visitor" in clean:
                answer = (
                    f"Total traffic today is {self._visitors_today_count:,} visitors across "
                    f"{self._sessions_today_count:,} sessions."
                )
            elif "pricing" in clean:
                answer = "The /pricing page has received 1,240 views today with an 18.2% click-through to checkout."
            else:
                answer = (
                    f"Sample analytics summary for '{question}': conversion rate is "
                    f"{format_number(self._conversion_rate_today, 2, '%')} ({self._conversion_rate_trend}) "
                    f"with nominal server response times (112ms avg)."
                )

            return {
                "question": question,
                "answer": answer,
                "confidence": 0.95,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trust_level": "UNTRUSTED_EXTERNAL",
                "sample_data": True,
            }

    def run_website_health_check(self) -> dict[str, Any]:
        """Probes Nexus for a website health audit, or says it did not answer."""
        if self.mock_mode:
            with self._lock:
                return {
                    "overall_status": "HEALTHY",
                    "health_score": self._site_health_score,
                    "api_gateway": "ONLINE (Port 8002)",
                    "event_tracking_pipeline": "OPERATIONAL (0 dropped events)",
                    "lead_scoring_engine": "ACTIVE (Latency 45ms)",
                    "ai_universe_bridge": "CONNECTED",
                    "policy_guardrails": "ENFORCING",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "trust_level": "UNTRUSTED_EXTERNAL",
                    "sample_data": True,
                }

        result = self._live("health_check")
        if not result["ok"]:
            return {
                "overall_status": "UNREACHABLE",
                "api_url": self.base_url,
                "error": result["error"] or "no response",
                "trust_level": "UNTRUSTED_EXTERNAL",
                "sample_data": False,
                **self._client.unavailable(),
            }
        payload = dict(result["payload"])
        payload.setdefault("overall_status", payload.get("status", "UNREPORTED"))
        payload["trust_level"] = "UNTRUSTED_EXTERNAL"
        payload["sample_data"] = False
        payload["http_status"] = result["http_status"]
        return payload

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
        """Executes voice-driven Nexus website and growth manager commands."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []
        sample_suffix = " (sample data)" if self.mock_mode else ""

        try:
            # 1. "Website status" / "Site overview"
            if any(k in clean for k in ["website status", "site overview", "how is the website doing"]):
                ov = self.get_site_overview()
                if ov.get("available") is False:
                    spoken = self._no_reading("website overview")
                else:
                    spoken = (
                        f"🌐 Website Health Overview: status is {ov.get('status', UNKNOWN_LABEL)} "
                        f"({format_number(ov.get('health_score'), 1, '/100')}). "
                        f"Traffic: {ov.get('visitors_today', UNKNOWN_LABEL)} visitors "
                        f"({ov.get('live_active_visitors', UNKNOWN_LABEL)} live) | "
                        f"Conversion rate: {format_number(ov.get('conversion_rate_today'), 2, '%')} "
                        f"({ov.get('conversion_trend') or UNKNOWN_LABEL}) | "
                        f"Pipeline leads: {ov.get('leads_today_count', UNKNOWN_LABEL)} | "
                        f"Active incidents: {ov.get('active_incidents_count', UNKNOWN_LABEL)} | "
                        f"Pending approvals: {ov.get('pending_approvals_count', UNKNOWN_LABEL)}."
                        + sample_suffix
                    )
                step_results.append({"action": "get_site_overview", "data": ov})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "Who's on my website?" / "Live visitors"
            if any(k in clean for k in ["who's on my website", "who is on my website", "live visitors", "active visitors"]):
                visitors = self.get_live_visitors()
                if not visitors and self.last_result().get("ok") is False:
                    spoken = self._no_reading("live visitor list")
                elif not visitors:
                    spoken = "Nexus reports no active visitors right now." + sample_suffix
                else:
                    high_intent = [
                        v for v in visitors if isinstance(v.get("intent_score"), (int, float)) and v["intent_score"] >= 0.8
                    ]
                    lines = [
                        f"Nexus reports {len(visitors)} active visitors on the site "
                        f"({len(high_intent)} of them high intent):"
                    ]
                    for v in visitors:
                        comp = f" from **{v['inferred_company']}**" if v.get("inferred_company") else ""
                        lines.append(
                            f"• Visitor on `{v.get('current_page', UNKNOWN_LABEL)}`{comp} — "
                            f"Intent: {v.get('intent_level', UNKNOWN_LABEL)} "
                            f"({format_number(v.get('intent_score'), 2)}) | "
                            f"Dwell: {v.get('dwell_time_seconds', UNKNOWN_LABEL)}s"
                        )
                    spoken = "\n".join(lines) + sample_suffix
                step_results.append({"action": "get_live_visitors", "visitors": visitors})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "Any new leads?" / "Recent leads"
            if any(k in clean for k in ["any new leads", "recent leads", "website leads"]):
                pipeline = self.get_lead_pipeline()
                all_leads = pipeline.get("DECISION", []) + pipeline.get("EVALUATION", []) + pipeline.get("DISCOVERY", [])
                if not all_leads and self.last_result().get("ok") is False:
                    spoken = self._no_reading("lead list")
                elif not all_leads:
                    spoken = "Nexus reports no prospective leads in the pipeline." + sample_suffix
                else:
                    lines = [f"Nexus is tracking {len(all_leads)} active prospective leads:"]
                    for lead in all_leads[:5]:
                        lines.append(
                            f"• **{lead.get('company_domain', UNKNOWN_LABEL)}** "
                            f"(Score: {lead.get('score', UNKNOWN_LABEL)}/100, Stage: {lead.get('stage', 'LEAD')}) — "
                            f"{lead.get('evidence', UNKNOWN_LABEL)}"
                        )
                    spoken = "\n".join(lines) + sample_suffix
                step_results.append({"action": "get_recent_leads", "count": len(all_leads)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "What's my conversion rate?"
            if any(k in clean for k in ["what's my conversion rate", "what is my conversion rate", "conversion rate today", "conversion trend"]):
                ov = self.get_site_overview()
                if ov.get("available") is False:
                    spoken = self._no_reading("conversion rate")
                else:
                    spoken = (
                        f"📊 Nexus reports today's website conversion rate as "
                        f"**{format_number(ov.get('conversion_rate_today'), 2, '%')}** "
                        f"({ov.get('conversion_trend') or UNKNOWN_LABEL}). "
                        f"Yesterday: {format_number(ov.get('conversion_rate_yesterday'), 2, '%')}. "
                        f"Traffic volume: {ov.get('visitors_today', UNKNOWN_LABEL)} visitors."
                        + sample_suffix
                    )
                step_results.append({"action": "get_conversion_rate", "data": ov})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. "Any website problems?" / "Website incidents"
            if any(k in clean for k in ["any website problems", "website incidents", "site errors"]):
                incidents = self.get_incidents()
                if not incidents and self.last_result().get("ok") is False:
                    spoken = self._no_reading("incident list")
                elif not incidents:
                    spoken = "Nexus reports no active website incidents." + sample_suffix
                else:
                    lines = [f"⚠️ Nexus reports {len(incidents)} active website incidents:"]
                    for inc in incidents:
                        lines.append(
                            f"• `[{inc.get('severity', UNKNOWN_LABEL)}]` {inc.get('title', UNKNOWN_LABEL)}: "
                            f"{inc.get('description', UNKNOWN_LABEL)}"
                        )
                    spoken = "\n".join(lines) + sample_suffix
                step_results.append({"action": "get_incidents", "count": len(incidents)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 6. "Show the lead pipeline"
            if any(k in clean for k in ["show the lead pipeline", "show lead pipeline", "lead pipeline by stage"]):
                pipe = self.get_lead_pipeline()
                if "UNREPORTED" in pipe and not any(pipe[k] for k in ("DISCOVERY", "EVALUATION", "DECISION", "CLOSED_WON")):
                    spoken = self._no_reading("lead pipeline")
                else:

                    def _domains(stage: str) -> str:
                        return ", ".join(
                            str(lead.get("company_domain", UNKNOWN_LABEL)) for lead in pipe.get(stage, [])
                        ) or "none reported"

                    lines = [
                        "🎯 **Nexus Lead Pipeline by Stage**:",
                        f"• **Decision ({len(pipe.get('DECISION', []))}):** " + _domains("DECISION"),
                        f"• **Evaluation ({len(pipe.get('EVALUATION', []))}):** " + _domains("EVALUATION"),
                        f"• **Discovery ({len(pipe.get('DISCOVERY', []))}):** " + _domains("DISCOVERY"),
                        f"• **Closed Won ({len(pipe.get('CLOSED_WON', []))}):** " + _domains("CLOSED_WON"),
                    ]
                    spoken = "\n".join(lines) + sample_suffix
                step_results.append({"action": "get_lead_pipeline", "pipeline": pipe})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 7. SENSITIVE: "Approve that Nexus action"
            if any(k in clean for k in ["approve that nexus action", "approve nexus action", "confirm nexus action"]):
                approvals = self.get_pending_approvals()
                if not approvals:
                    message = (
                        self._no_reading("pending approval to act on")
                        if self.last_result().get("ok") is False
                        else "There are no pending Nexus actions to approve." + sample_suffix
                    )
                    return SkillExecutionResult(skill_name=self.name, success=True, output=message, step_results=[])

                target = approvals[0]
                res = self.approve_nexus_action(str(target.get("action_id", "")))
                if res.get("success"):
                    if self.mock_mode:
                        spoken = (
                            f"✅ Sample action **{res.get('status', 'APPROVED')}**: `{target.get('action_id')}` "
                            f"({target.get('title', UNKNOWN_LABEL)}). Evidence: "
                            f"{target.get('evidence', UNKNOWN_LABEL)} Expected lift: "
                            f"{format_number(target.get('expected_lift_pct'), 1, '%')}. "
                            "This only updates in-process sample state; no live Nexus request or deployment was made."
                            + sample_suffix
                        )
                    elif str(res.get("status") or "").upper() == "APPROVED":
                        spoken = (
                            f"✅ Nexus reports action **APPROVED**: `{target.get('action_id')}` "
                            f"({target.get('title', UNKNOWN_LABEL)}). Evidence: "
                            f"{target.get('evidence', UNKNOWN_LABEL)} Expected lift: "
                            f"{format_number(target.get('expected_lift_pct'), 1, '%')}."
                        )
                    else:
                        spoken = (
                            f"Nexus confirmed the approval request for `{target.get('action_id')}`, "
                            "but did not report the action status. "
                            f"Evidence reported: {target.get('evidence', UNKNOWN_LABEL)}."
                        )
                else:
                    spoken = f"The approval did not take effect: {res.get('message') or res.get('error')}"
                step_results.append({"action": "approve_nexus_action", "result": res})
                return SkillExecutionResult(skill_name=self.name, success=bool(res.get("success")), output=spoken, step_results=step_results)

            # 8. "Why did Nexus recommend that?" / "Reasoning chain"
            if any(k in clean for k in ["why did nexus recommend that", "nexus reasoning chain", "nexus decision audit"]):
                logs = self.get_intelligence_log(limit=1)
                if not logs:
                    spoken = (
                        self._no_reading("decision reasoning chain")
                        if self.last_result().get("ok") is False
                        else "Nexus has no consultation on record to explain." + sample_suffix
                    )
                else:
                    log = logs[0]
                    chain = log.get("reasoning_chain") or []
                    steps_text = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(chain)) or "No reasoning steps were reported."
                    spoken = (
                        "🧠 **Nexus Decision Reasoning Chain**:\n"
                        f"Recommendation: *{log.get('recommendation', UNKNOWN_LABEL)}* "
                        f"(Confidence: {format_number(log.get('confidence') * 100 if isinstance(log.get('confidence'), (int, float)) else None, 1, '%')})\n"
                        f"Reasoning:\n{steps_text}\n"
                        f"Consulted AI Universe Model: `{log.get('ai_universe_model', UNKNOWN_LABEL)}`."
                        + sample_suffix
                    )
                step_results.append({"action": "explain_nexus_decision", "log": logs})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 9. "What has Nexus learned?" / "Strategy performance"
            if any(k in clean for k in ["what has nexus learned", "strategy performance", "growth learnings"]):
                learnings = self.get_strategy_performance()
                if not learnings:
                    spoken = (
                        self._no_reading("strategy performance")
                        if self.last_result().get("ok") is False
                        else "Nexus reports no strategy results yet." + sample_suffix
                    )
                else:
                    lines = [f"📈 **Nexus Growth Strategy Learnings ({len(learnings)} reported)**:"]
                    for entry in learnings:
                        icon = "✅" if entry.get("status") == "PROMOTED_TO_PRODUCTION" else "❌"
                        lines.append(
                            f"{icon} **{entry.get('strategy_name', UNKNOWN_LABEL)}** "
                            f"({entry.get('status', UNKNOWN_LABEL)}): {entry.get('learning', UNKNOWN_LABEL)} "
                            f"(Lift: {format_number(entry.get('measured_lift_pct'), 1, '%')})"
                        )
                    spoken = "\n".join(lines) + sample_suffix
                step_results.append({"action": "get_strategy_performance", "learnings": learnings})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 10. "Run website health check" / "Site audit"
            if any(k in clean for k in ["run website health check", "site audit", "website audit", "website health check"]):
                health = self.run_website_health_check()
                if not health.get("available", True) or health.get("overall_status") == "UNREACHABLE":
                    spoken = (
                        f"🏥 Website operational audit could not run: I probed {health.get('api_url')} and got no "
                        f"answer ({health.get('error')})."
                    )
                else:
                    details = "\n".join(
                        f"• {label}: {health.get(key, UNKNOWN_LABEL)}"
                        for label, key in (
                            ("API Gateway", "api_gateway"),
                            ("Event Pipeline", "event_tracking_pipeline"),
                            ("Lead Scorer", "lead_scoring_engine"),
                            ("AI Universe Bridge", "ai_universe_bridge"),
                            ("Policy Guardrails", "policy_guardrails"),
                        )
                    )
                    spoken = (
                        f"🏥 **Website Operational Audit**: status is "
                        f"**{health.get('overall_status', UNKNOWN_LABEL)}** "
                        f"(Score: {format_number(health.get('health_score'), 1, '/100')}).\n{details}"
                        + sample_suffix
                    )
                step_results.append({"action": "run_website_health_check", "health": health})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # Fallback Analytics Query
            analytics = self.query_nexus_analytics(user_request)
            step_results.append({"action": "query_nexus_analytics", "result": analytics})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=analytics.get("answer", UNKNOWN_LABEL) + sample_suffix,
                step_results=step_results,
            )

        except Exception as e:
            logger.error(f"[NEXUS_MANAGER] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Nexus Manager error: {e}",
                error=str(e),
                step_results=step_results,
            )
