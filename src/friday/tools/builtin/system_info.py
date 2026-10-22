"""Safe built-in tool for retrieving comprehensive local system information."""

import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class SystemInfoTool(BaseTool):
    """Tool to query local system environment, hardware architecture, OS, and Python details safely."""

    name = "get_system_info"
    description = "Retrieve operating system, processor architecture, CPU counts, Python runtime, and UTC timestamp."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Optional category filter: 'all', 'os', 'hardware', 'runtime'",
            }
        },
        "required": [],
    }

    def execute(self, category: str = "all", **kwargs: Any) -> ToolResult:
        os_info = {
            "Operating System": platform.system(),
            "OS Release": platform.release(),
            "OS Version": platform.version(),
            "Platform": platform.platform(),
        }

        hw_info = {
            "Architecture": platform.machine(),
            "Processor": platform.processor() or "Unknown",
            "Logical CPU Cores": os.cpu_count() or 1,
        }

        # Try to read total memory safely if possible
        try:
            if sys.platform == "win32":
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    total_gb = round(stat.ullTotalPhys / (1024**3), 2)
                    avail_gb = round(stat.ullAvailPhys / (1024**3), 2)
                    hw_info["Total Physical RAM (GB)"] = total_gb
                    hw_info["Available Physical RAM (GB)"] = avail_gb
                    hw_info["Memory Load"] = f"{stat.dwMemoryLoad}%"
        except Exception:
            pass

        runtime_info = {
            "Python Version": sys.version.split()[0],
            "Python Executable": sys.executable,
            "Current UTC Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

        cat = category.lower().strip() if category else "all"

        sections = []
        if cat in ("all", "os"):
            sections.append("#### OS Information\n" + "\n".join(f"- **{k}**: {v}" for k, v in os_info.items()))
        if cat in ("all", "hardware"):
            sections.append("#### Hardware Architecture\n" + "\n".join(f"- **{k}**: {v}" for k, v in hw_info.items()))
        if cat in ("all", "runtime"):
            sections.append("#### Runtime & Environment\n" + "\n".join(f"- **{k}**: {v}" for k, v in runtime_info.items()))

        if not sections:
            sections.append("#### System Information\n" + "\n".join(f"- **{k}**: {v}" for k, v in {**os_info, **hw_info, **runtime_info}.items()))

        return ToolResult(
            name=self.name,
            content="### System Diagnostics Report\n" + "\n\n".join(sections),
            is_error=False,
            safety_level=self.safety_level,
        )
