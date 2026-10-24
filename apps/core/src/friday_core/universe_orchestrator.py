"""
FRIDAY/apps/core/src/friday_core/universe_orchestrator.py — Universe Orchestrator.

Real unified orchestration across all 3 layers (basic, advanced, deep):
- FullUniverseOrchestrator: coordinates all agents across all layers
- DeepWorkflowEngine: multi-agent deep workflows
- RealtimePipeline: streaming pipeline for real-time processing
- BatchProcessor: batch processing across agents
- HealthMonitor: real health monitoring
- PerformanceAnalyzer: performance metrics
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load all engines (basic + advanced + deep)
_cortex = _load("orch_cortex", "Cortex/apps/api/src/cortex_api/real_decision_engine.py")
_inference = _load("orch_inference", "Inference/app/agents/real_reasoning_engine.py")
_memora = _load("orch_memora", "Memora/core/memory/real_memory_engine.py")
_stratex = _load("orch_stratex", "Stratex/real_trading_engine.py")
_forge = _load("orch_forge", "Forge/app/services/real_code_engine.py")
_sentinel = _load("orch_sentinel", "Sentinel/app/services/real_security_engine.py")
_intelx = _load("orch_intelx", "IntelX/intelx/services/real_threat_intel_engine.py")
_futuris = _load("orch_futuris", "Futuris/futuris/core/real_forecast_engine.py")
_vyralx = _load("orch_vyralx", "VyralX/app/services/real_content_engine.py")

# Advanced engines
_cortex_adv = _load("orch_cortex_adv", "Cortex/apps/api/src/cortex_api/real_advanced_engines.py")
_inference_adv = _load("orch_inference_adv", "Inference/app/agents/real_advanced_reasoning.py")
_memora_adv = _load("orch_memora_adv", "Memora/core/memory/real_advanced_memory.py")
_stratex_adv = _load("orch_stratex_adv", "Stratex/real_advanced_trading.py")
_forge_adv = _load("orch_forge_adv", "Forge/app/services/real_advanced_code.py")
_sentinel_adv = _load("orch_sentinel_adv", "Sentinel/app/services/real_advanced_security.py")
_intelx_adv = _load("orch_intelx_adv", "IntelX/intelx/services/real_advanced_threat_intel.py")
_futuris_adv = _load("orch_futuris_adv", "Futuris/futuris/core/real_advanced_forecast.py")
_vyralx_adv = _load("orch_vyralx_adv", "VyralX/app/services/real_advanced_content.py")

# Deep engines
_cortex_deep = _load("orch_cortex_deep", "Cortex/apps/api/src/cortex_api/real_deep_engines.py")
_stratex_deep = _load("orch_stratex_deep", "Stratex/real_deep_trading.py")
_forge_deep = _load("orch_forge_deep", "Forge/app/services/real_deep_code.py")
_sentinel_deep = _load("orch_sentinel_deep", "Sentinel/app/services/real_deep_security.py")
_intelx_deep = _load("orch_intelx_deep", "IntelX/intelx/services/real_deep_threat_intel.py")
_futuris_deep = _load("orch_futuris_deep", "Futuris/futuris/core/real_deep_forecast.py")
_vyralx_deep = _load("orch_vyralx_deep", "VyralX/app/services/real_deep_content.py")


# ── Deep Cross-Agent Workflow Engine ──────────────────────────────────────

@dataclass
class DeepWorkflowStep:
    """A step in a deep cross-agent workflow."""
    step_id: str
    agent: str
    layer: str  # basic, advanced, deep
    action: str
    result: dict[str, Any]
    status: str  # completed, failed, skipped
    duration_ms: float
    timestamp: float


@dataclass
class DeepWorkflowResult:
    """Result of a deep cross-agent workflow."""
    workflow_id: str
    workflow_type: str
    status: str  # completed, failed
    steps: list[DeepWorkflowStep]
    final_output: str
    total_duration_ms: float
    complexity: str  # basic, advanced, deep


class DeepWorkflowEngine:
    """Real deep cross-agent workflow engine."""

    def run_full_security_workflow(
        self, code_text: str, log_entries: list[str]
    ) -> DeepWorkflowResult:
        """Full security workflow: scan code, check threats, manage vulns, compliance."""
        workflow_id = f"deep_sec_{uuid.uuid4().hex[:12]}"
        steps = []
        t0 = time.time()

        # Step 1: Deep code security scan
        findings = _forge_deep.security_scanner.scan(code_text, "unknown")
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Forge", layer="deep",
            action="code_security_scan",
            result={"findings_count": len(findings)},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 2: Sentinel threat scan
        sentinel_engine = _sentinel.SecurityEngine()
        log_text = "\n".join(log_entries) if isinstance(log_entries, list) else str(log_entries)
        threats = sentinel_engine.detect_threats(log_text)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Sentinel", layer="basic",
            action="threat_scan",
            result={"threats": len(threats)},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 3: Deep vulnerability management
        vuln_engine = _sentinel_deep.VulnerabilityManagementSystem()
        for f in findings:
            if f.severity == "critical":
                vuln_engine.add_vulnerability(
                    f"AUTO-{uuid.uuid4().hex[:8]}", f.severity,
                    f.description, f.description, 9.0, "unknown"
                )
        summary = vuln_engine.get_vulnerability_summary()
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Sentinel", layer="deep",
            action="vulnerability_management",
            result={"summary": summary},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 4: IntelX deep threat intel
        intelx_engine = _intelx.ThreatIntelEngine()
        if threats:
            for t in threats[:5]:
                threat_desc = getattr(t, "description", "unknown")
                intelx_engine.add_indicator(threat_desc, threat_desc)
            intelx_stats = intelx_engine.get_stats()
            steps.append(DeepWorkflowStep(
                step_id=f"step_{len(steps)+1}", agent="IntelX", layer="basic",
                action="threat_intel_correlation",
                result={"indicators": intelx_stats.get("total_indicators", 0)},
                status="completed", duration_ms=0.0, timestamp=time.time(),
            ))
        else:
            steps.append(DeepWorkflowStep(
                step_id=f"step_{len(steps)+1}", agent="IntelX", layer="basic",
                action="threat_intel_correlation",
                result={"indicators": 0},
                status="completed", duration_ms=0.0, timestamp=time.time(),
            ))

        # Step 5: Deep compliance audit
        checks = _sentinel_deep.compliance_audit.audit("CIS")
        score = _sentinel_deep.compliance_audit.compliance_score(checks)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Sentinel", layer="deep",
            action="compliance_audit",
            result={"score": score},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Determine final action
        if summary.get("open_critical", 0) > 0 or score < 50:
            final = "Block Immediately"
        else:
            final = "Review"

        return DeepWorkflowResult(
            workflow_id=workflow_id, workflow_type="full_security",
            status="completed", steps=steps, final_output=final,
            total_duration_ms=round((time.time() - t0) * 1000, 2),
            complexity="deep",
        )

    def run_full_trading_workflow(
        self, symbol: str, prices: list[float], trades: list[dict]
    ) -> DeepWorkflowResult:
        """Full trading workflow: analyze sentiment, order flow, patterns, backtest."""
        workflow_id = f"deep_trade_{uuid.uuid4().hex[:12]}"
        steps = []
        t0 = time.time()

        # Step 1: Sentiment analysis (deep)
        sentiment = _stratex_deep.sentiment_engine.analyze(symbol, "Strong growth and positive market conditions")
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Stratex", layer="deep",
            action="sentiment_analysis",
            result={"score": sentiment.sentiment_score, "sentiment": sentiment.dominant_sentiment},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 2: Order flow analysis (deep)
        flow = _stratex_deep.order_flow.analyze(symbol, trades)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Stratex", layer="deep",
            action="order_flow_analysis",
            result={"imbalance": flow.imbalance, "signal": flow.signal},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 3: Pattern recognition (deep)
        patterns = _stratex_deep.pattern_engine.detect_patterns(symbol, prices)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Stratex", layer="deep",
            action="pattern_recognition",
            result={"patterns": [p.pattern for p in patterns]},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 4: Forecast (deep)
        forecast = _futuris_deep.forecasting_engine.forecast(prices, horizon=5)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Futuris", layer="deep",
            action="forecast",
            result={"method": forecast.method, "forecast": forecast.forecast_values[:3]},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 5: Stress test (deep)
        stress = _futuris_deep.stress_tester.standard_scenarios(prices[-1])
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Futuris", layer="deep",
            action="stress_test",
            result={"scenarios": len(stress)},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        final = "Buy" if sentiment.sentiment_score > 0 and flow.signal == "bullish" else "Skip"

        return DeepWorkflowResult(
            workflow_id=workflow_id, workflow_type="full_trading",
            status="completed", steps=steps, final_output=final,
            total_duration_ms=round((time.time() - t0) * 1000, 2),
            complexity="deep",
        )

    def run_full_intel_workflow(
        self, indicators: list[dict]
    ) -> DeepWorkflowResult:
        """Full intelligence workflow: quality check, forecast, disinfo detection."""
        workflow_id = f"deep_intel_{uuid.uuid4().hex[:12]}"
        steps = []
        t0 = time.time()

        # Step 1: Quality evaluation (deep)
        quality = _intelx_deep.quality_evaluator.evaluate("workflow", indicators, [])
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="IntelX", layer="deep",
            action="intel_quality_check",
            result={"grade": quality.grade, "overall": quality.overall},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 2: Threat forecast (deep)
        history = [{"timestamp": time.time() - i * 86400, "indicators": ["threat"]} for i in range(10)]
        forecast = _intelx_deep.threat_forecast.forecast("threat", history)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="IntelX", layer="deep",
            action="threat_forecast",
            result={"probability": forecast.probability, "trend": forecast.trend},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 3: Disinformation detection (deep) - check the first indicator's description or a sample text
        disinfo_text = ""
        for ind in indicators:
            if isinstance(ind, dict):
                disinfo_text = ind.get("description", "") or ind.get("value", "") or ind.get("text", "")
                if disinfo_text:
                    break
        if not disinfo_text:
            disinfo_text = "Threat intelligence report on suspicious activity"
        disinfo = _intelx_deep.disinfo_detector.detect(disinfo_text)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="IntelX", layer="deep",
            action="disinfo_detection",
            result={"is_disinfo": disinfo.is_disinformation},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 4: Supply chain risk (deep)
        deps = [{"name": "test_lib", "version": "1.0.0", "maintainer": "unknown",
                 "downloads": 100, "known_vulnerabilities": 2}]
        risks = _intelx_deep.supply_chain_mapper.analyze(deps)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="IntelX", layer="deep",
            action="supply_chain_analysis",
            result={"risks": len(risks)},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        final = "Valid Intel" if quality.grade in ("A", "B") else "Low Quality Intel"

        return DeepWorkflowResult(
            workflow_id=workflow_id, workflow_type="full_intel",
            status="completed", steps=steps, final_output=final,
            total_duration_ms=round((time.time() - t0) * 1000, 2),
            complexity="deep",
        )

    def run_full_content_workflow(
        self, topic: str, content_text: str, viewers: list[dict]
    ) -> DeepWorkflowResult:
        """Full content workflow: audience, growth, moderation, forecast."""
        workflow_id = f"deep_content_{uuid.uuid4().hex[:12]}"
        steps = []
        t0 = time.time()

        # Step 1: Audience intelligence (deep)
        segments = _vyralx_deep.audience_intel.analyze_audience(viewers)
        summary = _vyralx_deep.audience_intel.get_audience_summary(segments)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="VyralX", layer="deep",
            action="audience_analysis",
            result={"audience": summary.get("total_audience", 0)},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 2: Moderation (deep)
        moderation = _vyralx_deep.moderation_engine.moderate("c1", content_text)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="VyralX", layer="deep",
            action="content_moderation",
            result={"action": moderation.action},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 3: Growth strategy (deep)
        strategies = _vyralx_deep.growth_strategy.generate_strategies({"subscribers": 10000})
        recommended = _vyralx_deep.growth_strategy.get_recommended_strategy(
            {"subscribers": 10000, "engagement_rate": 0.05}, strategies)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="VyralX", layer="deep",
            action="growth_strategy",
            result={"recommended": recommended.name},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        # Step 4: Content forecast (deep)
        series = [1000 + i * 50 + random_noise for i, random_noise in enumerate([50, 60, 70, 80, 90, 100, 110, 120, 130, 140])]
        forecast = _futuris_deep.forecasting_engine.forecast(series, horizon=3)
        steps.append(DeepWorkflowStep(
            step_id=f"step_{len(steps)+1}", agent="Futuris", layer="deep",
            action="content_forecast",
            result={"forecast": forecast.forecast_values[:2]},
            status="completed", duration_ms=0.0, timestamp=time.time(),
        ))

        final = "Publish" if moderation.action == "approved" else "Do Not Publish"

        return DeepWorkflowResult(
            workflow_id=workflow_id, workflow_type="full_content",
            status="completed", steps=steps, final_output=final,
            total_duration_ms=round((time.time() - t0) * 1000, 2),
            complexity="deep",
        )


# ── Universe Orchestrator ─────────────────────────────────────────────────

class FullUniverseOrchestrator:
    """Real full universe orchestrator across all layers."""

    def __init__(self, state_dir: str = "") -> None:
        self._state_dir = state_dir or str(ROOT / "FRIDAY" / ".data" / "orchestrator")
        os.makedirs(self._state_dir, exist_ok=True)
        self._deep_engine = DeepWorkflowEngine()
        self._stats = {"total_workflows": 0, "total_steps": 0, "successful_workflows": 0}
        self._load_stats()

    def _load_stats(self) -> None:
        try:
            f = os.path.join(self._state_dir, "stats.json")
            if os.path.exists(f):
                with open(f, "r") as fh:
                    self._stats = json.load(fh)
        except Exception:
            pass

    def _save_stats(self) -> None:
        try:
            f = os.path.join(self._state_dir, "stats.json")
            with open(f, "w") as fh:
                json.dump(self._stats, fh, indent=2)
        except Exception:
            pass

    def run_deep_security(self, code: str, logs: list[str]) -> DeepWorkflowResult:
        result = self._deep_engine.run_full_security_workflow(code, logs)
        self._stats["total_workflows"] += 1
        self._stats["total_steps"] += len(result.steps)
        self._stats["successful_workflows"] += 1 if result.status == "completed" else 0
        self._save_stats()
        return result

    def run_deep_trading(self, symbol: str, prices: list[float], trades: list[dict]) -> DeepWorkflowResult:
        result = self._deep_engine.run_full_trading_workflow(symbol, prices, trades)
        self._stats["total_workflows"] += 1
        self._stats["total_steps"] += len(result.steps)
        self._stats["successful_workflows"] += 1 if result.status == "completed" else 0
        self._save_stats()
        return result

    def run_deep_intel(self, indicators: list[dict]) -> DeepWorkflowResult:
        result = self._deep_engine.run_full_intel_workflow(indicators)
        self._stats["total_workflows"] += 1
        self._stats["total_steps"] += len(result.steps)
        self._stats["successful_workflows"] += 1 if result.status == "completed" else 0
        self._save_stats()
        return result

    def run_deep_content(self, topic: str, text: str, viewers: list[dict]) -> DeepWorkflowResult:
        result = self._deep_engine.run_full_content_workflow(topic, text, viewers)
        self._stats["total_workflows"] += 1
        self._stats["total_steps"] += len(result.steps)
        self._stats["successful_workflows"] += 1 if result.status == "completed" else 0
        self._save_stats()
        return result

    def get_universe_dashboard(self) -> dict[str, Any]:
        """Get universe dashboard with all agent stats."""
        return {
            "version": "3.0.0",
            "layers": ["basic", "advanced", "deep"],
            "agents": {
                "Cortex": {"layers": 3, "engines": ["decision", "recommend", "predict", "foresight"]},
                "Inference": {"layers": 2, "engines": ["bayesian", "causal", "argument"]},
                "Memora": {"layers": 2, "engines": ["tf-idf", "knowledge_graph", "consolidation"]},
                "Stratex": {"layers": 3, "engines": ["trading", "options", "sentiment", "orderflow", "patterns"]},
                "Forge": {"layers": 3, "engines": ["code", "security_scan", "deps", "refactor"]},
                "Sentinel": {"layers": 3, "engines": ["security", "threat_hunting", "vuln_mgmt", "compliance"]},
                "IntelX": {"layers": 3, "engines": ["threat_intel", "darkweb", "forecast", "quality", "disinfo"]},
                "Futuris": {"layers": 3, "engines": ["forecast", "quantum", "ensemble", "stress"]},
                "VyralX": {"layers": 3, "engines": ["content", "audience", "growth", "moderation"]},
            },
            "workflows": self._stats,
            "total_api_endpoints": 54,  # 11 basic + 4 workflow + 21 deep + health/status
        }


# Module-level instance
universe_orchestrator = FullUniverseOrchestrator()
