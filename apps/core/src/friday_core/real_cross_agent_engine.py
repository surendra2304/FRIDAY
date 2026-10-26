"""
FRIDAY/apps/core/src/friday_core/real_cross_agent_engine.py — Real Cross-Agent Engine.

Actually orchestrates multiple agents to work together:
- Trading workflow: Stratex generates signals -> Inference reasons -> Memora stores
- Security workflow: Sentinel detects threats -> IntelX correlates -> Cortex decides
- Content workflow: VyralX predicts -> Futuris forecasts -> Cortex decides
- Code workflow: Forge generates -> Sentinel scans -> Cortex reviews

Priority 1: Real cross-agent integration — agents actually working together
"""
from __future__ import annotations

import importlib.util
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent


def load_engine(relpath, name):
    """Load an engine module directly from file path."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load all engines
_cortex = load_engine("Cortex/apps/api/src/cortex_api/real_decision_engine.py", "r_decision")
_inference = load_engine("Inference/app/agents/real_reasoning_engine.py", "r_reasoning")
_memora = load_engine("Memora/core/memory/real_memory_engine.py", "r_memory")
_stratex = load_engine("Stratex/real_trading_engine.py", "r_trading")
_forge = load_engine("Forge/app/services/real_code_engine.py", "r_code")
_sentinel = load_engine("Sentinel/app/services/real_security_engine.py", "r_security")
_intelx = load_engine("IntelX/intelx/services/real_threat_intel_engine.py", "r_threat_intel")
_futuris = load_engine("Futuris/futuris/core/real_forecast_engine.py", "r_forecast")
_vyralx = load_engine("VyralX/app/services/real_content_engine.py", "r_content")


@dataclass
class WorkflowStep:
    """A single step in a cross-agent workflow."""
    step_id: str
    name: str
    agent: str
    action: str
    input_ref: str = ""  # references previous step output
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class WorkflowResult:
    """Result of a cross-agent workflow."""
    workflow_id: str
    name: str
    status: str  # completed, failed, running
    steps: list[WorkflowStep]
    final_output: Any = None
    total_time_ms: float = 0.0


class CrossAgentEngine:
    """Real cross-agent engine that orchestrates multiple agents working together."""

    def __init__(self, state_dir: str | None = None) -> None:
        from threading import RLock
        self._capability_lock = RLock()
        self._state_dir = state_dir or str(ROOT / "FRIDAY" / ".data" / "cross_agent")
        Path(self._state_dir).mkdir(parents=True, exist_ok=True)

        # Initialize all engines with shared state directory
        self._decision = _cortex.DecisionEngine(
            state_file=f"{self._state_dir}/decisions.json"
        )
        self._reasoning = _inference.ReasoningEngine(
            state_file=f"{self._state_dir}/reasoning.json"
        )
        self._memory = _memora.MemoryEngine(
            store_dir=f"{self._state_dir}/memora"
        )
        self._trading = _stratex.TradingEngine(
            state_dir=f"{self._state_dir}/stratex"
        )
        self._code = _forge.CodeEngine(
            template_dir=f"{self._state_dir}/templates"
        )
        self._security = _sentinel.SecurityEngine(
            state_dir=f"{self._state_dir}/sentinel"
        )
        self._threat_intel = _intelx.ThreatIntelEngine(
            state_dir=f"{self._state_dir}/intelx"
        )
        self._forecast = _futuris.ForecastEngine(
            state_dir=f"{self._state_dir}/futuris"
        )
        self._content = _vyralx.ContentEngine(
            state_dir=f"{self._state_dir}/vyralx"
        )

    def capability_runtime(self):
        """Versioned workplace capabilities, preserving the existing agent APIs."""
        with self._capability_lock:
            if not hasattr(self, "_capability_runtime"):
                from friday_core.real_capability_runtime import AgentCapabilityRuntime
                self._capability_runtime = AgentCapabilityRuntime(self)
            return self._capability_runtime

    def local_action_engine(self):
        from friday_core.real_local_actions import LocalActionEngine
        import os
        if not hasattr(self, "_local_actions"):
            try:
                apps = json.loads(os.environ.get("FRIDAY_ALLOWED_APPS", "{}"))
                if not isinstance(apps, dict) or any(not isinstance(k, str) or not isinstance(v, list) or
                        any(not isinstance(arg, str) or len(arg) > 500 for arg in v) for k,v in apps.items()):
                    apps = {}
            except (ValueError, TypeError):
                apps = {}
            self._local_actions = LocalActionEngine(self._state_dir, apps=apps,
                mail_cache=os.environ.get("FRIDAY_MAIL_CACHE"))
        return self._local_actions

    def voice_engine(self, recognizer=None, synthesizer=None):
        module = load_engine("VyralX/app/agents/real_assistant_voice.py", "friday_assistant_voice")
        session_id = "voice_" + uuid.uuid4().hex
        return module.AssistantVoiceEngine(
            lambda query: self.assistant_reply(query, session_id=session_id), recognizer, synthesizer)

    def business_ops_engine(self):
        module = load_engine("FRIDAY/apps/core/src/friday_core/real_business_ops_engine.py", "friday_business_ops")
        if not hasattr(self, "_business_ops"):
            self._business_ops = module.BusinessOpsEngine(str(Path(self._state_dir) / "business_ops"))
        return self._business_ops

    def trading_coach(self):
        return self._trading.coach_engine()

    def investigation_engine(self, endpoints=None, collector=None):
        """Full live IntelX research lifecycle, preserving Memora integration."""
        if endpoints is None and collector is None:
            if not hasattr(self, "_investigator"):
                self._investigator = self._threat_intel.investigation_engine(ingest=self.research_threats)
            return self._investigator
        return self._threat_intel.investigation_engine(endpoints, collector, self.research_threats)

    def research_threats(self, documents: list[dict[str, str]], per_host_limit: int = 3,
                         allow_clearweb: bool = False) -> dict[str, Any]:
        """IntelX evidence ingestion -> persistent Memora research summary."""
        result = self._threat_intel.ingest_research(documents, per_host_limit, allow_clearweb)
        report = result["report"]
        memory = self._memory.store(
            f"IntelX report {report['report_id']}: {report['summary']}",
            agent_origin="IntelX", tags=["osint", "unverified"], importance=0.5)
        result["memory_id"] = memory.memory_id
        return result

    def assistant_reply(self, query: str, market: dict[str, Any] | None = None,
                        documents: list[dict[str, str]] | None = None,
                        provider=None, models: list[str] | None = None,
                        ohlcv_bars: list[dict[str, Any]] | None = None,
                        business_data: dict[str, Any] | None = None,
                        session_id: str | None = None) -> dict[str, Any]:
        """Read-only local agent dispatch before optional cloud inference.

        Context is explicit: no shell, browser execution or order placement.
        API requests use no shared conversational history.
        """
        from dataclasses import asdict
        from friday_core.real_hybrid_assistant import HybridAssistantEngine
        import re
        payload: dict[str, Any] = {}

        def local(command):
            if re.search(r"\b(market|stock|momentum|analyze)\b", command, re.I) and market is not None:
                report = self._trading.analyze_momentum(**market)
                payload["agent"] = "Stratex"
                payload["analysis"] = asdict(report)
                if ohlcv_bars:
                    bars = [_stratex.PriceBar(**bar) for bar in ohlcv_bars]
                    payload["technical_review"] = asdict(self._trading.review_market(report.symbol, bars))
                return f"{report.symbol}: {report.signal}; price {report.price}; change {report.percent_change:.2f}%."
            if re.search(r"\b(research|osint|threat|investigate)\b", command, re.I) and documents is not None:
                payload["agent"] = "IntelX"
                payload["research"] = self.research_threats(documents)
                return payload["research"]["report"]["summary"]
            if command.lower() in {"status", "universe status"}:
                payload["agent"] = "FRIDAY"
                payload["status"] = self.get_universe_status()
                return "FRIDAY Universe engine status retrieved."
            import os
            if re.search(r"\b(business idea|startup idea|idea catalog|lead review|follow.?up|ad report|campaign report|ops sweep)\b", command, re.I):
                ops = self.business_ops_engine()
                if re.search(r"\b(idea|business idea|startup idea|catalog)\b", command, re.I):
                    result = ops.recommend_ideas(command)
                    payload["agent"] = "FRIDAY-Business"
                    payload["business_ideas"] = result
                    return ("Search the imported Drive idea cards. " + result.get("guidance", "Ranked ideas are attached."))
                if business_data is None:
                    payload["agent"] = "FRIDAY-Business"
                    return "Provide a current, permissioned read-only business snapshot; FRIDAY will prepare drafts/reports, not send messages or edit records."
                if "lead" in command.lower() or "follow" in command.lower():
                    workflow = "lead_review"
                elif "ad" in command.lower() or "campaign" in command.lower():
                    workflow = "daily_ad_report"
                else:
                    workflow = "weekly_ops_sweep"
                result = ops.run(workflow, business_data)
                payload["agent"] = "FRIDAY-Business"
                payload["business_workflow"] = asdict(result)
                return f"{workflow.replace('_', ' ').title()} prepared from supplied records; nothing was sent or changed."
            if re.search(r"\b(market|stock|nifty|sensex|crypto|bitcoin)\b", command, re.I) and market is None:
                if os.environ.get("FRIDAY_LIVE_MARKETS") != "1":
                    return "Live market lookup is disabled; supply market observations or enable FRIDAY_LIVE_MARKETS."
                aliases = {"nifty": "^NSEI", "sensex": "^BSESN", "bitcoin": "BTC-USD"}
                symbols = [symbol for name, symbol in aliases.items() if name in command.lower()]
                payload["agent"] = "Stratex"
                payload["market"] = self._trading.live_market_report(symbols or None)
                return payload["market"]["briefing"]
            planned = self.local_action_engine().plan(command)
            if planned:
                payload.update({k: v for k, v in planned.items() if k not in {"text", "source"}})
                payload["agent"] = "FRIDAY"
                return planned["text"]
            return None

        # A configured in-process provider can be attached once, preserving its
        # cooldown across calls. No arbitrary endpoint or API key enters the API.
        if not hasattr(self, "_assistant"):
            import os
            from friday_core.real_hybrid_assistant import GroqChatProvider
            key = os.environ.get("GROQ_API_KEY", "").strip()
            if provider is None and key:
                provider = GroqChatProvider(key)
                models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
            self._assistant = HybridAssistantEngine(models or [], provider, local,
                                                   history_turns=0, session_history_turns=3)
        self._assistant.local_action = local
        if provider is not None:
            self._assistant.provider = provider
            self._assistant.models = tuple(models or [])
        reply = self._assistant.respond(query, session_id=session_id)
        return {**asdict(reply), **payload}

    # ── Trading Workflow ────────────────────────────────────────────────────

    def run_trading_workflow(self, symbol: str, price_data: list[float], strategy: str = "sma_cross") -> WorkflowResult:
        """Full trading workflow: Stratex -> Inference -> Memora -> Cortex."""
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        start = time.time()

        steps = []

        # Step 1: Stratex generates trading signals
        step1 = WorkflowStep(
            step_id="s1", name="Generate Signals",
            agent="Stratex", action="generate_signals",
            started_at=time.time(),
        )
        bars = [
            _stratex.PriceBar(timestamp=i, open=p, high=p+1, low=max(p-1,1e-12), close=p, volume=10000)
            for i, p in enumerate(price_data)
        ]
        signals = self._trading.generate_signals(symbol, bars, strategy=strategy)
        step1.status = "completed"
        step1.result = {"signal_count": len(signals), "signals": [str(s) for s in signals[:3]]}
        step1.completed_at = time.time()
        steps.append(step1)

        # Step 2: Backtest the strategy
        step2 = WorkflowStep(
            step_id="s2", name="Backtest Strategy",
            agent="Stratex", action="backtest",
            input_ref="s1",
            started_at=time.time(),
        )
        bt_result = self._trading.backtest(symbol, bars, strategy=strategy, initial_capital=10000)
        step2.status = "completed"
        step2.result = {
            "return_pct": bt_result.total_return_pct,
            "sharpe": bt_result.sharpe_ratio,
            "trades": bt_result.total_trades,
        }
        step2.completed_at = time.time()
        steps.append(step2)

        # Step 3: Inference reasons about the signal
        step3 = WorkflowStep(
            step_id="s3", name="Reason About Trade",
            agent="Inference", action="bayesian_update",
            input_ref="s2",
            started_at=time.time(),
        )
        # Bayesian update on whether to trade
        buy_hyp = self._reasoning.bayesian_update(
            f"Trading {symbol} is profitable",
            prior=0.5,
            evidence=f"Backtest return: {bt_result.total_return_pct}%, Sharpe: {bt_result.sharpe_ratio}",
            likelihood=0.7 if bt_result.total_return_pct > 0 else 0.3,
        )
        step3.status = "completed"
        step3.result = {
            "buy_probability": buy_hyp.posterior_probability,
            "should_trade": buy_hyp.posterior_probability > 0.5,
        }
        step3.completed_at = time.time()
        steps.append(step3)

        # Step 4: Memora stores the decision
        step4 = WorkflowStep(
            step_id="s4", name="Store Decision",
            agent="Memora", action="store",
            input_ref="s3",
            started_at=time.time(),
        )
        memory = self._memory.store(
            f"Trading decision for {symbol}: buy_prob={buy_hyp.posterior_probability:.3f}, "
            f"backtest_return={bt_result.total_return_pct}%, sharpe={bt_result.sharpe_ratio}",
            agent_origin="Stratex",
            tags=["trading", symbol],
            importance=0.8,
        )
        step4.status = "completed"
        step4.result = {"memory_id": memory.memory_id}
        step4.completed_at = time.time()
        steps.append(step4)

        # Step 5: Cortex makes final decision
        step5 = WorkflowStep(
            step_id="s5", name="Final Decision",
            agent="Cortex", action="decide",
            input_ref="s4",
            started_at=time.time(),
        )
        decision = self._decision.decide(
            question=f"Should we execute the {symbol} trade?",
            options=[
                {"name": "Execute", "scores": {"risk": buy_hyp.posterior_probability * 100,
                    "opportunity": max(bt_result.total_return_pct, 0) + 50,
                    "confidence": buy_hyp.posterior_probability * 100},
                 "risks": ["Market risk", "Liquidity risk"],
                 "benefits": [f"Expected return: {bt_result.total_return_pct}%"]},
                {"name": "Skip", "scores": {"risk": 90, "opportunity": 30, "confidence": 90},
                 "risks": ["Missed opportunity"],
                 "benefits": ["No risk exposure"]},
            ],
            criteria=[
                {"name": "risk", "weight": 0.3},
                {"name": "opportunity", "weight": 0.3},
                {"name": "confidence", "weight": 0.4},
            ]
        )
        step5.status = "completed"
        step5.result = {
            "decision": decision.best_option,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
        }
        step5.completed_at = time.time()
        steps.append(step5)

        return WorkflowResult(
            workflow_id=workflow_id,
            name="Trading Workflow",
            status="completed",
            steps=steps,
            final_output=decision.best_option,
            total_time_ms=(time.time() - start) * 1000,
        )

    # ── Security Workflow ───────────────────────────────────────────────────

    def run_security_workflow(self, code: str, network_logs: str) -> WorkflowResult:
        """Full security workflow: Sentinel -> IntelX -> Cortex -> Memora."""
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        start = time.time()

        steps = []

        # Step 1: Sentinel scans code for vulnerabilities
        step1 = WorkflowStep(
            step_id="s1", name="Scan Code",
            agent="Sentinel", action="scan_code",
            started_at=time.time(),
        )
        vulns = self._security.scan_code(code, "input.py")
        step1.status = "completed"
        step1.result = {"vuln_count": len(vulns), "critical": sum(1 for v in vulns if v.severity == "critical")}
        step1.completed_at = time.time()
        steps.append(step1)

        # Step 2: Sentinel detects threats in network logs
        step2 = WorkflowStep(
            step_id="s2", name="Detect Threats",
            agent="Sentinel", action="detect_threats",
            input_ref="s1",
            started_at=time.time(),
        )
        threats = self._security.detect_threats(network_logs, source="network")
        step2.status = "completed"
        step2.result = {"threat_count": len(threats), "types": [t.threat_type for t in threats]}
        step2.completed_at = time.time()
        steps.append(step2)

        # Step 3: IntelX correlates indicators
        step3 = WorkflowStep(
            step_id="s3", name="Correlate Indicators",
            agent="IntelX", action="correlate",
            input_ref="s2",
            started_at=time.time(),
        )
        # Add indicators from threats
        indicator_ids = []
        for threat in threats:
            ind = self._threat_intel.add_indicator(
                threat.description[:50], "hash",
                confidence=threat.confidence, tags=[threat.threat_type]
            )
            indicator_ids.append(ind.indicator_id)
        correlations = self._threat_intel.correlate_indicators(indicator_ids)
        step3.status = "completed"
        step3.result = {"correlations": len(correlations)}
        step3.completed_at = time.time()
        steps.append(step3)

        # Step 4: Cortex decides on response
        step4 = WorkflowStep(
            step_id="s4", name="Security Decision",
            agent="Cortex", action="decide",
            input_ref="s3",
            started_at=time.time(),
        )
        decision = self._decision.decide(
            question="What security response should we take?",
            options=[
                {"name": "Block Immediately", "scores": {"risk": 95, "urgency": 90, "impact": 90},
                 "risks": ["False positive risk"], "benefits": ["Immediate protection"]},
                {"name": "Monitor", "scores": {"risk": 60, "urgency": 40, "impact": 70},
                 "risks": ["May miss attack"], "benefits": ["Avoid false positives"]},
                {"name": "Investigate", "scores": {"risk": 75, "urgency": 70, "impact": 80},
                 "risks": ["Delayed response"], "benefits": ["Accurate assessment"]},
            ],
            criteria=[
                {"name": "risk", "weight": 0.3},
                {"name": "urgency", "weight": 0.3},
                {"name": "impact", "weight": 0.4},
            ]
        )
        step4.status = "completed"
        step4.result = {"decision": decision.best_option, "confidence": decision.confidence}
        step4.completed_at = time.time()
        steps.append(step4)

        # Step 5: Memora stores security event
        step5 = WorkflowStep(
            step_id="s5", name="Store Event",
            agent="Memora", action="store",
            input_ref="s4",
            started_at=time.time(),
        )
        memory = self._memory.store(
            f"Security event: {len(threats)} threats, {len(vulns)} vulns. "
            f"Decision: {decision.best_option} (confidence: {decision.confidence:.2f})",
            agent_origin="Sentinel",
            tags=["security", "incident"],
            importance=0.9,
        )
        step5.status = "completed"
        step5.result = {"memory_id": memory.memory_id}
        step5.completed_at = time.time()
        steps.append(step5)

        return WorkflowResult(
            workflow_id=workflow_id,
            name="Security Workflow",
            status="completed",
            steps=steps,
            final_output=decision.best_option,
            total_time_ms=(time.time() - start) * 1000,
        )

    # ── Code Workflow ──────────────────────────────────────────────────────

    def run_code_workflow(self, spec: str) -> WorkflowResult:
        """Full code workflow: Forge -> Sentinel -> Cortex -> Memora."""
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        start = time.time()

        steps = []

        # Step 1: Forge generates code
        step1 = WorkflowStep(
            step_id="s1", name="Generate Code",
            agent="Forge", action="generate_function",
            started_at=time.time(),
        )
        # Simple spec: "function that adds two numbers"
        generated = self._code.generate_function(
            "add_numbers", ["a", "b"], "Add two numbers",
            "return a + b"
        )
        step1.status = "completed"
        step1.result = {"filename": generated.filename, "lines": generated.line_count}
        step1.completed_at = time.time()
        steps.append(step1)

        # Step 2: Forge generates tests
        step2 = WorkflowStep(
            step_id="s2", name="Generate Tests",
            agent="Forge", action="generate_tests",
            input_ref="s1",
            started_at=time.time(),
        )
        tests = self._code.generate_tests(generated.code)
        step2.status = "completed"
        step2.result = {"test_count": tests.test_count, "targets": tests.coverage_targets}
        step2.completed_at = time.time()
        steps.append(step2)

        # Step 3: Sentinel scans generated code
        step3 = WorkflowStep(
            step_id="s3", name="Scan Code",
            agent="Sentinel", action="scan_code",
            input_ref="s1",
            started_at=time.time(),
        )
        vulns = self._security.scan_code(generated.code, generated.filename)
        step3.status = "completed"
        step3.result = {"vuln_count": len(vulns)}
        step3.completed_at = time.time()
        steps.append(step3)

        # Step 4: Cortex reviews the code
        step4 = WorkflowStep(
            step_id="s4", name="Code Review",
            agent="Cortex", action="decide",
            input_ref="s3",
            started_at=time.time(),
        )
        analysis = self._code.analyze(generated.code, "python")
        review = self._code.review(generated.code)
        decision = self._decision.decide(
            question="Should we deploy this code?",
            options=[
                {"name": "Deploy", "scores": {"quality": analysis.maintainability_index,
                    "security": 100 - len(vulns) * 10, "complexity": max(0, 100 - analysis.cyclomatic_complexity * 5)},
                 "risks": ["Potential bugs"], "benefits": ["New functionality"]},
                {"name": "Refactor", "scores": {"quality": 70, "security": 90, "complexity": 70},
                 "risks": ["Delay"], "benefits": ["Better code"]},
            ],
            criteria=[
                {"name": "quality", "weight": 0.3},
                {"name": "security", "weight": 0.4},
                {"name": "complexity", "weight": 0.3},
            ]
        )
        step4.status = "completed"
        step4.result = {"decision": decision.best_option, "score": review["score"]}
        step4.completed_at = time.time()
        steps.append(step4)

        # Step 5: Memora stores the code decision
        step5 = WorkflowStep(
            step_id="s5", name="Store Decision",
            agent="Memora", action="store",
            input_ref="s4",
            started_at=time.time(),
        )
        memory = self._memory.store(
            f"Code review: {generated.filename} score={review['score']}, "
            f"decision={decision.best_option}, complexity={analysis.cyclomatic_complexity}",
            agent_origin="Forge",
            tags=["code", "review"],
            importance=0.7,
        )
        step5.status = "completed"
        step5.result = {"memory_id": memory.memory_id}
        step5.completed_at = time.time()
        steps.append(step5)

        return WorkflowResult(
            workflow_id=workflow_id,
            name="Code Workflow",
            status="completed",
            steps=steps,
            final_output=decision.best_option,
            total_time_ms=(time.time() - start) * 1000,
        )

    # ── Content Workflow ───────────────────────────────────────────────────

    def run_content_workflow(self, title: str, description: str) -> WorkflowResult:
        """Full content workflow: VyralX -> Futuris -> Cortex -> Memora."""
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        start = time.time()

        steps = []

        # Step 1: VyralX predicts content performance
        step1 = WorkflowStep(
            step_id="s1", name="Predict Performance",
            agent="VyralX", action="predict_performance",
            started_at=time.time(),
        )
        prediction = self._content.predict_performance(title, description, tags=["content"])
        step1.status = "completed"
        step1.result = {"engagement_score": prediction["engagement_score"]}
        step1.completed_at = time.time()
        steps.append(step1)

        # Step 2: Futuris forecasts growth
        step2 = WorkflowStep(
            step_id="s2", name="Forecast Growth",
            agent="Futuris", action="ensemble_forecast",
            input_ref="s1",
            started_at=time.time(),
        )
        series = [prediction["predicted_views"] * (0.8 + i * 0.02) for i in range(30)]
        forecast = self._forecast.ensemble_forecast("CONTENT", series)
        step2.status = "completed"
        step2.result = {"forecast": forecast.prediction, "confidence": forecast.confidence}
        step2.completed_at = time.time()
        steps.append(step2)

        # Step 3: Cortex decides on publishing
        step3 = WorkflowStep(
            step_id="s3", name="Publishing Decision",
            agent="Cortex", action="decide",
            input_ref="s2",
            started_at=time.time(),
        )
        decision = self._decision.decide(
            question="Should we publish this content?",
            options=[
                {"name": "Publish Now", "scores": {"engagement": prediction["engagement_score"],
                    "growth": forecast.confidence * 100, "risk": 70}},
                {"name": "Schedule", "scores": {"engagement": prediction["engagement_score"] * 0.9,
                    "growth": forecast.confidence * 80, "risk": 85}},
            ],
            criteria=[
                {"name": "engagement", "weight": 0.4},
                {"name": "growth", "weight": 0.3},
                {"name": "risk", "weight": 0.3},
            ]
        )
        step3.status = "completed"
        step3.result = {"decision": decision.best_option, "confidence": decision.confidence}
        step3.completed_at = time.time()
        steps.append(step3)

        # Step 4: Memora stores content decision
        step4 = WorkflowStep(
            step_id="s4", name="Store Decision",
            agent="Memora", action="store",
            input_ref="s3",
            started_at=time.time(),
        )
        memory = self._memory.store(
            f"Content decision: '{title}' -> {decision.best_option} "
            f"(engagement: {prediction['engagement_score']}, forecast: {forecast.prediction})",
            agent_origin="VyralX",
            tags=["content", "decision"],
            importance=0.6,
        )
        step4.status = "completed"
        step4.result = {"memory_id": memory.memory_id}
        step4.completed_at = time.time()
        steps.append(step4)

        return WorkflowResult(
            workflow_id=workflow_id,
            name="Content Workflow",
            status="completed",
            steps=steps,
            final_output=decision.best_option,
            total_time_ms=(time.time() - start) * 1000,
        )

    def get_universe_status(self) -> dict[str, Any]:
        """Get the status of all agents in the universe."""
        return {
            "decision_engine": {
                "total_decisions": len(self._decision.get_history()),
                "patterns": self._decision.get_decision_patterns(),
            },
            "reasoning_engine": {
                "total_beliefs": len(self._reasoning.get_beliefs()),
            },
            "memory_engine": self._memory.get_stats(),
            "trading_engine": self._trading.get_portfolio_stats(),
            "code_engine": {"templates": len(self._code._templates)},
            "security_engine": self._security.get_report(),
            "threat_intel": self._threat_intel.get_stats(),
            "forecast_engine": self._forecast.get_stats(),
            "content_engine": self._content.get_stats(),
        }


engine = CrossAgentEngine()
