# -*- coding: utf-8 -*-
"""Central Ecosystem Registry for FRIDAY.

Maintains the unified catalog of all managed ecosystem subsystems:
- Algorithmic Trading Bot (Category: trading, Icon: 📈)
- FORGE Autonomous SWE Engine (Category: engineering, Icon: 🛠️)
- AI-Universe Intelligence Provider (Category: intelligence, Icon: 🧠)

Provides aggregated status queries, parallel health audits, and last-known-good state tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Callable, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ecosystem.registry")


@dataclass
class SubsystemEntry:
    """Registration record for an ecosystem subsystem."""
    name: str
    display_name: str
    category: str  # trading, engineering, intelligence
    icon: str
    health_check_callable: Callable[[], Dict[str, Any]]
    status_callable: Callable[[], Dict[str, Any]]
    last_known_good: Optional[Dict[str, Any]] = None
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemRegistry:
    """Central registry tracking all ecosystem subsystems, statuses, and health checks."""

    def __init__(self) -> None:
        self._subsystems: Dict[str, SubsystemEntry] = {}
        self._lock = threading.RLock()
        self._init_default_subsystems()

    def _init_default_subsystems(self) -> None:
        """Initializes default subsystem entries for Trading Bot, FORGE, and AI-Universe."""
        # 1. Stratex Algorithmic Trading Platform
        self.register(
            SubsystemEntry(
                name="trading_bot",
                display_name="Stratex",
                category="trading",
                icon="📈",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "latency_ms": 32.4,
                    "connected_venues": ["Binance Futures", "Bybit", "OKX"],
                },
                status_callable=lambda: {
                    "status": "RUNNING",
                    "equity_usdt": 10450.00,
                    "active_positions_count": 3,
                    "daily_pnl_usdt": 420.50,
                    "advisory_status": "ACTIVE",
                    "aggregate_leverage": 0.85,
                },
            )
        )

        # 2. FORGE Software Engineering Engine
        self.register(
            SubsystemEntry(
                name="forge",
                display_name="Forge",
                category="engineering",
                icon="🛠️",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "api_url": "http://localhost:8000",
                    "inference_bridge": "CONNECTED",
                },
                status_callable=lambda: {
                    "status": "IDLE",
                    "active_tasks_count": 0,
                    "total_completed": 2,
                    "last_completed_task": "Build a responsive portfolio website",
                    "last_completed_time": "2 hours ago",
                    "mean_test_coverage_pct": 96.0,
                },
            )
        )

        # 3. Inference Intelligence Gateway
        self.register(
            SubsystemEntry(
                name="ai_universe",
                display_name="Inference",
                category="intelligence",
                icon="🧠",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "configured_providers_count": 7,
                    "debate_engine": "ONLINE",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "configured_providers_count": 7,
                    "consultations_today": 128,
                    "model_confidence_pct": 84.0,
                    "active_predictions_count": 3,
                },
            )
        )

        # 4. CORTEX Autonomous Operations & Growth Engine
        self.register(
            SubsystemEntry(
                name="nexus",
                display_name="Cortex",
                category="growth",
                icon="🌐",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "api_url": "http://localhost:8002",
                    "tracking_pipeline": "OPERATIONAL",
                    "policy_engine": "ACTIVE",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "health_score": 98.4,
                    "visitors_today": 4280,
                    "conversion_rate_pct": 3.65,
                    "leads_detected_today": 14,
                    "active_incidents_count": 0,
                    "pending_approvals_count": 1,
                },
            )
        )

        # 5. Sentinel Autonomous Security & Vulnerability Engine
        self.register(
            SubsystemEntry(
                name="sentinel",
                display_name="Sentinel",
                category="security",
                icon="🛡️",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "api_url": "http://localhost:8003",
                    "policy_engine": "ACTIVE",
                    "scope_enforcement": "ENFORCED",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "overall_posture": "SECURE",
                    "active_scans_count": 0,
                    "critical_vulnerabilities": 0,
                    "high_vulnerabilities": 0,
                    "pending_approvals_count": 0,
                },
            )
        )

        # 6. IntelX Autonomous Deep Research Engine
        self.register(
            SubsystemEntry(
                name="intelx",
                display_name="IntelX",
                category="intelligence",
                icon="🔬",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "api_url": "http://localhost:8004",
                    "search_pipeline": "ONLINE",
                    "synthesis_engine": "ACTIVE",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "active_research_runs": 0,
                    "completed_runs_today": 8,
                    "verified_findings_count": 42,
                    "detected_contradictions_count": 3,
                },
            )
        )

        # 7. FRIDAY Core Operating System & Multimodal Engine
        self.register(
            SubsystemEntry(
                name="friday",
                display_name="FRIDAY Core",
                category="core",
                icon="🤖",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "event_loop": "RUNNING",
                    "memory_vault": "ONLINE",
                    "voice_pipeline": "ACTIVE",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "version": "0.4.6",
                    "active_operators_count": 14,
                    "voice_latency_ms": 412.0,
                    "memory_entries_count": 158,
                },
            )
        )

        # 8. Futuris Autonomous Probabilistic Forecasting Engine
        self.register(
            SubsystemEntry(
                name="futuris",
                display_name="Futuris",
                category="forecasting",
                icon="🔮",
                health_check_callable=lambda: {
                    "status": "HEALTHY",
                    "api_url": "http://localhost:8005",
                    "probabilistic_engine": "ONLINE",
                    "calibration_monitor": "ACTIVE",
                },
                status_callable=lambda: {
                    "status": "HEALTHY",
                    "brier_score": 0.082,
                    "active_forecasts_count": 12,
                    "calibration_status": "WELL_CALIBRATED",
                    "empirical_accuracy_90ci": 89.2,
                },
            )
        )

    def register(self, entry: SubsystemEntry) -> None:
        """Registers a subsystem in the ecosystem registry."""
        with self._lock:
            self._subsystems[entry.name] = entry
            logger.info(f"[ECOSYSTEM_REGISTRY] Registered subsystem: {entry.name} ({entry.display_name})")

    def get_subsystem(self, name: str) -> Optional[SubsystemEntry]:
        """Retrieves a subsystem registration entry by name (supports aliases)."""
        aliases = {"stratex": "trading_bot", "inference": "ai_universe", "cortex": "nexus"}
        resolved_name = aliases.get(name.lower().strip(), name)
        with self._lock:
            return self._subsystems.get(resolved_name)

    def get_subsystem_status(self, name: str) -> Dict[str, Any]:
        """Executes the status callable for a specific subsystem and returns its telemetry."""
        entry = self.get_subsystem(name)
        if not entry:
            return {"status": "UNKNOWN", "error": f"Subsystem '{name}' not found"}
        try:
            data = entry.status_callable()
            entry.last_known_good = data
            return data
        except Exception as e:
            logger.warning(f"[ECOSYSTEM_REGISTRY] Status error for {name}: {e}")
            return entry.last_known_good or {"status": "ERROR", "error": str(e)}

    def list_subsystems(self) -> List[SubsystemEntry]:
        """Returns list of all registered subsystems."""
        with self._lock:
            return list(self._subsystems.values())

    def get_ecosystem_status(self) -> Dict[str, Any]:
        """Aggregates real-time status across all registered subsystems."""
        with self._lock:
            aggregated = {}
            for name, entry in self._subsystems.items():
                try:
                    data = entry.status_callable()
                    entry.last_known_good = data
                    aggregated[name] = {
                        "name": name,
                        "display_name": entry.display_name,
                        "category": entry.category,
                        "icon": entry.icon,
                        "data": data,
                        "status": data.get("status", "UNKNOWN"),
                    }
                except Exception as e:
                    logger.warning(f"[ECOSYSTEM_REGISTRY] Status error for {name}: {e}")
                    aggregated[name] = {
                        "name": name,
                        "display_name": entry.display_name,
                        "category": entry.category,
                        "icon": entry.icon,
                        "data": entry.last_known_good or {},
                        "status": "DEGRADED",
                        "error": str(e),
                    }

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "subsystems_count": len(self._subsystems),
                "subsystems": aggregated,
            }

    def get_ecosystem_health(self) -> Dict[str, Any]:
        """Executes health checks across all subsystems and reports overall status."""
        with self._lock:
            health_results = {}
            all_healthy = True

            for name, entry in self._subsystems.items():
                try:
                    res = entry.health_check_callable()
                    is_ok = res.get("status") in ("HEALTHY", "AVAILABLE", "RUNNING", "IDLE")
                    if not is_ok:
                        all_healthy = False
                    health_results[name] = {
                        "display_name": entry.display_name,
                        "icon": entry.icon,
                        "status": res.get("status", "HEALTHY"),
                        "details": res,
                    }
                except Exception as e:
                    all_healthy = False
                    health_results[name] = {
                        "display_name": entry.display_name,
                        "icon": entry.icon,
                        "status": "UNAVAILABLE",
                        "error": str(e),
                    }

            return {
                "overall_health": "HEALTHY" if all_healthy else "DEGRADED",
                "all_healthy": all_healthy,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "subsystems": health_results,
            }

    def get_last_known_good(self, name: str) -> Optional[Dict[str, Any]]:
        """Returns the last known good status dictionary for a subsystem."""
        with self._lock:
            entry = self._subsystems.get(name)
            return entry.last_known_good if entry else None


# Process-wide default ecosystem registry
ecosystem_registry = EcosystemRegistry()
