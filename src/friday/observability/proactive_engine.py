"""FRIDAY Proactive Engine: ambient awareness and unprompted announcements.

JARVIS does not wait to be asked. He watches suit diagnostics, the mansion,
the battlefield, and speaks up the moment something needs attention. This engine
continuously monitors system state and emits proactive announcements that FRIDAY
surfaces over voice and text without the user prompting.

Monitors:
  - System telemetry  : CPU, RAM, battery, disk, network
  - Active window     : what the user is currently doing
  - Anomaly detection : sudden spikes, low battery, hot CPU
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import psutil

from friday.core.logging import get_logger
from friday.observability.notifications import NotificationManager

logger = get_logger("observability.proactive")


@dataclass
class SystemSnapshot:
    """A single point-in-time reading of system health."""

    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    battery_percent: float | None
    battery_plugged: bool | None
    disk_percent: float
    network_up_kbps: float
    network_down_kbps: float
    active_window: str = ""
    top_processes: list[str] = field(default_factory=list)

    def cpu_hot(self) -> bool:
        return self.cpu_percent >= 85

    def ram_critical(self) -> bool:
        return self.ram_percent >= 90

    def battery_low(self) -> bool:
        return self.battery_percent is not None and self.battery_percent <= 20 and not self.battery_plugged

    def disk_full(self) -> bool:
        return self.disk_percent >= 90


def capture_snapshot() -> SystemSnapshot:
    """Grab one system telemetry reading (safe, never raises)."""
    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        battery = psutil.sensors_battery()
        net = psutil.net_io_counters()
        up_kbps = round(net.bytes_sent / 1024, 1)
        down_kbps = round(net.bytes_recv / 1024, 1)
        top: list[str] = []
        try:
            for p in psutil.process_iter(["name", "cpu_percent"]):
                info = p.info
                if info.get("name") and (info.get("cpu_percent") or 0) > 5:
                    top.append(str(info["name"]))
                if len(top) >= 5:
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return SystemSnapshot(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=round(cpu, 1),
            ram_percent=round(ram.percent, 1),
            ram_used_gb=round(ram.used / (1024 ** 3), 2),
            ram_total_gb=round(ram.total / (1024 ** 3), 2),
            battery_percent=round(battery.percent, 1) if battery else None,
            battery_plugged=battery.power_plugged if battery else None,
            disk_percent=round(disk.percent, 1),
            network_up_kbps=up_kbps,
            network_down_kbps=down_kbps,
            top_processes=top,
        )
    except Exception as exc:
        logger.warning(f"System snapshot failed: {exc}")
        return SystemSnapshot(
            timestamp=datetime.now(timezone.utc),
            cpu_percent=0, ram_percent=0, ram_used_gb=0, ram_total_gb=0,
            battery_percent=None, battery_plugged=None,
            disk_percent=0, network_up_kbps=0, network_down_kbps=0,
        )


PROACTIVE_OPENERS = (
    "While you were not looking -",
    "Quick heads-up:",
    "Before you ask -",
    "Something you should know:",
    "If I may interject -",
    "Worth noting:",
    "Just keeping you in the loop:",
)


def _phrase(message: str) -> str:
    """Wrap a raw monitoring fact in FRIDAY proactive voice."""
    return f"{random.choice(PROACTIVE_OPENERS)} {message}"


class ProactiveEngine:
    """Continuously monitors system state and emits proactive announcements.

    Runs a background polling loop. Call start() once at agent init and
    stop() at shutdown. Announcements are posted to the NotificationManager
    so FRIDAY surfaces them on the next turn (or immediately over voice).
    """

    def __init__(
        self,
        notifications: NotificationManager,
        user_name: str = "Surendra",
        poll_interval_seconds: float = 30.0,
    ) -> None:
        self.notifications = notifications
        self.user_name = user_name
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_snapshot: SystemSnapshot | None = None
        self._last_announcement_at: dict[str, datetime] = {}
        self._announcement_cooldown = timedelta(minutes=5)
        self._custom_checks: list[Callable[[SystemSnapshot, SystemSnapshot | None], str | None]] = []

    def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="friday-proactive", daemon=True)
        self._thread.start()
        logger.info("ProactiveEngine started")

    def stop(self) -> None:
        """Stop the background monitoring loop."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("ProactiveEngine stopped")

    def register_check(
        self, fn: Callable[[SystemSnapshot, SystemSnapshot | None], str | None]
    ) -> None:
        """Register a custom check function.

        The function receives (current, previous) snapshots and returns either
        an announcement string or None. Use this to add domain-specific monitoring.
        """
        self._custom_checks.append(fn)

    @property
    def last_snapshot(self) -> SystemSnapshot | None:
        return self._last_snapshot

    def _run(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                snapshot = capture_snapshot()
                self._evaluate(snapshot, self._last_snapshot)
                self._last_snapshot = snapshot
            except Exception as exc:
                logger.error(f"ProactiveEngine poll error: {exc}")
            self._stop_event.wait(self.poll_interval)

    def _evaluate(self, current: SystemSnapshot, previous: SystemSnapshot | None) -> None:
        announcements: list[tuple[str, str]] = []
        if current.cpu_hot():
            announcements.append((
                f"CPU is running hot at {current.cpu_percent}%. "
                f"{'Top offender: ' + current.top_processes[0] if current.top_processes else 'Keeping an eye on it.'}",
                "warning",
            ))
        if current.ram_critical():
            announcements.append((
                f"RAM usage is at {current.ram_percent}% ({current.ram_used_gb}/{current.ram_total_gb} GB). "
                "Might want to close a few things.",
                "warning",
            ))
        if current.battery_low():
            announcements.append((
                f"Battery is at {current.battery_percent}% and not charging. "
                "Plugging in would be wise.",
                "warning",
            ))
        if current.disk_full():
            announcements.append((
                f"Disk is {current.disk_percent}% full. Running low on space.",
                "warning",
            ))
        if previous and current.cpu_percent < 30 and previous.cpu_percent >= 85:
            announcements.append(("CPU has cooled down. Crisis averted.", "info"))
        for fn in self._custom_checks:
            try:
                result = fn(current, previous)
                if result:
                    announcements.append((result, "info"))
            except Exception as exc:
                logger.warning(f"Custom proactive check failed: {exc}")
        for message, severity in announcements:
            if self._should_announce(message):
                self.notifications.post_notification(
                    message=_phrase(message),
                    category="system_monitor",
                    severity=severity,
                )

    def _should_announce(self, message: str) -> bool:
        """Cooldown so we do not repeat the same announcement every poll."""
        key = message[:60]
        now = datetime.now(timezone.utc)
        last = self._last_announcement_at.get(key)
        if last and (now - last) < self._announcement_cooldown:
            return False
        self._last_announcement_at[key] = now
        return True