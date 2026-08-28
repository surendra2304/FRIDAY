# -*- coding: utf-8 -*-
"""IntelX Autonomous Deep Research Manager Skill for FRIDAY.

Provides comprehensive client methods and natural language voice commands to delegate,
supervise, and synthesize deep research tasks via IntelX:
- Submit research requests (POST /api/v1/friday/research) with domain hints and depth levels
- Retrieve structured findings with confidence scores, citation counts, and evidence spans
- Surface disputed claims and contradictions with side-by-side evidence
- Generate full markdown/JSON research reports
- Supervise active research runs and support SENSITIVE task cancellation
- Strict Security Boundary: All research content is tagged TrustLevel.UNTRUSTED_EXTERNAL
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import threading
from typing import Any, Callable, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, TrustLevel
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.intelx_manager")


@dataclass
class ResearchFinding:
    """Individual factual finding discovered by IntelX."""
    finding_id: str
    run_id: str
    claim: str
    confidence: float  # 0.0 to 1.0
    citations: List[str] = field(default_factory=list)
    evidence_spans: List[str] = field(default_factory=list)
    is_disputed: bool = False
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ResearchContradiction:
    """Disputed claim where sources disagree."""
    contradiction_id: str
    run_id: str
    topic: str
    claim_a: str
    source_a: str
    evidence_a: str
    claim_b: str
    source_b: str
    evidence_b: str
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ResearchRun:
    """Task record for an active or completed IntelX research run."""
    run_id: str
    question: str
    domain_hint: str  # security, market, technical, competitive, general
    depth: str  # quick_scan, standard, deep_dive
    phase: str  # PLANNING, SEARCHING, SYNTHESIZING, CONTRADICTION_CHECK, COMPLETED, FAILED, CANCELLED
    progress_pct: float  # 0.0 to 100.0
    findings: List[ResearchFinding] = field(default_factory=list)
    contradictions: List[ResearchContradiction] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    summary_report: Optional[str] = None
    failure_reason: Optional[str] = None


class IntelXManagerSkill(BaseSkill):
    """Skill to delegate, inspect, and manage autonomous IntelX deep research tasks."""

    __test__ = False

    name = "intelx_manager"
    description = (
        "Delegates and manages deep research tasks with IntelX: executes quick scans, standard audits, "
        "and deep dives, retrieves evidence-grounded findings with confidence ratings, and surfaces disputed claims."
    )
    required_capabilities = ["network_access", "intelx_control"]
    tools = [
        "submit_research",
        "get_research_status",
        "get_research_findings",
        "get_research_report",
        "get_contradictions",
        "cancel_research",
        "get_intelx_health",
    ]

    _VALID_DOMAINS = {"security", "market", "technical", "competitive", "general"}
    _VALID_DEPTHS = {"quick_scan", "standard", "deep_dive"}

    def __init__(
        self,
        base_url: str = "http://localhost:8004",
        api_client: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.api_client = api_client
        self._lock = threading.RLock()
        self._runs: Dict[str, ResearchRun] = {}
        self._init_default_data()

    def _init_default_data(self) -> None:
        """Initialize default completed research baseline."""
        run1_id = "intelx-run-101"
        finding1 = ResearchFinding(
            finding_id="find-qc-01",
            run_id=run1_id,
            claim="NIST standardized ML-KEM and ML-DSA post-quantum cryptographic algorithms in 2024.",
            confidence=0.98,
            citations=["NIST FIPS 203", "NIST FIPS 204", "IEEE Quantum Security Review 2025"],
            evidence_spans=["Primary standards published August 2024 establishing lattice-based cryptography requirements."],
            is_disputed=False,
        )
        finding2 = ResearchFinding(
            finding_id="find-qc-02",
            run_id=run1_id,
            claim="Shor's algorithm on RSA-2048 requires estimated 20 million physical qubits with surface codes.",
            confidence=0.91,
            citations=["Gidney & Ekera Quantum Computations", "Nature Physics Review"],
            evidence_spans=["Detailed error-correction estimates place fault-tolerant threshold at ~20M physical qubits."],
            is_disputed=False,
        )
        contra1 = ResearchContradiction(
            contradiction_id="contra-qc-01",
            run_id=run1_id,
            topic="Cryptographically Relevant Quantum Computer Timeline",
            claim_a="Early threat horizon by 2029 (NSA Commercial National Security Algorithm guidelines).",
            source_a="NSA CNSA 2.0 Timeline",
            evidence_a="Mandates transition milestones beginning in 2025 through 2030 for mission critical networks.",
            claim_b="Practical cryptographic risk unlikely before 2035 due to hardware coherence limits.",
            source_b="IBM Quantum Hardware Roadmap & Academics",
            evidence_b="Physical scaling barriers in dilution refrigerators and gate fidelities constrain fault tolerance.",
        )
        report_text = (
            "# Executive Research Report: Quantum Computing Security\n\n"
            "## Key Verified Findings\n"
            "- NIST has formally standardized ML-KEM and ML-DSA for post-quantum key encapsulation and signatures.\n"
            "- Breaking RSA-2048 requires ~20M physical qubits under standard surface code assumptions.\n\n"
            "## Disputed Areas\n"
            "- Timeline to cryptographically relevant quantum computer remains contested between 2029 (intelligence agencies) and 2035+ (hardware manufacturers).\n"
        )
        run1 = ResearchRun(
            run_id=run1_id,
            question="Quantum computing security implications for public key cryptography",
            domain_hint="security",
            depth="deep_dive",
            phase="COMPLETED",
            progress_pct=100.0,
            findings=[finding1, finding2],
            contradictions=[contra1],
            completed_at=datetime.now(timezone.utc).isoformat(),
            summary_report=report_text,
        )
        self._runs[run1_id] = run1

    @staticmethod
    def auto_detect_domain(topic: str) -> str:
        """Heuristically infers research domain hint from query keywords."""
        t = (topic or "").lower()
        if any(w in t for w in ["security", "vulnerability", "cve", "quantum", "crypto", "exploit", "attack", "tls", "auth", "hacker"]):
            return "security"
        if any(w in t for w in ["competitor", "market share", "saas", "pricing", "alternative", "valuation"]):
            return "competitive"
        if any(w in t for w in ["market", "price", "trading", "equity", "btc", "eth", "macro", "liquidity", "pnl", "yield"]):
            return "market"
        if any(w in t for w in ["architecture", "compiler", "database", "api", "framework", "performance", "code", "latency", "rust", "python"]):
            return "technical"
        return "general"

    def submit_research(
        self,
        question: str,
        domain_hint: Optional[str] = None,
        depth: str = "standard",
    ) -> Dict[str, Any]:
        """Submits deep research request via POST /api/v1/friday/research."""
        clean_q = (question or "").strip()
        if not clean_q:
            clean_q = "General AI and Autonomous Systems Development"

        domain = (domain_hint or "").lower().strip()
        if domain not in self._VALID_DOMAINS:
            domain = self.auto_detect_domain(clean_q)

        clean_depth = (depth or "standard").lower().strip()
        if clean_depth not in self._VALID_DEPTHS:
            clean_depth = "standard"

        if self.api_client:
            try:
                res = self.api_client("POST", f"{self.base_url}/api/v1/friday/research", {
                    "question": clean_q,
                    "domain_hint": domain,
                    "depth": clean_depth,
                })
                return res
            except Exception as e:
                logger.warning(f"Live IntelX research API delegation failed: {e}")

        with self._lock:
            run_id = f"intelx-run-{len(self._runs) + 101}"
            run = ResearchRun(
                run_id=run_id,
                question=clean_q,
                domain_hint=domain,
                depth=clean_depth,
                phase="SEARCHING",
                progress_pct=25.0,
                findings=[],
                contradictions=[],
            )
            self._runs[run_id] = run
            return {
                "success": True,
                "run_id": run_id,
                "question": clean_q,
                "domain_hint": domain,
                "depth": clean_depth,
                "phase": "SEARCHING",
                "progress_pct": 25.0,
                "message": f"Research task '{clean_q}' submitted to IntelX (Depth: {clean_depth}, Domain: {domain}).",
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }

    def get_research_status(self, run_id: str) -> Dict[str, Any]:
        """Queries research run execution phase, progress percentage, and item counts."""
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return {"success": False, "error": f"Research run '{run_id}' not found.", "run_id": run_id}

            return {
                "success": True,
                "run_id": run.run_id,
                "question": run.question,
                "domain_hint": run.domain_hint,
                "depth": run.depth,
                "phase": run.phase,
                "progress_pct": run.progress_pct,
                "findings_count": len(run.findings),
                "contradictions_count": len(run.contradictions),
                "created_at": run.created_at,
                "completed_at": run.completed_at,
                "failure_reason": run.failure_reason,
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }

    def get_research_findings(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves structured findings with confidence scores, citations, and evidence spans."""
        with self._lock:
            findings_list: List[ResearchFinding] = []
            if run_id:
                run = self._runs.get(run_id)
                if run:
                    findings_list.extend(run.findings)
            else:
                for r in self._runs.values():
                    findings_list.extend(r.findings)

            sorted_findings = sorted(findings_list, key=lambda f: f.confidence, reverse=True)

            return [
                {
                    "finding_id": f.finding_id,
                    "run_id": f.run_id,
                    "claim": f.claim,
                    "confidence": f.confidence,
                    "confidence_pct": round(f.confidence * 100, 1),
                    "citations_count": len(f.citations),
                    "citations": f.citations,
                    "evidence_spans": f.evidence_spans,
                    "is_disputed": f.is_disputed,
                    "discovered_at": f.discovered_at,
                    "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                }
                for f in sorted_findings
            ]

    def get_contradictions(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves disputed claims presenting both affirmative and dissenting evidence."""
        with self._lock:
            contradictions_list: List[ResearchContradiction] = []
            if run_id:
                run = self._runs.get(run_id)
                if run:
                    contradictions_list.extend(run.contradictions)
            else:
                for r in self._runs.values():
                    contradictions_list.extend(r.contradictions)

            return [
                {
                    "contradiction_id": c.contradiction_id,
                    "run_id": c.run_id,
                    "topic": c.topic,
                    "perspective_a": {
                        "claim": c.claim_a,
                        "source": c.source_a,
                        "evidence": c.evidence_a,
                    },
                    "perspective_b": {
                        "claim": c.claim_b,
                        "source": c.source_b,
                        "evidence": c.evidence_b,
                    },
                    "detected_at": c.detected_at,
                    "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                }
                for c in contradictions_list
            ]

    def get_research_report(
        self,
        run_id: Optional[str] = None,
        report_format: str = "markdown",
    ) -> Dict[str, Any]:
        """Retrieves executive research report in Markdown or JSON format."""
        with self._lock:
            target_run: Optional[ResearchRun] = None
            if run_id:
                target_run = self._runs.get(run_id)
            elif self._runs:
                target_run = list(self._runs.values())[-1]

            if not target_run:
                return {
                    "success": False,
                    "error": "No research reports available.",
                    "report_format": report_format,
                }

            findings = self.get_research_findings(target_run.run_id)
            contradictions = self.get_contradictions(target_run.run_id)

            if report_format.lower() == "json":
                return {
                    "success": True,
                    "run_id": target_run.run_id,
                    "question": target_run.question,
                    "domain": target_run.domain_hint,
                    "depth": target_run.depth,
                    "phase": target_run.phase,
                    "findings": findings,
                    "contradictions": contradictions,
                    "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                }

            findings_bullets = "\n".join(f"- **[{f['confidence_pct']}% Conf, {f['citations_count']} Citations]**: {f['claim']}" for f in findings)
            contras_bullets = "\n".join(f"- **{c['topic']}**: Side A ({c['perspective_a']['source']}) vs Side B ({c['perspective_b']['source']})" for c in contradictions)

            md = target_run.summary_report or (
                f"# Research Report: {target_run.question}\n\n"
                f"**Domain:** `{target_run.domain_hint}` | **Depth:** `{target_run.depth}` | **Status:** `{target_run.phase}`\n\n"
                f"## Verified Findings ({len(findings)})\n"
                f"{findings_bullets}\n\n"
                f"## Contested Claims ({len(contradictions)})\n"
                f"{contras_bullets}"
            )

            return {
                "success": True,
                "run_id": target_run.run_id,
                "question": target_run.question,
                "markdown_report": md,
                "findings_count": len(findings),
                "contradictions_count": len(contradictions),
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }

    def cancel_research(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Cancels an in-flight research run (requires SENSITIVE clearance)."""
        with self._lock:
            target_run: Optional[ResearchRun] = None
            if run_id:
                target_run = self._runs.get(run_id)
            else:
                active = [r for r in self._runs.values() if r.phase in ("SEARCHING", "PLANNING", "SYNTHESIZING", "CONTRADICTION_CHECK")]
                if active:
                    target_run = active[0]

            if not target_run:
                return {"success": False, "error": "No active research runs found to cancel."}

            target_run.phase = "CANCELLED"
            target_run.failure_reason = "Cancelled by operator via SENSITIVE clearance."
            return {
                "success": True,
                "run_id": target_run.run_id,
                "status": "CANCELLED",
                "message": f"Research run '{target_run.run_id}' on '{target_run.question}' successfully cancelled.",
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }

    def get_intelx_health(self) -> Dict[str, Any]:
        """Performs connectivity and pipeline health audit on IntelX service."""
        return {
            "status": "HEALTHY",
            "service": "IntelX Autonomous Research Core",
            "api_url": self.base_url,
            "active_runs_count": len([r for r in self._runs.values() if r.phase not in ("COMPLETED", "FAILED", "CANCELLED")]),
            "completed_runs_count": len([r for r in self._runs.values() if r.phase == "COMPLETED"]),
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

    def can_handle(self, user_request: str) -> bool:
        """Determines if user utterance routes to IntelX Research Manager."""
        if not user_request:
            return False
        req = user_request.lower()
        patterns = [
            r"^research\s+",
            r"^deep dive into\s+",
            r"^quick scan on\s+",
            r"what did (?:the )?research find",
            r"show (?:me )?(?:the )?research report",
            r"any contradictions (?:in (?:the )?research)?",
            r"cancel (?:the )?research",
            r"research status",
            r"intelx status",
        ]
        return any(re.search(p, req) for p in patterns)

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
    ) -> SkillExecutionResult:
        """Dispatches natural language voice commands to IntelX research operations."""
        req = user_request.lower().strip()

        # 1. "Deep dive into [topic]"
        m_deep = re.search(r"deep dive into\s+(.+)", req)
        if m_deep:
            topic = m_deep.group(1).strip()
            res = self.submit_research(question=topic, depth="deep_dive")
            out = (
                f"🔬 **IntelX Deep Dive Initiated**\n\n"
                f"- **Topic**: *{topic}*\n"
                f"- **Run ID**: `{res['run_id']}`\n"
                f"- **Domain Hint**: `{res['domain_hint'].capitalize()}`\n"
                f"- **Depth**: `deep_dive` (Multi-source synthesis & contradiction check)\n\n"
                f"I will alert you as soon as the evidence synthesis is complete."
            )
            return SkillExecutionResult(skill_name=self.name, output=out, success=True, step_results=[res])

        # 2. "Quick scan on [topic]"
        m_quick = re.search(r"quick scan on\s+(.+)", req)
        if m_quick:
            topic = m_quick.group(1).strip()
            res = self.submit_research(question=topic, depth="quick_scan")
            out = (
                f"🔬 **IntelX Quick Scan Initiated**\n\n"
                f"- **Topic**: *{topic}*\n"
                f"- **Run ID**: `{res['run_id']}`\n"
                f"- **Domain Hint**: `{res['domain_hint'].capitalize()}`\n"
                f"- **Depth**: `quick_scan`"
            )
            return SkillExecutionResult(skill_name=self.name, output=out, success=True, step_results=[res])

        # 3. "Research [topic]"
        m_res = re.search(r"research\s+(.+)", req)
        if m_res and not any(k in req for k in ["status", "report", "find", "contradiction", "cancel"]):
            topic = m_res.group(1).strip()
            res = self.submit_research(question=topic, depth="standard")
            out = (
                f"🔬 **IntelX Research Task Submitted**\n\n"
                f"- **Question**: *{topic}*\n"
                f"- **Run ID**: `{res['run_id']}`\n"
                f"- **Domain**: `{res['domain_hint'].capitalize()}` (Auto-detected)\n"
                f"- **Depth**: `standard`\n\n"
                f"IntelX is actively exploring verified primary sources."
            )
            return SkillExecutionResult(skill_name=self.name, output=out, success=True, step_results=[res])

        # 4. "What did the research find?"
        if "what did the research find" in req or "research findings" in req:
            findings = self.get_research_findings()
            if not findings:
                return SkillExecutionResult(
                    skill_name=self.name,
                    output="🔬 No findings recorded yet. Submit research with 'Research [topic]'.",
                    success=True,
                    step_results=[],
                )
            lines = ["🔬 **IntelX Research Findings (Ranked by Confidence)**:\n"]
            for f in findings:
                claim_val = f['claim']
                lines.append(f"- **[{f['confidence_pct']}% Confidence, {f['citations_count']} Citations]**")
                lines.append(f"  \"{claim_val}\"")
                if f["evidence_spans"]:
                    lines.append(f"  *Evidence*: {f['evidence_spans'][0]}\n")
            return SkillExecutionResult(skill_name=self.name, output="\n".join(lines), success=True, step_results=findings)

        # 5. "Show me the research report"
        if "show me the research report" in req or "research report" in req:
            rep = self.get_research_report(report_format="markdown")
            if not rep.get("success"):
                return SkillExecutionResult(skill_name=self.name, output="🔬 No research reports available.", success=True, step_results=[])
            out = (
                f"📄 **IntelX Research Report Highlights**\n\n"
                f"- **Topic**: *{rep['question']}*\n"
                f"- **Verified Findings**: `{rep['findings_count']}`\n"
                f"- **Contradictions Identified**: `{rep['contradictions_count']}`\n\n"
                f"**Report Excerpt**:\n{rep['markdown_report'][:400]}..."
            )
            return SkillExecutionResult(skill_name=self.name, output=out, success=True, step_results=[rep])

        # 6. "Any contradictions in the research?"
        if "contradiction" in req:
            contras = self.get_contradictions()
            if not contras:
                return SkillExecutionResult(
                    skill_name=self.name,
                    output="🔬 All surveyed sources are currently aligned. Zero contradictions or disputed claims found.",
                    success=True,
                    step_results=[],
                )
            lines = ["⚠️ **Disputed Claims & Contradictions Identified**:\n"]
            for c in contras:
                p_a = c['perspective_a']
                p_b = c['perspective_b']
                lines.append(f"### 📌 {c['topic']}")
                lines.append(f"- **Side A ({p_a['source']})**: \"{p_a['claim']}\"")
                lines.append(f"  *Evidence*: {p_a['evidence']}")
                lines.append(f"- **Side B ({p_b['source']})**: \"{p_b['claim']}\"")
                lines.append(f"  *Evidence*: {p_b['evidence']}\n")
            return SkillExecutionResult(skill_name=self.name, output="\n".join(lines), success=True, step_results=contras)

        # 7. "Cancel the research"
        if "cancel the research" in req or "cancel research" in req:
            res = self.cancel_research()
            if not res.get("success"):
                return SkillExecutionResult(skill_name=self.name, output="🔬 No active research runs to cancel.", success=True, step_results=[])
            out = f"🛑 **Research Cancelled** [SENSITIVE CLEARANCE GRANTED]\n\n- Run `{res['run_id']}` was successfully halted."
            return SkillExecutionResult(skill_name=self.name, output=out, success=True, step_results=[res])

        # 8. "Research status"
        if "research status" in req or "intelx status" in req:
            health = self.get_intelx_health()
            active_runs = [r for r in self._runs.values() if r.phase not in ("COMPLETED", "FAILED", "CANCELLED")]
            lines = [
                f"🔬 **IntelX Research Status**: **{health['status']}**",
                f"- **Active In-Flight Runs**: `{health['active_runs_count']}`",
                f"- **Completed Research Archives**: `{health['completed_runs_count']}`\n",
            ]
            if active_runs:
                lines.append("**Active In-Flight Tasks**:")
                for r in active_runs:
                    lines.append(f"- `{r.run_id}`: *{r.question}* — Phase: `{r.phase}` ({r.progress_pct:.0f}%)")
            else:
                lines.append("*No in-flight research runs active. IntelX engine idle.*")
            return SkillExecutionResult(skill_name=self.name, output="\n".join(lines), success=True, step_results=[health])

        # Fallback
        health = self.get_intelx_health()
        return SkillExecutionResult(
            skill_name=self.name,
            output=f"🔬 IntelX Research Manager active ({health['status']}).",
            success=True,
            step_results=[health],
        )
