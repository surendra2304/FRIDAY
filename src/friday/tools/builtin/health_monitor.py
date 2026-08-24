# -*- coding: utf-8 -*-
"""Proactive System Health Monitor for FRIDAY.

Monitors CPU, RAM, disk space, battery level, and logs status to ~/friday/system_health.log.
Detects potential issues (low disk, critical battery, high load) and provides alerts.
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import psutil

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("agent.health_monitor")


class SystemHealthMonitor:
    """Proactive system telemetry and health metrics tracker."""

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or (Path.home() / ".friday")
        self.log_file = self.log_dir / "system_health.log"
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"Could not create health monitor log directory: {e}")

    def log_health_metric(self, metric_name: str, value: Any, unit: str = "%") -> None:
        """Append metric sample to system_health.log."""
        try:
            now_iso = datetime.now().isoformat()
            line = f"[{now_iso}] METRIC: {metric_name} = {value} {unit}\n"
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.debug(f"Could not log health metric: {e}")

    def collect_health_report(self) -> Dict[str, Any]:
        """Collect current system telemetry and return structured health status."""
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None

        self.log_health_metric("cpu_percent", cpu)
        self.log_health_metric("ram_percent", ram.percent)
        self.log_health_metric("disk_used_percent", disk.percent)
        if battery:
            self.log_health_metric("battery_percent", battery.percent)

        alerts = []
        if disk.percent > 90.0:
            alerts.append(f"Disk space is low ({disk.percent:.1f}% used, {disk.free // (1024**3):,} GB free).")
        if ram.percent > 90.0:
            alerts.append(f"System memory usage is very high ({ram.percent:.1f}%).")
        if battery and not battery.power_plugged and battery.percent < 20.0:
            alerts.append(f"Battery is low ({battery.percent:.0f}% remaining).")

        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": cpu,
            "ram_percent": ram.percent,
            "ram_used_mb": ram.used // (1024**2),
            "ram_total_mb": ram.total // (1024**2),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free // (1024**3),
            "battery_percent": battery.percent if battery else None,
            "battery_plugged": battery.power_plugged if battery else None,
            "alerts": alerts,
            "healthy": len(alerts) == 0,
        }


class HealthCheckTool(BaseTool):
    """Tool to inspect proactive system health and active alerts."""

    name = "health_check"
    description = (
        "Inspect proactive system health, resources (CPU, RAM, disk, battery), "
        "and check for hardware or performance alerts."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, monitor: Optional[SystemHealthMonitor] = None):
        super().__init__()
        self.monitor = monitor or SystemHealthMonitor()

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            report = self.monitor.collect_health_report()
            alerts_str = "\n".join([f"- [ALERT] {a}" for a in report["alerts"]]) if report["alerts"] else "- All metrics nominal. No active alerts."
            batt_info = f"{report['battery_percent']:.0f}% ({'Plugged in' if report['battery_plugged'] else 'On battery'})" if report['battery_percent'] is not None else "N/A"
            content = (
                f"Proactive Health Status (Status: {'HEALTHY' if report['healthy'] else 'WARNING'}):\n"
                f"- CPU: {report['cpu_percent']:.1f}%\n"
                f"- RAM: {report['ram_percent']:.1f}% ({report['ram_used_mb']:,} MB / {report['ram_total_mb']:,} MB)\n"
                f"- Disk (C:): {report['disk_percent']:.1f}% used ({report['disk_free_gb']:,} GB free)\n"
                f"- Battery: {batt_info}\n"
                f"Alerts:\n{alerts_str}"
            )
            return ToolResult(name=self.name, content=content, is_error=False, safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Failed to check health: {e}", is_error=True, safety_level=self.safety_level)
