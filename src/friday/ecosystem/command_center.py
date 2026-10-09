"""Ecosystem Command Center for FRIDAY.

Provides unified 3-system visibility (Trading Bot, AI-Universe, FRIDAY OS),
ecosystem state governance (FULL_AUTONOMY, SUPERVISED_AUTONOMY, SHADOW_MODE, DEGRADED, EMERGENCY_HALT),
biometric-verified autonomy adjustments, and autonomous decision auditing.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger
from friday.security.production_security import ProductionSecurityManager

logger = get_logger("ecosystem.command_center")


def demo_mode_enabled() -> bool:
    """Whether sample ecosystem data may be used.

    The command centre used to fill its "real-time telemetry" with literals -
    $25,000 deployed, +$420.50 daily P&L, three open positions, 0.84 model
    confidence, "AES-256_BIOMETRIC_ENFORCED" - and a freshly constructed centre
    in a production environment reported all of it as current. Nothing measured
    any of it. Sample data is legitimate for a demo or a test; it is a lie when
    it is indistinguishable from a reading, so it now requires being asked for
    by name (``FRIDAY_DEMO_DATA=true``) or running under ``FRIDAY_ENV=testing``.
    """
    import os

    env = (os.getenv("FRIDAY_ENV") or "").strip().lower()
    flag = (os.getenv("FRIDAY_DEMO_DATA") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return env == "testing"


class EcosystemState(str, Enum):
    """Operational states of the overall trading ecosystem."""
    FULL_AUTONOMY = "FULL_AUTONOMY"
    SUPERVISED_AUTONOMY = "SUPERVISED_AUTONOMY"
    SHADOW_MODE = "SHADOW_MODE"
    DEGRADED = "DEGRADED"
    EMERGENCY_HALT = "EMERGENCY_HALT"


class AutonomyLevel(int, Enum):
    """Graduated levels of algorithmic trading autonomy."""
    LEVEL_1_SHADOW = 1  # Observational only
    LEVEL_2_SUPERVISED = 2  # Standard execution with human gates
    LEVEL_3_AUTONOMOUS = 3  # Full automated parameter and strategy rebalancing


@dataclass
class EcosystemDecision:
    """Audit record of an autonomous decision executed in the ecosystem."""
    decision_id: str
    action_type: str  # AUTONOMY_CHANGE, PARAMETER_OVERLAY, REBALANCE, HALT
    details: dict[str, Any]
    operator_id: str
    signature: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemCommandCenter:
    """Master controller aggregating the 3 core systems and governing ecosystem autonomy."""

    def __init__(
        self,
        security_manager: ProductionSecurityManager | None = None,
        *,
        demo_data: bool | None = None,
    ) -> None:
        self._security_manager = security_manager
        self._ecosystem_state = EcosystemState.SUPERVISED_AUTONOMY
        self._autonomy_level = AutonomyLevel.LEVEL_2_SUPERVISED
        self._decisions: list[EcosystemDecision] = []
        self._lock = threading.RLock()
        #: Live readings reported by an integration, keyed by system name. Until
        #: something calls :meth:`record_system_status` the centre knows nothing,
        #: and :meth:`get_ecosystem_status` says so instead of returning numbers.
        self._reported: dict[str, dict[str, Any]] = {}
        self._demo_data = demo_mode_enabled() if demo_data is None else bool(demo_data)
        if self._demo_data:
            self._init_defaults()

    def record_system_status(self, system: str, payload: dict[str, Any]) -> None:
        """Record a reading reported by a real integration.

        This is the only way a number reaches :meth:`get_ecosystem_status`. A
        trading bridge, an advisory client or a health probe calls it; nothing in
        this module invents a value. ``payload`` should carry whatever the system
        can actually attest to (status, counts, latency) and is merged over the
        previous reading for that system.
        """
        with self._lock:
            current = dict(self._reported.get(system, {}))
            current.update(payload or {})
            current["reported_at"] = datetime.now(timezone.utc).isoformat()
            self._reported[system] = current
            logger.info("Ecosystem reading recorded for '%s': %s", system, sorted(current))

    def record_decision(self, decision: EcosystemDecision) -> None:
        """Append a decision that was really taken, to the audit log."""
        with self._lock:
            self._decisions.append(decision)

    @property
    def security_manager(self) -> ProductionSecurityManager:
        if self._security_manager is None:
            self._security_manager = ProductionSecurityManager()
        return self._security_manager

    def _init_defaults(self) -> None:
        """Sample decisions, only ever used when demo mode was asked for."""
        self._reported = {
            "trading_bot": {
                "status": "HEALTHY",
                "note": "SAMPLE DATA - not a live reading",
                "connected_venues": ["Binance", "Bybit", "OKX"],
                "active_capital_usdt": 25000.0,
                "daily_pnl_usdt": 420.50,
                "active_positions_count": 3,
                "api_latency_ms": 32.4,
            },
            "ai_universe": {
                "status": "HEALTHY",
                "note": "SAMPLE DATA - not a live reading",
                "model_confidence": 0.84,
                "active_predictions_count": 3,
                "debate_engine_status": "ONLINE",
                "latency_ms": 118.0,
            },
            "friday_os": {
                "status": "HEALTHY",
                "note": "SAMPLE DATA - not a live reading",
                "active_operators_count": 8,
            },
        }
        self._decisions = [
            EcosystemDecision(
                decision_id="dec_01",
                action_type="PARAMETER_OVERLAY",
                details={"strategy": "BTC_Supertrend_Momentum", "atr_multiplier": 2.2},
                operator_id="AI_UNIVERSE_AUTONOMOUS",
                signature="e8a1f49b72c91834...",
            ),
            EcosystemDecision(
                decision_id="dec_02",
                action_type="VENUE_REBALANCE",
                details={"venue": "BINANCE", "amount_usdt": 1000.0},
                operator_id="FRIDAY_PORTFOLIO_SUPERVISOR",
                signature="9b2c3d4e5f6a7b8c...",
            ),
        ]

    #: The systems this centre is responsible for reporting on.
    SYSTEMS: tuple[str, ...] = ("trading_bot", "ai_universe", "friday_os")

    def get_ecosystem_status(self) -> dict[str, Any]:
        """Report each system's status **as last reported**, or as unknown.

        Every value here used to be a literal. A caller - the master dashboard,
        the voice skill, the executive dashboard - then rendered those literals
        under a live timestamp, so the reader saw "real-time telemetry" that had
        never been measured. A status field whose default is "HEALTHY" is the
        single most dangerous kind of placeholder, because the failure mode of
        the thing it describes (no data) is reported as the best case.

        Now: a system appears as ``"UNKNOWN"`` with ``"available": False`` until
        an integration calls :meth:`record_system_status`.
        """
        with self._lock:
            systems: dict[str, Any] = {}
            for name in self.SYSTEMS:
                reading = self._reported.get(name)
                if reading:
                    systems[name] = {"available": True, **reading}
                else:
                    systems[name] = {
                        "available": False,
                        "status": "UNKNOWN",
                        "note": "No integration has reported a reading for this system.",
                    }
            return {
                "ecosystem_state": self._ecosystem_state.value,
                "autonomy_level": self._autonomy_level.value,
                "autonomy_name": self._autonomy_level.name,
                "systems": systems,
                "risk_posture": {
                    "available": "trading_bot" in self._reported,
                    "aggregate_leverage": self._reported.get("trading_bot", {}).get("aggregate_leverage"),
                    "daily_loss_limit_proximity_pct": self._reported.get("trading_bot", {}).get(
                        "daily_loss_limit_proximity_pct"
                    ),
                    "single_asset_max_exposure_pct": self._reported.get("trading_bot", {}).get(
                        "single_asset_max_exposure_pct"
                    ),
                },
                "recent_decisions_count": len(self._decisions),
                "demo_data": self._demo_data,
                "data_provenance": (
                    "sample data (FRIDAY_DEMO_DATA or testing environment)"
                    if self._demo_data
                    else "reported by integrations; systems without a reading are UNKNOWN"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def set_autonomy_level(
        self,
        new_level: int,
        speaker_id: str = "operator_surendra",
        voice_embedding: list[float] | None = None,
        verbal_confirmation: str = "",
    ) -> tuple[bool, str, str | None]:
        """Sets autonomy level with biometric verification and verbal phrase check."""
        with self._lock:
            if voice_embedding:
                passed, score, msg = self.security_manager.verify_voice_biometrics(
                    speaker_id, voice_embedding, similarity_threshold=0.95
                )
                if not passed:
                    return False, f"AUTONOMY REJECTED: Voice biometrics failed ({msg}).", None

            # Check verbal phrase
            if "confirm" not in verbal_confirmation.lower():
                return False, "AUTONOMY REJECTED: Verbal confirmation phrase 'Confirm autonomy change' is required.", None

            try:
                target_level = AutonomyLevel(new_level)
            except ValueError:
                return False, f"Invalid autonomy level: {new_level}. Supported: 1 (Shadow), 2 (Supervised), 3 (Autonomous)", None

            old_level = self._autonomy_level
            self._autonomy_level = target_level

            if target_level == AutonomyLevel.LEVEL_1_SHADOW:
                self._ecosystem_state = EcosystemState.SHADOW_MODE
            elif target_level == AutonomyLevel.LEVEL_2_SUPERVISED:
                self._ecosystem_state = EcosystemState.SUPERVISED_AUTONOMY
            elif target_level == AutonomyLevel.LEVEL_3_AUTONOMOUS:
                self._ecosystem_state = EcosystemState.FULL_AUTONOMY

            signed = self.security_manager.sign_decision(
                "SET_AUTONOMY_LEVEL",
                {"old_level": old_level.value, "new_level": target_level.value, "state": self._ecosystem_state.value},
                operator_id=speaker_id,
            )

            decision = EcosystemDecision(
                decision_id=f"dec_{len(self._decisions)+1:02d}",
                action_type="AUTONOMY_CHANGE",
                details={"old_level": old_level.value, "new_level": target_level.value},
                operator_id=speaker_id,
                signature=signed["signature"],
            )
            self._decisions.append(decision)

            msg = (
                f"Ecosystem autonomy successfully set to Level {target_level.value} ({target_level.name}). "
                f"Ecosystem State transitioned to {self._ecosystem_state.value}. "
                f"Signature: `{signed['signature'][:12]}...`"
            )
            logger.info(f"[COMMAND_CENTER] {msg}")
            return True, msg, signed["signature"]

    def get_recent_decisions(self) -> list[EcosystemDecision]:
        """Returns the autonomous decision log."""
        with self._lock:
            return list(self._decisions)
