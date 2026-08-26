# -*- coding: utf-8 -*-
"""Event-Driven Triggers for FRIDAY Persistent Operators.

Supports:
1. FileSystemTrigger: Detects file creation, modification, or deletion in monitored directories.
2. ProcessTrigger: Detects process start and termination events using psutil.
3. ChainedTrigger: Fired by upstream operator completion.
4. ConditionTrigger: Fired when an arbitrary predicate returns True.
5. IntervalTrigger: Periodic timer trigger.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import os
import time
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from friday.core.logging import get_logger

logger = get_logger("operators.triggers")


class BaseTrigger(ABC):
    """Abstract Base Class for all event-driven triggers."""

    def __init__(self, name: str, trigger_id: Optional[str] = None) -> None:
        self.trigger_id = trigger_id or f"trig_{uuid.uuid4().hex[:8]}"
        self.name = name
        self.is_active: bool = False

    def start(self) -> None:
        """Activate trigger monitoring."""
        self.is_active = True

    def stop(self) -> None:
        """Deactivate trigger monitoring."""
        self.is_active = False

    @abstractmethod
    def evaluate(self) -> Optional[Dict[str, Any]]:
        """Check for events. Returns event dictionary if fired, else None."""
        pass


class FileSystemTrigger(BaseTrigger):
    """Monitors a file or directory for modifications, creations, or deletions."""

    def __init__(
        self,
        watch_path: str,
        name: Optional[str] = None,
        recursive: bool = False,
        events_to_watch: Optional[List[str]] = None,
    ) -> None:
        trigger_name = name or f"file_watch:{os.path.basename(watch_path)}"
        super().__init__(name=trigger_name)
        self.watch_path = os.path.abspath(watch_path)
        self.recursive = recursive
        self.events_to_watch = set(events_to_watch or ["created", "modified"])
        self._file_snapshots: Dict[str, float] = {}
        self._initialized = False
        self._watchdog_observer = None

    def start(self) -> None:
        super().start()
        self._update_snapshots()
        self._initialized = True
        logger.info(f"FileSystemTrigger started on '{self.watch_path}'")

    def stop(self) -> None:
        super().stop()
        if self._watchdog_observer:
            try:
                self._watchdog_observer.stop()
                self._watchdog_observer.join(timeout=1.0)
            except Exception:
                pass
            self._watchdog_observer = None

    def _get_current_files(self) -> Dict[str, float]:
        """Collect current files and their modification timestamps."""
        files = {}
        if not os.path.exists(self.watch_path):
            return files

        if os.path.isfile(self.watch_path):
            try:
                files[self.watch_path] = os.path.getmtime(self.watch_path)
            except OSError:
                pass
            return files

        if self.recursive:
            for root, _, filenames in os.walk(self.watch_path):
                for fn in filenames:
                    fp = os.path.join(root, fn)
                    try:
                        files[fp] = os.path.getmtime(fp)
                    except OSError:
                        pass
        else:
            try:
                for entry in os.scandir(self.watch_path):
                    if entry.is_file():
                        try:
                            files[entry.path] = entry.stat().st_mtime
                        except OSError:
                            pass
            except OSError:
                pass

        return files

    def _update_snapshots(self) -> None:
        self._file_snapshots = self._get_current_files()

    def evaluate(self) -> Optional[Dict[str, Any]]:
        """Compare current file system state against previous snapshot."""
        if not self.is_active or not os.path.exists(self.watch_path):
            return None

        current = self._get_current_files()
        if not self._initialized:
            self._file_snapshots = current
            self._initialized = True
            return None

        # Check for created or modified files
        for path, mtime in current.items():
            if path not in self._file_snapshots:
                if "created" in self.events_to_watch:
                    self._file_snapshots = current
                    return {
                        "event_type": "file_created",
                        "path": path,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
            elif mtime > self._file_snapshots[path]:
                if "modified" in self.events_to_watch:
                    self._file_snapshots = current
                    return {
                        "event_type": "file_modified",
                        "path": path,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

        # Check for deleted files
        if "deleted" in self.events_to_watch:
            for path in self._file_snapshots:
                if path not in current:
                    self._file_snapshots = current
                    return {
                        "event_type": "file_deleted",
                        "path": path,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

        self._file_snapshots = current
        return None


class ProcessTrigger(BaseTrigger):
    """Monitors running operating system processes to detect launch and termination events."""

    def __init__(
        self,
        process_name: str,
        name: Optional[str] = None,
        watch_event: str = "started",
    ) -> None:
        super().__init__(name=name or f"process_watch:{process_name}")
        self.process_name = process_name.lower().strip()
        self.watch_event = watch_event.lower().strip()  # "started", "stopped", "any"
        self._known_pids: Set[int] = set()
        self._initialized = False

    def _scan_pids(self) -> Set[int]:
        import psutil
        pids = set()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                pname = (p.info["name"] or "").lower()
                if self.process_name in pname:
                    pids.add(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids

    def start(self) -> None:
        super().start()
        try:
            self._known_pids = self._scan_pids()
        except Exception:
            self._known_pids = set()
        self._initialized = True
        logger.info(f"ProcessTrigger started for '{self.process_name}' (PIDs: {self._known_pids})")

    def evaluate(self) -> Optional[Dict[str, Any]]:
        if not self.is_active:
            return None

        try:
            current_pids = self._scan_pids()
        except Exception as e:
            logger.debug(f"Error scanning processes: {e}")
            return None

        if not self._initialized:
            self._known_pids = current_pids
            self._initialized = True
            return None

        # Check for newly started processes
        started_pids = current_pids - self._known_pids
        if started_pids and self.watch_event in ("started", "any"):
            pid = next(iter(started_pids))
            self._known_pids = current_pids
            return {
                "event_type": "process_started",
                "process_name": self.process_name,
                "pid": pid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Check for stopped processes
        stopped_pids = self._known_pids - current_pids
        if stopped_pids and self.watch_event in ("stopped", "any"):
            pid = next(iter(stopped_pids))
            self._known_pids = current_pids
            return {
                "event_type": "process_stopped",
                "process_name": self.process_name,
                "pid": pid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        self._known_pids = current_pids
        return None


class ConditionTrigger(BaseTrigger):
    """Triggers whenever a custom boolean predicate evaluates to True."""

    def __init__(self, predicate: Callable[[], bool], name: str = "condition_trigger") -> None:
        super().__init__(name=name)
        self.predicate = predicate

    def evaluate(self) -> Optional[Dict[str, Any]]:
        if not self.is_active:
            return None
        try:
            if self.predicate():
                return {
                    "event_type": "condition_met",
                    "trigger_name": self.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.debug(f"Predicate evaluation error: {e}")
        return None


class IntervalTrigger(BaseTrigger):
    """Periodic interval timer trigger."""

    def __init__(self, interval_seconds: float, name: Optional[str] = None) -> None:
        super().__init__(name=name or f"interval_{interval_seconds}s")
        self.interval_seconds = interval_seconds
        self.last_tick: Optional[float] = None

    def evaluate(self) -> Optional[Dict[str, Any]]:
        if not self.is_active:
            return None
        now = time.time()
        if self.last_tick is None or (now - self.last_tick) >= self.interval_seconds:
            self.last_tick = now
            return {
                "event_type": "interval_elapsed",
                "interval_seconds": self.interval_seconds,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return None
