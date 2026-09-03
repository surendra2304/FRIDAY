from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.system_monitor")


def get_current_system_resources() -> dict[str, Any]:
    """Retrieve real-time CPU, RAM, and top memory-consuming processes using psutil."""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        virtual_mem = psutil.virtual_memory()
        ram_percent = virtual_mem.percent
        total_ram_gb = round(virtual_mem.total / (1024 ** 3), 2)
        used_ram_gb = round(virtual_mem.used / (1024 ** 3), 2)

        processes = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                info = p.info
                mem_bytes = info['memory_info'].rss if info.get('memory_info') else 0
                mem_mb = round(mem_bytes / (1024 * 1024), 1)
                processes.append({
                    "pid": info['pid'],
                    "name": info['name'] or "unknown",
                    "memory_mb": mem_mb,
                    "cpu_percent": info.get('cpu_percent') or 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Sort by memory usage descending
        processes.sort(key=lambda x: x["memory_mb"], reverse=True)
        top_processes = processes[:5]

        # Battery telemetry
        battery_data = None
        try:
            bat = psutil.sensors_battery()
            if bat is not None:
                battery_data = {
                    "percent": round(bat.percent, 1),
                    "power_plugged": bat.power_plugged,
                    "seconds_left": bat.secsleft if bat.secsleft != -1 and bat.secsleft != -2 else None,
                }
        except Exception:
            battery_data = None

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "total_ram_gb": total_ram_gb,
            "used_ram_gb": used_ram_gb,
            "top_processes": top_processes,
            "battery": battery_data,
        }
    except Exception as e:
        logger.warning(f"Failed to query system resources: {e}")
        return {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "total_ram_gb": 0.0,
            "used_ram_gb": 0.0,
            "top_processes": [],
            "battery": None,
            "error": str(e),
        }


class GetSystemResourcesTool(BaseTool):
    """Inspect CPU usage, RAM utilization, battery status, and top memory-consuming processes."""

    name = "get_system_resources"
    description = (
        "Get current system resource telemetry: CPU usage (%), RAM usage (%), "
        "battery level and charging status, and top 5 memory-consuming applications."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "process_name": {
                "type": "string",
                "description": "Optional specific process name to filter (e.g. 'chrome', 'spotify').",
            }
        },
        "required": [],
    }

    def execute(self, process_name: str | None = None, **kwargs: Any) -> ToolResult:
        res = get_current_system_resources()
        if "error" in res and not res.get("top_processes"):
            return ToolResult(
                name=self.name,
                content=f"Failed to inspect system resources: {res['error']}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if process_name:
            import psutil
            needle = process_name.lower().strip()
            matched = []
            for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                try:
                    pname = (p.info.get('name') or "").lower()
                    if needle in pname:
                        mem_mb = round((p.info['memory_info'].rss if p.info.get('memory_info') else 0) / (1024 * 1024), 1)
                        matched.append(f"- {p.info['name']} (PID {p.info['pid']}): {mem_mb} MB RAM")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if matched:
                content = f"Resource usage for '{process_name}':\n" + "\n".join(matched)
            else:
                content = f"No running processes found matching '{process_name}'."

            return ToolResult(
                name=self.name,
                content=content,
                is_error=False,
                safety_level=self.safety_level,
                metadata=res,
            )

        lines = [
            f"CPU Usage: {res['cpu_percent']}%",
            f"RAM Usage: {res['ram_percent']}% ({res['used_ram_gb']} GB / {res['total_ram_gb']} GB)",
        ]

        # Battery reporting
        bat = res.get("battery")
        if bat:
            plug_str = "Plugged in (Charging)" if bat.get("power_plugged") else "On Battery"
            mins_str = ""
            if bat.get("seconds_left"):
                mins = int(bat["seconds_left"] // 60)
                mins_str = f" (~{mins // 60}h {mins % 60}m remaining)"
            lines.append(f"Battery: {bat['percent']}% — {plug_str}{mins_str}")

        lines.append("Top Memory-Consuming Processes:")
        for p in res.get("top_processes", []):
            lines.append(f"- {p['name']} (PID {p['pid']}): {p['memory_mb']} MB RAM")

        return ToolResult(
            name=self.name,
            content="\n".join(lines),
            is_error=False,
            safety_level=self.safety_level,
            metadata=res,
        )


class KillProcessTool(BaseTool):
    """Terminate or kill a running application process by PID or process name."""

    name = "kill_process"
    description = (
        "Terminate or kill a running process by its PID or process name (e.g. 'notepad.exe', 'Spotify.exe', 1234). "
        "Requires authorization as a DANGEROUS/SENSITIVE system action."
    )
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "pid_or_name": {
                "type": "string",
                "description": "Process ID (integer string) or executable name (e.g. 'Spotify', 'chrome.exe').",
            }
        },
        "required": ["pid_or_name"],
    }

    def execute(self, pid_or_name: str, **kwargs: Any) -> ToolResult:
        import psutil
        target = (pid_or_name or "").strip()
        if not target:
            return ToolResult(
                name=self.name,
                content="No PID or process name provided to kill.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # 1. Check if numeric PID
        if target.isdigit():
            pid = int(target)
            try:
                p = psutil.Process(pid)
                pname = p.name()
                p.terminate()
                p.wait(timeout=2.0)
                return ToolResult(
                    name=self.name,
                    content=f"Terminated process {pname} (PID {pid}).",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            except psutil.TimeoutExpired:
                try:
                    p.kill()
                    return ToolResult(
                        name=self.name,
                        content=f"Forcefully killed process {pname} (PID {pid}).",
                        is_error=False,
                        safety_level=self.safety_level,
                    )
                except Exception as ex:
                    return ToolResult(
                        name=self.name,
                        content=f"Failed to force-kill PID {pid}: {ex}",
                        is_error=True,
                        safety_level=self.safety_level,
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                return ToolResult(
                    name=self.name,
                    content=f"Could not kill process PID {pid}: {e}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        # 2. Match by Process Name
        needle = target.lower()
        if not needle.endswith(".exe"):
            needle_exe = needle + ".exe"
        else:
            needle_exe = needle

        killed_count = 0
        killed_names = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pname = (p.info.get('name') or "").lower()
                if pname == needle or pname == needle_exe or needle in pname:
                    actual_name = p.info.get('name')
                    p.terminate()
                    killed_count += 1
                    killed_names.append(f"{actual_name} (PID {p.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if killed_count == 0:
            return ToolResult(
                name=self.name,
                content=f"No running process found matching '{target}'.",
                is_error=False,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Successfully terminated {killed_count} process(es): {', '.join(killed_names)}.",
            is_error=False,
            safety_level=self.safety_level,
        )
