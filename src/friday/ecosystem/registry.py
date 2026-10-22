"""Central Ecosystem Registry for FRIDAY.

Maintains the unified catalog of all managed ecosystem subsystems:
- Algorithmic Trading Bot (Category: trading, Icon: 📈)
- FORGE Autonomous SWE Engine (Category: engineering, Icon: 🛠️)
- AI-Universe Intelligence Provider (Category: intelligence, Icon: 🧠)

Provides aggregated status queries, parallel health audits, and last-known-good state tracking.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("ecosystem.registry")


@dataclass
class SubsystemEntry:
    """Registration record for an ecosystem subsystem."""
    name: str
    display_name: str
    category: str  # trading, engineering, intelligence
    icon: str
    health_check_callable: Callable[[], dict[str, Any]]
    status_callable: Callable[[], dict[str, Any]]
    last_known_good: dict[str, Any] | None = None
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemRegistry:
    """Central registry tracking all ecosystem subsystems, statuses, and health checks."""

    def __init__(self) -> None:
        self._subsystems: dict[str, SubsystemEntry] = {}
        self._lock = threading.RLock()
        self._init_default_subsystems()

    def _init_default_subsystems(self) -> None:
        """Register known identities without inventing their runtime state."""
        entries = (
            ("trading_bot", "Stratex", "trading", "📈"),
            ("forge", "Forge", "engineering", "🛠️"),
            ("ai_universe", "Inference", "intelligence", "🧠"),
            ("nexus", "Cortex", "growth", "🌐"),
            ("sentinel", "Sentinel", "security", "🛡️"),
            ("intelx", "IntelX", "intelligence", "🔬"),
            ("friday", "FRIDAY Core", "core", "🤖"),
            ("futuris", "Futuris", "forecasting", "🔮"),
        )
        for name, display_name, category, icon in entries:
            def unverified(name: str = name) -> dict[str, Any]:
                return {
                    "status": "UNVERIFIED",
                    "evidence": "No live health/status probe is configured for this service.",
                    "service": name,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }

            self.register(
                SubsystemEntry(
                    name=name,
                    display_name=display_name,
                    category=category,
                    icon=icon,
                    health_check_callable=unverified,
                    status_callable=unverified,
                )
            )

    def register(self, entry: SubsystemEntry) -> None:
        """Registers a subsystem in the ecosystem registry."""
        with self._lock:
            self._subsystems[entry.name] = entry
            logger.info(f"[ECOSYSTEM_REGISTRY] Registered subsystem: {entry.name} ({entry.display_name})")

    def get_subsystem(self, name: str) -> SubsystemEntry | None:
        """Retrieves a subsystem registration entry by name (supports aliases)."""
        aliases = {"stratex": "trading_bot", "inference": "ai_universe", "cortex": "nexus"}
        resolved_name = aliases.get(name.lower().strip(), name)
        with self._lock:
            return self._subsystems.get(resolved_name)

    def get_subsystem_status(self, name: str) -> dict[str, Any]:
        """Executes the status callable for a specific subsystem and returns its telemetry."""
        entry = self.get_subsystem(name)
        if not entry:
            return {"status": "UNKNOWN", "error": f"Subsystem '{name}' not found"}
        try:
            data = entry.status_callable()
            if str(data.get("status", "")).upper() not in {"UNVERIFIED", "UNKNOWN"}:
                entry.last_known_good = data
            return data
        except Exception as e:
            logger.warning(f"[ECOSYSTEM_REGISTRY] Status error for {name}: {e}")
            return entry.last_known_good or {"status": "ERROR", "error": str(e)}

    def list_subsystems(self) -> list[SubsystemEntry]:
        """Returns list of all registered subsystems."""
        with self._lock:
            return list(self._subsystems.values())

    def get_ecosystem_status(self) -> dict[str, Any]:
        """Aggregates real-time status across all registered subsystems."""
        with self._lock:
            aggregated = {}
            for name, entry in self._subsystems.items():
                try:
                    data = entry.status_callable()
                    if str(data.get("status", "")).upper() not in {"UNVERIFIED", "UNKNOWN"}:
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

    def get_ecosystem_health(self) -> dict[str, Any]:
        """Executes health checks across all subsystems and reports overall status."""
        with self._lock:
            health_results = {}
            observed_statuses: list[str] = []

            for name, entry in self._subsystems.items():
                try:
                    res = entry.health_check_callable()
                    status = str(res.get("status", "UNVERIFIED")).upper()
                    observed_statuses.append(status)
                    health_results[name] = {
                        "display_name": entry.display_name,
                        "icon": entry.icon,
                        "status": status,
                        "details": res,
                    }
                except Exception as e:
                    observed_statuses.append("UNAVAILABLE")
                    health_results[name] = {
                        "display_name": entry.display_name,
                        "icon": entry.icon,
                        "status": "UNAVAILABLE",
                        "error": str(e),
                    }

            healthy_states = {"HEALTHY", "AVAILABLE", "RUNNING", "IDLE"}
            all_healthy = bool(observed_statuses) and all(status in healthy_states for status in observed_statuses)
            has_unknown = any(status in {"UNVERIFIED", "UNKNOWN"} for status in observed_statuses)
            overall = "HEALTHY" if all_healthy else ("UNVERIFIED" if has_unknown and all(status in healthy_states | {"UNVERIFIED", "UNKNOWN"} for status in observed_statuses) else "DEGRADED")
            return {
                "overall_health": overall,
                "all_healthy": all_healthy if not has_unknown else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "subsystems": health_results,
            }

    def get_last_known_good(self, name: str) -> dict[str, Any] | None:
        """Returns the last known good status dictionary for a subsystem."""
        with self._lock:
            entry = self._subsystems.get(name)
            return entry.last_known_good if entry else None


# Process-wide default ecosystem registry
ecosystem_registry = EcosystemRegistry()
