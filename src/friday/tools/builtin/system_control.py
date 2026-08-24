# -*- coding: utf-8 -*-
"""System Control tool for process inspection, termination, and service status."""

import os
import psutil
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.system_control")

_PROTECTED_PROCESSES = {"system", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe"}


class SystemControlTool(BaseTool):
    """System control tool for listing processes, checking resources, and terminating tasks."""

    name = "system_control"
    description = (
        "Perform system diagnostics and process management. Actions: 'list_processes' (top processes by memory/cpu), "
        "'terminate_process' (close task by name or pid), 'system_status' (CPU, RAM, battery, disk telemetry)."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_processes", "terminate_process", "system_status"],
                "description": "System control action to execute.",
            },
            "process_name": {
                "type": "string",
                "description": "Process name (e.g. 'notepad.exe') or PID for termination.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of processes to return (default: 10).",
            },
        },
        "required": ["action"],
    }

    def execute(
        self,
        action: str = "",
        process_name: str = "",
        limit: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        act = (action or "").strip().lower()

        if act == "system_status":
            try:
                cpu = psutil.cpu_percent(interval=0.1)
                ram = psutil.virtual_memory()
                disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
                battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
                batt_str = f"{battery.percent:.0f}% ({'Plugged in' if battery.power_plugged else 'Battery'})" if battery else "N/A"
                report = (
                    f"System Status:\n"
                    f"- CPU Usage: {cpu:.1f}%\n"
                    f"- RAM: {ram.percent:.1f}% used ({ram.used // (1024**2):,} MB / {ram.total // (1024**2):,} MB)\n"
                    f"- Disk (C:): {disk.percent:.1f}% used ({disk.free // (1024**3):,} GB free)\n"
                    f"- Battery: {batt_str}"
                )
                return ToolResult(name=self.name, content=report, is_error=False, safety_level=self.safety_level)
            except Exception as e:
                return ToolResult(name=self.name, content=f"Failed to query system status: {e}", is_error=True, safety_level=self.safety_level)

        if act == "list_processes":
            try:
                procs = []
                for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
                    try:
                        info = p.info
                        procs.append(info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                procs.sort(key=lambda x: x.get("memory_percent") or 0.0, reverse=True)
                top = procs[: max(1, min(50, limit))]
                lines = [f"{p['pid']:>6} | {p['name']:<25} | RAM: {p['memory_percent']:.1f}%" for p in top]
                out = "PID    | Process Name              | Memory\n" + "-" * 45 + "\n" + "\n".join(lines)
                return ToolResult(name=self.name, content=out, is_error=False, safety_level=self.safety_level)
            except Exception as e:
                return ToolResult(name=self.name, content=f"Failed to list processes: {e}", is_error=True, safety_level=self.safety_level)

        if act == "terminate_process":
            target = (process_name or "").strip()
            if not target:
                return ToolResult(name=self.name, content="No process name or PID specified to terminate.", is_error=True, safety_level=self.safety_level)
            if target.lower() in _PROTECTED_PROCESSES:
                return ToolResult(name=self.name, content=f"Cannot terminate critical system process '{target}'.", is_error=True, safety_level=self.safety_level)

            killed = 0
            try:
                if target.isdigit():
                    pid = int(target)
                    p = psutil.Process(pid)
                    p.terminate()
                    killed += 1
                else:
                    target_lower = target.lower()
                    for p in psutil.process_iter(["pid", "name"]):
                        try:
                            if p.info["name"] and p.info["name"].lower() == target_lower:
                                p.terminate()
                                killed += 1
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                if killed > 0:
                    return ToolResult(name=self.name, content=f"Successfully terminated {killed} instance(s) of '{target}'.", is_error=False, safety_level=self.safety_level)
                return ToolResult(name=self.name, content=f"No running process matching '{target}' found.", is_error=False, safety_level=self.safety_level)
            except Exception as e:
                return ToolResult(name=self.name, content=f"Error terminating process '{target}': {e}", is_error=True, safety_level=self.safety_level)

        return ToolResult(name=self.name, content=f"Unknown action '{action}'.", is_error=True, safety_level=self.safety_level)
