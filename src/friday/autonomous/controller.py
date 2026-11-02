"""FRIDAY Autonomous Mode & Multi-Agent Orchestration Controller.

Provides:
1. Autonomous Mode State Management (enabled/standby, execution logs).
2. Autonomous Agent Control: Dispatches directives to the 9 FRIDAY Universe specialist
   agents (Inference, Stratex, IntelX, Futuris, Cortex, Forge, Sentinel, Memora, VyralX),
   verifies outputs, and handles multi-agent handoffs.
3. Autonomous Self-Healing & Auto-Repair: Proactively detects runtime errors, zombie
   processes, socket disconnects, or tool failures, and applies self-correction
   mechanisms without human intervention.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
    "vyralx": {
        "name": "VYRALX",
        "role": "Autonomous Video Production & Governed Distribution",
        "domain": [
            "video",
            "youtube",
            "render",
            "media",
            "upload",
            "thumbnail",
            "shorts",
            "script",
            "voiceover",
            "pexels",
        ],
    },
}

#: Per-peer action vocabulary for the universal task protocol. A peer that does
#: not recognise an action returns 4xx, which is not the same as refusing work.
_MESH_ACTION_BY_AGENT = {
    "memora": "store",         # Memora accepts store/query only
    "stratex": "status",       # "execute" is reserved for Stratex's own trading loop
    "cortex": "health_summary",  # "execute" would attempt a live website change
}

_STATUS_INTENT = re.compile(
    r"\b(status|health|healthcheck|healthcheck|report|state|ping|alive|up)\b",
    re.IGNORECASE,
)
_STATUS_AWARE_AGENTS = {"forge", "sentinel", "futuris", "inference", "vyralx"}


def _mesh_action_for(agent_id: str, directive: str) -> str:
    """Pick the action a peer actually implements for this instruction.

    Sending every peer the literal action ``execute`` was wrong in both
    directions: agents whose protocol has no such verb answered 4xx, and agents
    that do treat ``execute`` as a live mutation were being asked to mutate
    production just to say hello. A status-shaped instruction becomes a status
    action on the peers that publish one; everything else stays ``execute``.
    """
    fixed = _MESH_ACTION_BY_AGENT.get(agent_id)
    if fixed:
        return fixed
    if agent_id in _STATUS_AWARE_AGENTS and _STATUS_INTENT.search(directive or ""):
        return "status"
    return "execute"


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

        self.action_history: list[AutonomousActionLog] = []
        self.active_directive: str | None = None
        self.active_agent: str | None = None
        self._max_history: int = 50
        self._repair_lock: asyncio.Lock = asyncio.Lock()
        # The dashboard's agent apartment renders per-agent activity from this
        # history, and the process is restarted on every deploy. Keeping it only
        # in memory meant the apartment was guaranteed to look empty right after
        # a release, which is exactly when someone looks at it.
        default_path = Path(__file__).resolve().parents[3] / ".data" / "autonomous_action_history.json"
        self._history_path = Path(os.getenv("FRIDAY_ACTION_HISTORY", str(default_path)))
        self._agent_activity: dict[str, dict[str, Any]] = {}
        self._load_history()
        self._initialized = True
        logger.info("FRIDAY AutonomousController initialized.")

    def _load_history(self) -> None:
        """Rehydrate the action log and per-agent activity from disk."""
        try:
            if not self._history_path.is_file():
                return
            with self._history_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # a corrupt log must never block startup
            logger.warning("Could not load action history from %s: %s", self._history_path, exc)
            return
        for raw in payload.get("actions", [])[-self._max_history:]:
            try:
                entry = AutonomousActionLog(
                    timestamp=str(raw.get("timestamp", "")),
                    action_type=str(raw.get("action_type", "")),
                    target=str(raw.get("target", "")),
                    directive=str(raw.get("directive", "")),
                    result=str(raw.get("result", "")),
                    success=bool(raw.get("success", False)),
                    details=raw.get("details") or {},
                )
            except Exception:
                continue
            self.action_history.append(entry)
        activity = payload.get("agent_activity")
        if isinstance(activity, dict):
            self._agent_activity = {
                str(k).lower(): v for k, v in activity.items() if isinstance(v, dict)
            }
        logger.info(
            "Restored %d autonomous actions and %d agent activity records",
            len(self.action_history),
            len(self._agent_activity),
        )

    def _persist_history(self) -> None:
        """Write the log atomically so a crash cannot truncate it."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "actions": [entry.__dict__ for entry in self.action_history],
                "agent_activity": self._agent_activity,
            }
            tmp = self._history_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, default=str)
            os.replace(tmp, self._history_path)
        except Exception as exc:
            logger.warning("Could not persist action history: %s", exc)

    @property
    def enabled(self) -> bool:
        """Read the same runtime setting used by the authorization boundary."""
        from friday.core.config import get_settings

        return bool(get_settings().autonomous_mode)

    @enabled.setter
    def enabled(self, state: bool) -> None:
        """Update the shared runtime setting used by status and authorization."""
        from friday.core.config import get_settings

        get_settings().autonomous_mode = bool(state)

    def is_autonomous(self) -> bool:
        """Check whether autonomous mode is active."""
        return self.enabled

    def toggle(self, state: bool | None = None) -> bool:
        """Toggle the shared autonomous-mode setting on or off."""
        self.enabled = not self.enabled if state is None else state
        logger.info("Autonomous Mode changed to: %s", self.enabled)
        return self.enabled

    def get_status(self) -> dict[str, Any]:
        """Return live execution modes, including what authorization still permits."""
        from friday.core.config import get_settings

        settings = get_settings()
        autonomous_mode = bool(settings.autonomous_mode)
        full_access_mode = bool(settings.full_access_mode)
        return {
            "autonomous_mode": autonomous_mode,
            "full_access_mode": full_access_mode,
            "sensitive_actions_auto_approved": autonomous_mode or full_access_mode,
            "autonomous_mode_persistence": "runtime_only",
            "active_agent": self.active_agent,
            "active_directive": self.active_directive,
            "history_count": len(self.action_history),
            "agent_activity": self._agent_activity,
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
        target_key = (target or "").strip().lower()
        if target_key:
            self._agent_activity[target_key] = {
                "timestamp": entry.timestamp,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "directive": directive[:400],
                "result": result[:400],
                "success": success,
                "action_type": action_type,
            }
        self._persist_history()

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
            r"^(?:friday\s*,?\s*)?(?:tell|have|make|command|control|ask|let|direct|instruct)\s+(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora|vyralx)\s+(?:to\s+|and\s+)?(?P<task>.+)$",
            r"^(?:friday\s*,?\s*)?(?:delegate\s+to\s+|dispatch\s+to\s+|route\s+to\s+)(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora|vyralx)\s+(?:to\s+|and\s+)?(?P<task>.+)$",
            r"^(?:friday\s*,?\s*)?(?:can\s+you\s+)?(?:get|use)\s+(?P<agent>inference|stratex|intelx|futuris|cortex|forge|sentinel|memora|vyralx)\s+(?:to\s+)?(?P<task>.+)$",
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

    def _get_peer_mesh(self) -> Any:
        """Lazily build the verified task mesh from the live fleet configuration."""
        mesh = getattr(self, "_peer_mesh", None)
        if mesh is None:
            from friday.cognition.mesh import Mesh, build_contracts

            mesh = Mesh(contracts=build_contracts(fleet_client))
            self._peer_mesh = mesh
        return mesh

    async def execute_agent_control(self, agent_id: str, directive: str) -> dict[str, Any]:
        """Dispatch a typed peer task and report only receipt-verified completion."""
        self.active_agent = agent_id.upper()
        self.active_directive = directive
        start_time = time.time()
        agent_id = agent_id.lower().strip()
        agent_meta = FLEET_AGENTS.get(agent_id, {"name": agent_id.upper(), "role": "Specialist Agent"})
        agent_name = agent_meta["name"]

        logger.info("[AUTONOMOUS DISPATCH] Sending typed task to %s: %r", agent_name, directive)

        try:
            from friday.cognition.mesh import OutcomeState

            mesh = self._get_peer_mesh()
            # Each peer publishes its own action vocabulary, and an action it does
            # not recognise is not the same thing as refusing the work. Memora's
            # universal protocol accepts only store/query ("execute" is a 422), and
            # Stratex correctly rejects "execute" as an attempt to command order
            # placement -- its supervisory action for a dispatched instruction is
            # "status". Everything else takes the generic "execute".
            mesh_action = _mesh_action_for(agent_id, directive)
            envelope = mesh.build_envelope(
                agent_id,
                action=mesh_action,
                objective=directive,
                inputs={
                    "directive": directive,
                    "content": directive,
                    "text": directive,
                    "query": directive,
                },
                capability=f"{agent_id}.execute",
                actor="friday",
                trust_level="operator_confirmed",
            )
            outcome = await mesh.dispatch(
                agent_id,
                action=mesh_action,
                envelope=envelope,
                attempts=1,
            )
            duration_ms = int((time.time() - start_time) * 1000)
            peer_result = outcome.result if isinstance(outcome.result, dict) else {}
            summary = str(peer_result.get("summary") or peer_result.get("message") or "").strip()
            verified = outcome.state is OutcomeState.COMPLETED
            task_state = outcome.state.value

            if verified:
                reply = f"[AGENT TASK VERIFIED: {agent_name}]\n{summary or outcome.detail}"
            elif outcome.state is OutcomeState.PENDING:
                reply = (
                    f"[AGENT TASK PENDING: {agent_name}]\n{outcome.detail} "
                    f"Task reference: {outcome.task_id}. Completion remains unverified."
                )
            else:
                # The mesh contract did not produce a verifiable receipt. Rather
                # than tell the owner "not verified" and stop, fall back to the
                # agent's own live endpoint through the fleet client, which is the
                # same call `/api/command` uses. The reply is then the peer's real
                # answer, labelled as a live response rather than a receipt.
                fallback = getattr(fleet_client, f"ask_{agent_id}", None)
                if callable(fallback):
                    try:
                        fallback_result = await fallback(directive)
                        fallback_reply = str(fallback_result.get("reply") or "").strip()
                        if fallback_reply:
                            reply = (
                                f"[{agent_name} LIVE RESPONSE]\n{fallback_reply}\n"
                                f"(mesh receipt unavailable: {outcome.detail})"
                            )
                            verified = False
                        else:
                            reply = f"[AGENT TASK NOT VERIFIED: {agent_name}]\n{outcome.detail}"
                    except Exception as exc:
                        reply = (
                            f"[AGENT TASK NOT VERIFIED: {agent_name}]\n{outcome.detail}\n"
                            f"Live fallback also failed: {exc}"
                        )
                else:
                    reply = f"[AGENT TASK NOT VERIFIED: {agent_name}]\n{outcome.detail}"

            self._log_action(
                action_type="AGENT_CONTROL",
                target=agent_name,
                directive=directive,
                result=reply,
                success=verified,
                details={
                    "latency_ms": duration_ms,
                    "task_state": task_state,
                    "task_id": outcome.task_id,
                    "http_status": outcome.http_status,
                    "contract_used": outcome.contract_used,
                    "task_completion_verified": verified,
                },
            )

            metadata: dict[str, Any] = {
                "autonomous": True,
                "agent": agent_id,
                "agent_name": agent_name,
                "latency_ms": duration_ms,
                "success": verified,
                "endpoint_response_received": outcome.http_status is not None,
                "task_completion_verified": verified,
                "task_state": task_state,
                "task_id": outcome.task_id,
                "http_status": outcome.http_status,
                "contract_used": outcome.contract_used,
            }
            receipt = peer_result.get("receipt")
            if receipt is not None:
                metadata["receipt"] = receipt
            task_result = peer_result.get("result")
            if task_result is not None:
                metadata["task_result"] = task_result
            if summary:
                metadata["task_summary"] = summary
            if outcome.state is OutcomeState.REFUSED:
                metadata["refused"] = True
            elif outcome.state is not OutcomeState.COMPLETED and outcome.state is not OutcomeState.PENDING:
                metadata["error"] = outcome.detail

            self.active_agent = None
            self.active_directive = None
            # Inter-agent fabric: mirror the outcome into Memora so other agents
            # (and the dashboard) can recall what happened. Best-effort; never
            # fail the task because memory persistence failed.
            try:
                from friday.memory.memora_client import memora_client
                memora_client.record_fact(
                    agent_name="friday",
                    fact_text=f"{agent_name} executed '{directive[:120]}' -> {task_state} ({reply[:200]})",
                    category="agent_task",
                    importance=0.6,
                )
            except Exception as mirror_exc:
                logger.debug("Memora mirror failed (non-fatal): %s", mirror_exc)
            return {"reply": reply, "metadata": metadata}

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error("[AUTONOMOUS CONTROL ERROR] Failed task dispatch to %s: %s", agent_name, exc)
            self._log_action(
                action_type="AGENT_CONTROL",
                target=agent_name,
                directive=directive,
                result=str(exc),
                success=False,
                details={"latency_ms": duration_ms, "task_state": "ERROR", "task_completion_verified": False},
            )
            self.active_agent = None
            self.active_directive = None
            return {
                "reply": f"Autonomous task to {agent_name} could not be verified: {exc}",
                "metadata": {
                    "autonomous": True,
                    "agent": agent_id,
                    "agent_name": agent_name,
                    "latency_ms": duration_ms,
                    "success": False,
                    "task_completion_verified": False,
                    "task_state": "ERROR",
                    "error": str(exc),
                },
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
                # A peer that never answered must not be counted as an answer.
                # The probes used to report a connection error as DEGRADED, so
                # eight unreachable peers produced {"status": "OBSERVED",
                # "responses": 8}: the evidence said the opposite of the truth.
                responded = [item for item in fleet_statuses if str(item.status).upper() != "UNREACHABLE"]
                unreachable = [item for item in fleet_statuses if str(item.status).upper() == "UNREACHABLE"]
                checks.append({
                    "name": "peer_health_endpoints",
                    "status": "OBSERVED" if responded else "UNAVAILABLE",
                    "evidence": {
                        "responded": len(responded),
                        "unreachable": len(unreachable),
                        "unreachable_peers": sorted(str(item.id) for item in unreachable),
                        "status_counts": counts,
                        "scope": "HTTP health/status endpoint responses only; task execution and inter-agent delivery are not verified.",
                    },
                })
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
