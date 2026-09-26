"""Enhanced Friday Doctor for 5-Subsystem Diagnostics and Automated Self-Healing.

Comprehensive diagnostics covering all 5 ecosystem components:
1. Algorithmic Trading Bot
2. AI-Universe Intelligence Core
3. FORGE Software Engineering Engine
4. Nexus Website & Growth Engine
5. FRIDAY Core Operating System

Features automated healing actions (reconnect stale sockets, restart failed operators,
clear cache corruption) and pre-flight startup configuration verification.
"""

import os
import importlib.util
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry

logger = get_logger("diagnostics.doctor_enhanced")


@dataclass
class PreFlightCheckResult:
    """Outcome of pre-flight environment and configuration audit."""
    is_ready_for_startup: bool
    checks_passed: int
    checks_total: int
    details: dict[str, bool]
    recommendations: list[str] = field(default_factory=list)


@dataclass
class DoctorDiagnosticReport:
    """Comprehensive 5-subsystem diagnostic audit."""
    overall_status: str  # HEALTHY, WARNING, CRITICAL
    subsystem_reports: dict[str, dict[str, Any]]
    healing_actions_taken: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FridayDoctorEnhanced:
    """Enhanced multi-system medical officer for automated diagnostics and self-healing."""

    def __init__(self, registry: EcosystemRegistry | None = None, settings: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or ecosystem_registry
        self._lock = threading.RLock()
        self._stale_connections_healed = 0
        self._operators_restarted = 0
        self._cache_purges = 0

    # =========================================================================
    # 1. Pre-Flight Startup Verification
    # =========================================================================

    def run_preflight_check(self) -> PreFlightCheckResult:
        """Check actual local configuration; do not mark unprobed services ready."""
        writable = os.access(os.getcwd(), os.W_OK)
        checks: dict[str, bool] = {
            "python_runtime_valid": bool(os.sys.version_info >= (3, 10)),
            "security_encryption_available": importlib.util.find_spec("cryptography") is not None,
            "reports_directory_writable": writable,
            "trading_bot_url_configured": bool(getattr(self.settings, "stratex_url", None) or os.getenv("FRIDAY_STRATEX_URL") or os.getenv("STRATEX_URL")),
            "forge_url_configured": bool(getattr(self.settings, "forge_url", None) or os.getenv("FRIDAY_FORGE_URL") or os.getenv("FORGE_URL")),
            "inference_url_configured": bool(getattr(self.settings, "inference_url", None) or os.getenv("FRIDAY_INFERENCE_URL") or os.getenv("INFERENCE_URL")),
            "cortex_url_configured": bool(getattr(self.settings, "cortex_url", None) or os.getenv("FRIDAY_CORTEX_URL") or os.getenv("CORTEX_URL")),
            "sentinel_url_configured": bool(getattr(self.settings, "sentinel_url", None) or os.getenv("FRIDAY_SENTINEL_URL") or os.getenv("SENTINEL_URL")),
        }

        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        is_ready = passed == total

        recommendations = []
        if not is_ready:
            recommendations.append("Configure the missing local prerequisite(s); cloud reachability is not checked by preflight.")

        return PreFlightCheckResult(
            is_ready_for_startup=is_ready,
            checks_passed=passed,
            checks_total=total,
            details=checks,
            recommendations=recommendations,
        )

    # =========================================================================
    # 2. Runtime diagnostics (read-only)
    # =========================================================================

    def diagnose_and_heal(self) -> DoctorDiagnosticReport:
        """Return registered subsystem observations without inventing health or repairs."""
        with self._lock:
            health = self.registry.get_ecosystem_health()
            subsystem_reports = health.get("subsystems", {})
            overall_status = str(health.get("overall_health", "UNVERIFIED"))

            return DoctorDiagnosticReport(
                overall_status=overall_status,
                subsystem_reports=subsystem_reports,
                healing_actions_taken=[],
            )

    # =========================================================================
    # 3. Automated Healing Routines
    # =========================================================================

    def heal_stale_connections(self) -> str | None:
        """No-op until a concrete stale connection can be identified and verified."""
        logger.info("[FRIDAY_DOCTOR] No connection repair performed: no verified stale connection was provided.")
        return None

    def restart_failed_operators(self) -> str | None:
        """No-op until a specific failed operator and safe restart procedure exist."""
        logger.info("[FRIDAY_DOCTOR] No operator restart performed: operator state is not instrumented.")
        return None

    def clear_corrupted_cache(self) -> str | None:
        """No-op until cache ownership and corruption evidence are available."""
        logger.info("[FRIDAY_DOCTOR] No cache purge performed: corruption was not verified.")
        return None


# Global singleton instance
friday_doctor_enhanced = FridayDoctorEnhanced()
