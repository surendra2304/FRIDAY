"""Trace Analyzer for FRIDAY Trace-Based Learning (Inspired by OpenJarvis).

Analyzes execution traces to discover tool efficiency patterns, evaluate provider reliability,
identify failing providers, and guide dynamic routing optimization.
"""

import re
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("learning.trace_analyzer")


class TraceAnalyzer:
    """Analyzes execution traces to optimize agent, tool, and provider routing."""

    def __init__(self, memory: Any | None = None) -> None:
        self.memory = memory

    def _get_memory(self) -> Any | None:
        if self.memory is not None:
            return self.memory
        try:
            from friday.core.config import get_settings
            from friday.memory.sqlite import SQLiteConversationMemory
            settings = get_settings()
            self.memory = SQLiteConversationMemory(db_path=settings.sqlite_db_path)
            return self.memory
        except Exception as e:
            logger.debug(f"Could not initialize memory in TraceAnalyzer: {e}")
            return None

    def get_tool_success_rates(
        self,
        goal_query: str | None = None,
        task_type: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Calculate empirical success rate and latency for each tool."""
        mem = self._get_memory()
        if mem is None or not hasattr(mem, "get_execution_traces"):
            return {}

        traces = mem.get_execution_traces(limit=500, goal_query=goal_query, task_type=task_type)
        stats: dict[str, dict[str, Any]] = {}

        for tr in traces:
            tools = tr.get("tools_used", [])
            success = tr.get("success", False)
            lat = tr.get("latency_ms", 0.0)

            for tool in tools:
                if tool not in stats:
                    stats[tool] = {"total": 0, "successes": 0, "failures": 0, "latencies": []}
                stats[tool]["total"] += 1
                if success:
                    stats[tool]["successes"] += 1
                else:
                    stats[tool]["failures"] += 1
                stats[tool]["latencies"].append(lat)

        result: dict[str, dict[str, Any]] = {}
        for tool, d in stats.items():
            tot = d["total"]
            succ = d["successes"]
            lats = d["latencies"]
            result[tool] = {
                "total": tot,
                "successes": succ,
                "failures": d["failures"],
                "success_rate": (succ / tot) if tot > 0 else 0.0,
                "avg_latency_ms": (sum(lats) / len(lats)) if lats else 0.0,
            }
        return result

    def get_provider_stats(self) -> dict[str, dict[str, Any]]:
        """Aggregate performance and failure metrics per provider."""
        mem = self._get_memory()
        if mem is None or not hasattr(mem, "get_execution_traces"):
            return {}

        traces = mem.get_execution_traces(limit=500)
        stats: dict[str, dict[str, Any]] = {}

        for tr in traces:
            prov = tr.get("provider", "default")
            success = tr.get("success", False)
            lat = tr.get("latency_ms", 0.0)

            if prov not in stats:
                stats[prov] = {"total": 0, "successes": 0, "failures": 0, "latencies": []}
            stats[prov]["total"] += 1
            if success:
                stats[prov]["successes"] += 1
            else:
                stats[prov]["failures"] += 1
            stats[prov]["latencies"].append(lat)

        result: dict[str, dict[str, Any]] = {}
        for prov, d in stats.items():
            tot = d["total"]
            succ = d["successes"]
            fails = d["failures"]
            lats = d["latencies"]
            result[prov] = {
                "total": tot,
                "successes": succ,
                "failures": fails,
                "success_rate": (succ / tot) if tot > 0 else 0.0,
                "failure_rate": (fails / tot) if tot > 0 else 0.0,
                "avg_latency_ms": (sum(lats) / len(lats)) if lats else 0.0,
            }
        return result

    def get_failing_providers(self, failure_threshold: float = 0.50, min_trials: int = 2) -> set[str]:
        """Identify unreliable providers exceeding failure threshold (e.g. 90% failure rate)."""
        prov_stats = self.get_provider_stats()
        failing: set[str] = set()

        for prov, s in prov_stats.items():
            if s["total"] >= min_trials and s["failure_rate"] >= failure_threshold:
                failing.add(prov)
        return failing

    def get_optimal_tool_and_provider(
        self,
        goal: str,
        available_tools: list[str] | None = None,
        max_latency_ms: float = 2000.0,
    ) -> dict[str, Any] | None:
        """Find high-performing tool and provider combinations historically successful in < 2s."""
        mem = self._get_memory()
        if mem is None or not hasattr(mem, "get_execution_traces"):
            return None

        # Look up similar goal traces
        tokens = [t.lower() for t in re.findall(r"\b\w{3,}\b", goal)]
        if not tokens:
            return None

        traces = mem.get_execution_traces(limit=200, success_only=True)
        matching_traces = []

        for tr in traces:
            tr_goal = (tr.get("goal") or "").lower()
            overlap = sum(1 for tok in tokens if tok in tr_goal)
            if overlap >= 1:
                matching_traces.append((overlap, tr))

        if not matching_traces:
            return None

        # Sort by overlap DESC, latency ASC
        matching_traces.sort(key=lambda item: (-item[0], item[1].get("latency_ms", 99999.0)))
        best_overlap, best_tr = matching_traces[0]

        tools = best_tr.get("tools_used", [])
        if available_tools and tools:
            # Check if preferred tool is available
            if not any(t in available_tools for t in tools):
                return None

        lat = best_tr.get("latency_ms", 0.0)
        prov = best_tr.get("provider", "default")
        preferred_tool = tools[0] if tools else None

        return {
            "preferred_tool": preferred_tool,
            "preferred_provider": prov,
            "historical_latency_ms": lat,
            "goal_match": best_tr.get("goal"),
            "fast_path": lat <= max_latency_ms,
        }

    def filter_and_rank_fallback_providers(self, candidate_providers: list[str]) -> list[str]:
        """Reorder fallback provider chain: high-success/low-latency first, de-prioritize high-failure providers to the bottom."""
        prov_stats = self.get_provider_stats()
        failing_providers = self.get_failing_providers(failure_threshold=0.50, min_trials=2)

        def provider_sort_key(p: str) -> tuple:
            is_failing = p in failing_providers
            s = prov_stats.get(p)
            if is_failing:
                fail_rate = s.get("failure_rate", 1.0) if s else 1.0
                return (2, fail_rate, 9999.0)
            elif s and s.get("total", 0) > 0:
                # Proven working provider: prioritized by success rate DESC (-success_rate), then latency ASC
                return (0, -s.get("success_rate", 1.0), s.get("avg_latency_ms", 1000.0))
            else:
                # Untried provider
                return (1, 0.0, 1000.0)

        return sorted(candidate_providers, key=provider_sort_key)
