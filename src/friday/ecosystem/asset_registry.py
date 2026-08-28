# -*- coding: utf-8 -*-
"""Asset Registry for FRIDAY.

Maintains a unified, live inventory of all securable assets across FRIDAY ecosystem:
- Domains (Nexus website & growth engine)
- APIs & Services (Forge-built microservices)
- Trading Endpoints (Trading Bot execution venues)
- Cloud & Infrastructure Resources (Reverse proxies, databases, compute clusters)

Tracks per-asset scan histories, findings counts, risk levels, next scheduled scans,
and computes aggregate security posture scores.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel

logger = get_logger("ecosystem.asset_registry")


class AssetType(str, Enum):
    """Types of securable digital assets."""
    DOMAIN = "domain"
    API_SERVICE = "api_service"
    TRADING_ENDPOINT = "trading_endpoint"
    CLOUD_RESOURCE = "cloud_resource"


@dataclass
class SecurableAsset:
    """Inventory record for a securable asset."""
    asset_id: str
    name: str
    asset_type: AssetType
    target: str  # URL, domain, IP, ARN, or endpoint
    subsystem: str  # nexus, forge, trading_bot, infrastructure
    risk_level: str = "CLEAN"  # CRITICAL, HIGH, MEDIUM, LOW, CLEAN
    open_findings_count: int = 0
    last_scan_time: Optional[str] = None
    last_scan_result: Optional[Dict[str, Any]] = None
    next_scheduled_scan: Optional[str] = None
    critical_findings_count: int = 0
    high_findings_count: int = 0
    medium_findings_count: int = 0
    low_findings_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AssetRegistry:
    """Central registry tracking all securable ecosystem assets and posture metrics."""

    def __init__(self) -> None:
        self._assets: Dict[str, SecurableAsset] = {}
        self._lock = threading.RLock()
        self._init_default_assets()

    def _init_default_assets(self) -> None:
        """Initialize baseline inventory from active subsystems."""
        now_iso = datetime.now(timezone.utc).isoformat()
        next_week_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        # 1. Nexus Primary Website
        self.register_asset(
            SecurableAsset(
                asset_id="asset-nexus-web",
                name="Nexus Primary Website",
                asset_type=AssetType.DOMAIN,
                target="example.com",
                subsystem="nexus",
                risk_level="MEDIUM",
                open_findings_count=2,
                critical_findings_count=0,
                high_findings_count=0,
                medium_findings_count=1,
                low_findings_count=1,
                last_scan_time=now_iso,
                last_scan_result={
                    "status": "COMPLETED",
                    "mode": "full_web",
                    "summary": "1 medium finding (TLS config), 1 low finding (CSP header).",
                },
                next_scheduled_scan=next_week_iso,
                metadata={"environment": "production", "framework": "fastapi"},
            )
        )

        # 2. Forge SWE Microservice
        self.register_asset(
            SecurableAsset(
                asset_id="asset-forge-api",
                name="Forge Tasks API",
                asset_type=AssetType.API_SERVICE,
                target="http://localhost:8000/api",
                subsystem="forge",
                risk_level="CLEAN",
                open_findings_count=0,
                last_scan_time=now_iso,
                last_scan_result={"status": "COMPLETED", "mode": "api_security", "summary": "Clean."},
                next_scheduled_scan=next_week_iso,
                metadata={"environment": "internal", "port": 8000},
            )
        )

        # 3. Trading Bot Order Gateway
        self.register_asset(
            SecurableAsset(
                asset_id="asset-trading-bot",
                name="Trading Bot Execution Gateway",
                asset_type=AssetType.TRADING_ENDPOINT,
                target="http://localhost:5000/api/v1/trading",
                subsystem="trading_bot",
                risk_level="CLEAN",
                open_findings_count=0,
                last_scan_time=now_iso,
                last_scan_result={"status": "COMPLETED", "mode": "api_security", "summary": "Clean."},
                next_scheduled_scan=next_week_iso,
                metadata={"environment": "trading_core", "port": 5000},
            )
        )

        # 4. Cloud Infrastructure Database
        self.register_asset(
            SecurableAsset(
                asset_id="asset-cloud-db",
                name="Primary PostgreSQL Cluster",
                asset_type=AssetType.CLOUD_RESOURCE,
                target="tcp://db.internal.friday:5432",
                subsystem="infrastructure",
                risk_level="CLEAN",
                open_findings_count=0,
                last_scan_time=now_iso,
                last_scan_result={"status": "COMPLETED", "mode": "network_scan", "summary": "VPC isolated."},
                next_scheduled_scan=next_week_iso,
                metadata={"vpc": "vpc-friday-core", "ssl": "required"},
            )
        )

    def register_asset(self, asset: SecurableAsset) -> None:
        """Register or update a securable asset."""
        with self._lock:
            self._assets[asset.asset_id] = asset
            logger.info(f"[ASSET_REGISTRY] Registered asset: {asset.asset_id} ({asset.name})")

    def unregister_asset(self, asset_id: str) -> bool:
        """Remove an asset from inventory."""
        with self._lock:
            if asset_id in self._assets:
                del self._assets[asset_id]
                return True
            return False

    def get_asset(self, asset_id: str) -> Optional[SecurableAsset]:
        """Retrieve an asset by its identifier."""
        with self._lock:
            return self._assets.get(asset_id)

    def get_all_assets(self) -> List[SecurableAsset]:
        """List all registered securable assets."""
        with self._lock:
            return list(self._assets.values())

    def get_assets_by_subsystem(self, subsystem: str) -> List[SecurableAsset]:
        """List assets belonging to a specific subsystem."""
        with self._lock:
            return [a for a in self._assets.values() if a.subsystem.lower() == subsystem.lower()]

    def get_highest_risk_asset(self) -> Optional[SecurableAsset]:
        """Find the asset with the highest vulnerability severity."""
        with self._lock:
            if not self._assets:
                return None
            order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "CLEAN": 4}
            sorted_assets = sorted(
                self._assets.values(),
                key=lambda a: (order.get(a.risk_level.upper(), 5), -a.open_findings_count),
            )
            return sorted_assets[0] if sorted_assets else None

    def update_scan_result(
        self,
        asset_id: str,
        findings: List[Dict[str, Any]],
        mode: str = "full_web",
    ) -> Optional[SecurableAsset]:
        """Update scan timestamps, findings counts, and risk levels for an asset."""
        with self._lock:
            asset = self._assets.get(asset_id)
            if not asset:
                return None

            crit = sum(1 for f in findings if f.get("severity", "").upper() == "CRITICAL")
            high = sum(1 for f in findings if f.get("severity", "").upper() == "HIGH")
            med = sum(1 for f in findings if f.get("severity", "").upper() == "MEDIUM")
            low = sum(1 for f in findings if f.get("severity", "").upper() == "LOW")

            risk = "CLEAN"
            if crit > 0:
                risk = "CRITICAL"
            elif high > 0:
                risk = "HIGH"
            elif med > 0:
                risk = "MEDIUM"
            elif low > 0:
                risk = "LOW"

            now_iso = datetime.now(timezone.utc).isoformat()
            asset.risk_level = risk
            asset.open_findings_count = len(findings)
            asset.critical_findings_count = crit
            asset.high_findings_count = high
            asset.medium_findings_count = med
            asset.low_findings_count = low
            asset.last_scan_time = now_iso
            asset.last_scan_result = {
                "status": "COMPLETED",
                "mode": mode,
                "findings_count": len(findings),
                "summary": f"{crit} critical, {high} high, {med} medium, {low} low findings.",
            }
            return asset

    def calculate_security_posture_score(self) -> Dict[str, Any]:
        """Calculate aggregate 0 - 100 security score based on active findings across all assets."""
        with self._lock:
            total_assets = len(self._assets)
            if total_assets == 0:
                return {"score": 100, "rating": "SECURE", "critical": 0, "high": 0, "medium": 0, "low": 0}

            total_crit = sum(a.critical_findings_count for a in self._assets.values())
            total_high = sum(a.high_findings_count for a in self._assets.values())
            total_med = sum(a.medium_findings_count for a in self._assets.values())
            total_low = sum(a.low_findings_count for a in self._assets.values())

            # Base score = 100. Penalties: Critical = -35 each, High = -15 each, Medium = -5 each, Low = -1 each
            deductions = (total_crit * 35) + (total_high * 15) + (total_med * 5) + (total_low * 1)
            score = max(0, min(100, 100 - deductions))

            rating = "SECURE"
            if score < 50 or total_crit > 0:
                rating = "CRITICAL_RISK"
            elif score < 75 or total_high > 0:
                rating = "ELEVATED_RISK"
            elif score < 90 or total_med > 0:
                rating = "MODERATE_RISK"

            return {
                "score": score,
                "rating": rating,
                "total_assets": total_assets,
                "critical": total_crit,
                "high": total_high,
                "medium": total_med,
                "low": total_low,
                "total_findings": total_crit + total_high + total_med + total_low,
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }


# Default singleton instance
asset_registry = AssetRegistry()
