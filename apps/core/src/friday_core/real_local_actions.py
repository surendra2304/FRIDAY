"""Jarvis local actions: real host adapters, explicit one-use approval, honest results."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable
from urllib.parse import urlencode
from threading import RLock
import uuid


@dataclass
class LocalAction:
    action_id: str
    kind: str
    target: str
    arguments: list[str]
    created_at: float
    status: str = "awaiting_approval"


class LocalActionEngine:
    SITES = {"youtube": "https://www.youtube.com", "whatsapp": "https://web.whatsapp.com",
             "gmail": "https://mail.google.com", "google": "https://www.google.com",
             "github": "https://github.com", "maps": "https://maps.google.com",
             "calendar": "https://calendar.google.com", "drive": "https://drive.google.com"}

    def __init__(self, state_dir: str, apps: dict[str, list[str]] | None = None,
                 runner: Callable = subprocess.run, clock: Callable = time.monotonic,
                 mail_cache: str | None = None) -> None:
        self.apps = apps or {}
        self.runner, self.clock = runner, clock
        self.mail_cache = Path(mail_cache) if mail_cache else None
        self.pending: dict[str, LocalAction] = {}
        self._lock = RLock()
        self._cpu_previous: tuple[int, int] | None = None
        self.audit_path = Path(state_dir) / "local_actions.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def vitals(self) -> dict:
        """Best-effort real host vitals, with unavailable fields left null."""
        import os
        usage = shutil.disk_usage(self.audit_path.parent)
        load = list(os.getloadavg()) if hasattr(os, "getloadavg") else None
        cpu_percent = memory = battery = None
        if sys.platform.startswith("linux"):
            try:
                fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
                values = [int(x) for x in fields]
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                total = sum(values)
                with self._lock:
                    if self._cpu_previous:
                        old_total, old_idle = self._cpu_previous
                        dt, di = total-old_total, idle-old_idle
                        cpu_percent = round(max(0.0, min(100.0, (dt-di)/dt*100)), 1) if dt > 0 else None
                    self._cpu_previous=(total,idle)
            except (OSError, ValueError, IndexError):
                pass
            try:
                values={}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    key, value = line.split(":",1)
                    parts=value.strip().split()
                    if parts and parts[0].isdigit(): values[key]=int(parts[0])*1024
                total=values.get("MemTotal")
                available=values.get("MemAvailable")
                if total and available is not None:
                    memory={"total_bytes":total,"available_bytes":available,
                            "used_bytes":total-available,"percent":round((total-available)/total*100,1)}
            except (OSError, ValueError):
                pass
            try:
                for battery_path in Path("/sys/class/power_supply").glob("*/capacity"):
                    raw=battery_path.read_text().strip()
                    if raw.isdigit():
                        battery={"percent":int(raw),"status":"available"};break
            except OSError:
                pass
        else:
            try:
                import psutil
                cpu_percent=psutil.cpu_percent(interval=0.1)
                vm=psutil.virtual_memory()
                memory={"total_bytes":vm.total,"available_bytes":vm.available,
                        "used_bytes":vm.used,"percent":vm.percent}
                battery_info=psutil.sensors_battery()
                if battery_info is not None:
                    battery={"percent":battery_info.percent,"plugged_in":battery_info.power_plugged}
            except (ImportError, OSError, AttributeError):
                pass
        return {"status":"ok" if cpu_percent is not None or memory is not None else "partial",
                "platform":sys.platform,"cpu_cores":os.cpu_count(),"cpu_percent":cpu_percent,
                "load_average":load,"memory":memory,"disk":{"total_bytes":usage.total,
                "free_bytes":usage.free,"used_bytes":usage.used},"battery":battery,
                "sampled_at":time.time(),"limitations":"Unavailable measurements are null; no fabricated readings."}

    def read_mail(self) -> str:
        if self.mail_cache is None or not self.mail_cache.is_file():
            return "No mail cache configured or available; no unread count is known."
        with self.mail_cache.open(encoding="utf-8", errors="replace") as handle:
            content = handle.read(6000).strip()
        return content or "The configured mail cache is empty."

    def plan(self, query: str) -> dict | None:
        command = re.sub(r"^\s*(?:jarvis|friday)\b[,\s]*", "", query, flags=re.I).strip().rstrip(".!?")
        lowered = command.lower()
        if lowered in {"time", "what time is it", "date", "today", "what is the date"}:
            return {"text": datetime.now().astimezone().isoformat(), "source": "local"}
        if lowered in {"system vitals", "system status", "system info"}:
            return {"text": "Current host measurements", "vitals": self.vitals(), "source": "local"}
        if lowered in {"mail brief", "check mail", "read emails", "inbox summary", "unread emails"}:
            return {"text": self.read_mail(), "source": "local"}
        kind = target = ""
        arguments: list[str] = []
        match = re.fullmatch(r"(?:play|search|find|open)\s+(.+?)\s+(?:on|in)\s+youtube", command, re.I)
        if match:
            kind, target = "open_url", "https://www.youtube.com/results?" + urlencode({"search_query": match[1]})
        else:
            match = re.fullmatch(r"(?:search|google)(?: for)?\s+(.+)", command, re.I)
            if match:
                kind, target = "open_url", "https://www.google.com/search?" + urlencode({"q": match[1]})
        whatsapp = re.fullmatch(r"send whatsapp to\s+(\+?\d{7,15})\s+saying\s+(.+)", command, re.I)
        if whatsapp:
            kind, target = "message_draft", "https://web.whatsapp.com/send?" + urlencode({"phone": whatsapp[1].lstrip("+"), "text": whatsapp[2]})
        launch = re.fullmatch(r"(?:please\s+)?(?:open|launch|start)\s+(.+)", command, re.I)
        if launch and not kind:
            name = launch[1].lower()
            if name in self.SITES:
                kind, target = "open_url", self.SITES[name]
            elif name in self.apps:
                kind, target, arguments = "launch_app", name, list(self.apps[name])
            else:
                return {"text": f"Application or site is not in the configured allowlist: {name}", "source": "local"}
        if lowered in {"volume up", "volume down", "mute", "mute volume", "mute the volume", "louder", "quieter"}:
            kind, target = "volume", lowered
        if not kind:
            return None
        # Expire old approvals and bound process-local state.
        for key in list(self.pending):
            if self.clock() - self.pending[key].created_at > 300:
                del self.pending[key]
        if len(self.pending) >= 100:
            raise ValueError("too many outstanding local actions")
        action = LocalAction(uuid.uuid4().hex, kind, target, arguments, self.clock())
        self.pending[action.action_id] = action
        return {"text": "Action prepared; explicit approval required before host execution.",
                "source": "local", "action": asdict(action)}

    def execute(self, action_id: str, approved: bool = False) -> dict:
        action = self.pending.get(action_id)
        if action is None:
            raise KeyError(action_id)
        if not approved:
            del self.pending[action_id]
            return {"action_id": action_id, "status": "declined"}
        del self.pending[action_id]  # single use even when the OS fails
        if self.clock() - action.created_at > 300:
            return {"action_id": action_id, "status": "expired"}
        if action.kind in {"open_url", "message_draft"}:
            args = (["open", action.target] if sys.platform == "darwin" else
                    ["rundll32.exe", "url.dll,FileProtocolHandler", action.target] if sys.platform == "win32" else
                    ["xdg-open", action.target])
        elif action.kind == "launch_app":
            args = action.arguments
        else:
            up = action.target in {"volume up", "louder"}
            down = action.target in {"volume down", "quieter"}
            if sys.platform == "darwin":
                script = (f"set volume output volume ((output volume of (get volume settings)) {'+' if up else '-'} 15)"
                          if up or down else "set volume with output muted")
                args = ["osascript", "-e", script]
            elif sys.platform.startswith("linux"):
                args = ["amixer", "-q", "sset", "Master", "15%+" if up else "15%-" if down else "mute"]
            else:
                return {"action_id": action_id, "status": "unsupported", "detail": "volume adapter unavailable"}
        try:
            result = self.runner(args, capture_output=True, text=True, timeout=15, shell=False)
            status = "completed" if result.returncode == 0 else "failed"
        except (OSError, subprocess.TimeoutExpired):
            status = "failed"
        record = {"action_id": action_id, "kind": action.kind, "status": status, "timestamp": time.time()}
        # Audit excludes message text, queries and API credentials.
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return {**record, "detail": "Opened a message draft; no message was sent." if action.kind == "message_draft" else ""}
