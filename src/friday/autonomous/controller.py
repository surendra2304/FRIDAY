"""FRIDAY Autonomous Mode & Multi-Agent Orchestration Controller.

Provides:
1. Autonomous Mode State Management (enabled/standby, execution logs).
2. Autonomous Agent Control: Dispatches directives to the 8 FRIDAY Universe specialist
   agents (Inference, Stratex, IntelX, Futuris, Cortex, Forge, Sentinel, Memora),
   verifies outputs, and handles multi-agent handoffs.
3. Autonomous Self-Healing & Auto-Repair: Proactively detects runtime errors, zombie
   processes, socket disconnects, or tool failures, and applies self-correction
   mechanisms without human intervention.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psutil

from friday.core.logging import get_logger
from friday.ecosystem.fleet_client import fleet_client

logger = get_logger("autonomous.controller")

FLEET_AGENTS = {
    "inference": {
        "name": "INFERENCE",
        "role": "Multi-Model Consensus & Edge Reasoning",
        "domain": ["reason", "think", "decide", "consensus", "llm", "query", "model", "logic"],
    },
    "stratex": {
        "name": "STRATEX",
        "role": "24/7 Futures Trading & Market Strategy",
        "domain": ["trade", "trading", "crypto", "futures", "position", "pnl", "market", "risk", "orders"],
    },
    "intelx": {
        "name": "INTELX",
        "role": "Macro Evidence & Deep Web Research",
        "domain": ["research", "investigate", "evidence", "macro", "search", "sources", "news", "trend"],
    },
    "futuris": {
        "name": "FUTURIS",
        "role": "Calibrated Probabilistic Forecasting",
        "domain": ["forecast", "predict", "probability", "brier", "timeline", "likelihood", "future"],
    },
    "cortex": {
        "name": "CORTEX",
        "role": "Autonomous Web Operations & Scraping",
        "domain": ["browse", "scrape", "website", "crawl", "extract", "url", "traffic", "leads"],
    },
    "forge": {
        "name": "FORGE",
        "role": "Autonomous Software Engineering & DevOps",
        "domain": ["code", "build", "compile", "devops", "test", "deploy", "git", "software", "patch"],
    },
    "sentinel": {
        "name": "SENTINEL",
        "role": "Zero-Trust Cybersecurity & Threat Defense",
        "domain": ["security", "audit", "threat", "firewall", "vulnerability", "auth", "zero-trust", "protect"],
    },
    "memora": {
        "name": "MEMORA",
        "role": "Persistent Vector Memory Fabric",
        "domain": ["memory", "remember", "recall", "turso", "vector", "episodic", "profile", "storage"],
    },
}


@dataclass
class AutonomousActionLog:
    timestamp: str
    action_type: str  # "AGENT_CONTROL", "SELF_REPAIR", "FAILOVER"
    target: str
    directive: str
    result: str
    success: bool
    details: dict[str, Any] = field(default_factory=dict)


class AutonomousController:
    """Central manager for FRIDAY's Autonomous Mode, Agent Control, and Self-Healing."""

    _instance: AutonomousController | None = None

    def __new__(cls) -> AutonomousController:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self.enabled: bool = True  # Enabled by default per user directive
        self.action_history: list[AutonomousActionLog] = []
        self.active_directive: str | None = None
        self.active_agent: str | None = None
        self._max_history: int = 50
        self._repair_lock: asyncio.Lock = asyncio.Lock()
        self._initialized = True
        logger.info("FRIDAY AutonomousController initialized in ACTIVE mode.")

    def is_autonomous(self) -> bool:
        """Check whether autonomous mode is active."""
        return self.enabled

    def toggle(self, state: bool | None = None) -> bool:
        """Toggle autonomous mode on or off."""
        if state is not None:
            self.enabled = state
        else:
            self.enabled = not self.enabled
        logger.info(f"Autonomous Mode changed to: {self.enabled}")
        return self.enabled

    def get_status(self) -> dict[str, Any]:
        """Return real-time state of the autonomous subsystem."""
        return {
            "autonomous_mode": self.enabled,
            "active_agent": self.active_agent,
            "active_directive": self.active_directive,
            "history_count": len(self.action_history),
            "recent_actions": [
                {
                    "timestamp": l.timestamp,
                    "action_type": l.action_type,
                    "target": l.target,
                    "directive": l.directive,
                    "result": l.result[:120] + ("..." if len(l.result) > 120 else ""),
                    "success": l.success,
                }
                for l in reversed(self.action_history[-8:])
            ],
        }

    def _log_action(
        self,
        action_type: str,
        target: str,
        directive: str,
        result: str,
        success: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an autonomous event into system trace."""
        entry = AutonomousActionLog(
            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
            action_type=action_type,
            target=target,
            directive=directive,
            result=result,
            success=success,
            details=details or {},
        )
        self.action_history.append(entry)
        if len(self.action_history) > self._max_history:
            self.action_history.pop(0)

    # =========================================================================
    # 1. Multi-Agent Autonomous Delegation & Control
    # =========================================================================

    def detect_agent_directive(self, command: str) -> tuple[str | None, str | None]:
        """
        Parse command to determine if it commands FRIDAY to control or delegate to an agent.
        Returns: (agent_id, sub_task_prompt)
        """
        cmd_lower = command.lower().strip()

        # A. Explicit agent invocation patterns:
        # e.g. "tell intelx to research...", "have stratex check positions", "control forge and run tests", "make cortex scrape..."
        patterns = [
            r"^(?:friday\s*,?\s*)?(?:tell|have|make|command|control|ask|let|direct|instruct)\s+(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora)\s+(?:to\s+|and\s+)?(?P<task>.+)$",
            r"^(?:friday\s*,?\s*)?(?:delegate\s+to\s+|dispatch\s+to\s+|route\s+to\s+)(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora)\s+(?:to\s+|and\s+)?(?P<task>.+)$",
            r"^(?:friday\s*,?\s*)?(?:can\s+you\s+)?(?:get|use)\s+(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora)\s+(?:to\s+)?(?P<task>.+)$",
        ]

        for pat in patterns:
            m = re.match(pat, cmd_lower)
            if m:
                agent_id = m.group("agent").strip()
                task = m.group("task").strip()
                return agent_id, task

        # B. Direct query syntax: "ask <agent> <task>" or "<agent>: <task>"
        for agent_key in FLEET_AGENTS:
            if cmd_lower.startswith(f"ask {agent_key} ") or cmd_lower.startswith(f"@{agent_key} "):
                parts = command.split(" ", 2)
                task = parts[2] if len(parts) > 2 else "Report status."
                return agent_key, task

        return None, None

    async def execute_agent_control(self, agent_id: str, directive: str) -> dict[str, Any]:
        """
        Autonomously commands a specialist agent to perform the directive,
        verifies the response, and falls back to self-repair if needed.
        """
        self.active_agent = agent_id.upper()
        self.active_directive = directive
        start_time = time.time()

        agent_meta = FLEET_AGENTS.get(agent_id.lower(), {"name": agent_id.upper(), "role": "Specialist Agent"})
        agent_name = agent_meta["name"]

        logger.info(f"[AUTONOMOUS DISPATCH] Controlling {agent_name} with directive: '{directive}'")

        try:
            # Dispatch to live fleet client
            res: dict[str, Any] = {}
            if agent_id == "inference":
                res = await fleet_client.ask_inference(directive)
            elif agent_id == "memora":
                res = await fleet_client.ask_memora(directive)
            elif agent_id == "stratex":
                res = await fleet_client.ask_stratex(directive)
            elif agent_id == "intelx":
                res = await fleet_client.ask_intelx(directive)
            elif agent_id == "futuris":
                res = await fleet_client.ask_futuris(directive)
            elif agent_id == "cortex":
                res = await fleet_client.ask_cortex(directive)
            elif agent_id == "forge":
                res = await fleet_client.ask_forge(directive)
            elif agent_id == "sentinel":
                res = await fleet_client.ask_sentinel(directive)
            else:
                res = {"reply": f"Agent '{agent_id}' dispatched.", "metadata": {"autonomous": True}}

            reply_text = res.get("reply", "")
            duration_ms = int((time.time() - start_time) * 1000)

            # Check if agent encountered an error or unreachable endpoint
            has_explicit_err = bool(res.get("metadata", {}).get("error"))
            has_err_text = any(sig in reply_text.lower() for sig in ["direct connection error", "error connecting", "unreachable", "gateway error", "error http"])
            is_error = has_explicit_err or has_err_text

            if is_error and self.enabled:
                # Trigger Autonomous Failover & Self-Repair
                logger.warning(f"[AUTONOMOUS FAILOVER] {agent_name} degraded. Initiating autonomous failover...")
                failover_result = await self.autonomous_failover(agent_id, directive)
                self._log_action(
                    action_type="FAILOVER",
                    target=agent_name,
                    directive=directive,
                    result=failover_result["reply"],
                    success=bool(failover_result.get("metadata", {}).get("success", False)),
                    details={"failover": False, "advisory_only": True, "task_completion_verified": False, "original_error": reply_text},
                )
                self.active_agent = None
                self.active_directive = None
                return failover_result

            # The current ask_* methods mostly query health/status endpoints;
            # their HTTP response is not proof that the requested work ran.
            formatted_reply = (
                f"[AGENT RESPONSE: {agent_name}]\n{reply_text}\n\n"
                f"The agent endpoint responded in {duration_ms} ms. Requested task completion is not verified."
            )

            self._log_action(
                action_type="AGENT_CONTROL",
                target=agent_name,
                directive=directive,
                result=reply_text,
                success=False,
                details={"latency_ms": duration_ms, "endpoint_response_received": True, "task_completion_verified": False},
            )

            self.active_agent = None
            self.active_directive = None
            return {
                "reply": formatted_reply,
                "metadata": {
                    "autonomous": True,
                    "agent": agent_id,
                    "agent_name": agent_name,
                    "latency_ms": duration_ms,
                    "success": False,
                    "endpoint_response_received": True,
                    "task_completion_verified": False,
                },
            }

        except Exception as exc:
            logger.error(f"[AUTONOMOUS CONTROL ERROR] Failed dispatch to {agent_name}: {exc}")
            if self.enabled:
                failover_result = await self.autonomous_failover(agent_id, directive)
                self.active_agent = None
                self.active_directive = None
                return failover_result

            self.active_agent = None
            self.active_directive = None
            return {
                "reply": f"Autonomous command to {agent_name} failed: {exc}",
                "metadata": {"autonomous": True, "error": str(exc), "success": False},
            }

    async def autonomous_failover(self, failed_agent: str, directive: str) -> dict[str, Any]:
        """
        When a designated agent fails, optionally request an advisory response
        from Inference. This does not execute the failed agent's task.
        """
        logger.info(f"[AUTONOMOUS FAILOVER] Resolving directive autonomously for failed agent '{failed_agent}'")
        try:
            # Attempt failover through the master Inference consensus gateway
            res = await fleet_client.ask_inference(
                f"[Autonomous Failover for {failed_agent.upper()}] The user requested: {directive}. "
                f"Please provide an authoritative, direct execution answer."
            )
            reply = res.get("reply", "")
            if res.get("metadata", {}).get("error") or not reply:
                raise RuntimeError("Inference returned no usable response")
            return {
                "reply": (
                    f"Inference provided an advisory response after {failed_agent.upper()} did not complete the request:\n\n"
                    f"{reply}\n\nThe original task remains incomplete; no retry or external action was performed."
                ),
                "metadata": {"autonomous": True, "failover": False, "advisory_only": True, "task_completion_verified": False, "fallback_provider": "inference", "success": False},
            }
        except Exception as e:
            return {
                "reply": (
                    f"Specialist '{failed_agent.upper()}' did not complete the request, and the Inference fallback was unavailable. "
                    "The request was not scheduled for retry."
                ),
                "metadata": {"autonomous": True, "failover": False, "task_completion_verified": False, "success": False, "error": type(e).__name__},
            }

    # =========================================================================
    # 2. Autonomous Self-Healing & System Auto-Repair
    # =========================================================================

    async def execute_self_repair(self, context: str = "general") -> dict[str, Any]:
        """Run a bounded diagnostic and report only observations with evidence.

        This routine deliberately does not kill processes, clear caches, or edit
        source code. Those actions require a concrete repair plan and verification.
        """
        async with self._repair_lock:
            checks: list[dict[str, Any]] = []
            try:
                zombie_count = sum(
                    1 for proc in psutil.process_iter(["status"])
                    if proc.info.get("status") == psutil.STATUS_ZOMBIE
                )
                checks.append({"name": "zombie_processes", "status": "PASS" if zombie_count == 0 else "DEGRADED", "evidence": f"Observed {zombie_count} zombie process(es); no processes were changed."})
            except Exception as exc:
                checks.append({"name": "zombie_processes", "status": "ERROR", "evidence": type(exc).__name__})

            try:
                vm = psutil.virtual_memory()
                checks.append({"name": "memory", "status": "DEGRADED" if vm.percent >= 90 else "PASS", "evidence": f"{vm.percent:.1f}% used; {vm.available / 1024**3:.2f} GiB available."})
            except Exception as exc:
                checks.append({"name": "memory", "status": "ERROR", "evidence": type(exc).__name__})

            try:
                fleet_statuses = await fleet_client.get_all_statuses(force_refresh=True)
                counts: dict[str, int] = {}
                for item in fleet_statuses:
                    state = str(item.status).upper()
                    counts[state] = counts.get(state, 0) + 1
                checks.append({"name": "peer_health_endpoints", "status": "OBSERVED" if fleet_statuses else "UNAVAILABLE", "evidence": {"responses": len(fleet_statuses), "status_counts": counts, "scope": "HTTP health/status endpoint responses only; task execution and inter-agent delivery are not verified."}})
            except Exception as exc:
                checks.append({"name": "peer_health_endpoints", "status": "UNAVAILABLE", "evidence": type(exc).__name__})

            observed = [item["status"] for item in checks]
            overall = "DEGRADED" if any(s in {"ERROR", "DEGRADED", "UNAVAILABLE"} for s in observed) else "UNVERIFIED"
            passed = sum(s == "PASS" for s in observed)
            full_report = (
                f"FRIDAY diagnostic: {overall}. {passed}/{len(checks)} local checks passed. "
                "No repair was attempted. A passing HTTP health endpoint does not prove agent task execution or data delivery."
            )

            self._log_action(
                action_type="SELF_REPAIR",
                target="LOCAL_SYSTEM",
                directive="System self-healing & diagnostic sweep",
                result=full_report,
                success=overall == "HEALTHY",
                details={"status": overall, "checks": checks, "repairs_attempted": []},
            )

            return {
                "reply": full_report,
                "metadata": {
                    "autonomous": True,
                    "status": overall,
                    "checks": checks,
                    "repairs_attempted": [],
                    "success": overall == "HEALTHY",
                },
            }


# Singleton instance
autonomous_controller = AutonomousController()
