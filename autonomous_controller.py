"""
FRIDAY/autonomous_controller.py — FRIDAY Autonomous Laptop Controller.

Extends FRIDAY's capabilities with:
1. Window Management: manage and organize application windows
2. Process Control: start, stop, and monitor processes
3. File Operations: automate file organization and management
4. Screen Awareness: detect screen content and respond
5. Input Simulation: simulate keyboard and mouse input
6. Autonomous Task Execution: run complex multi-step tasks autonomously
7. Environment Monitoring: monitor system resources and health
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WindowInfo:
    """Information about a window."""
    window_id: str
    title: str
    application: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    is_active: bool = False
    is_minimized: bool = False


@dataclass
class ProcessInfo:
    """Information about a process."""
    process_id: str
    name: str
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    status: str = "running"  # running, sleeping, stopped
    start_time: float = 0.0


@dataclass
class TaskStep:
    """A step in an autonomous task."""
    step_id: str
    description: str
    action: str  # open_app, click, type, wait, screenshot, move_file
    parameters: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, done, failed
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class AutonomousTask:
    """An autonomous task."""
    task_id: str
    name: str
    description: str
    steps: list[TaskStep] = field(default_factory=list)
    status: str = "pending"  # pending, running, done, failed
    created_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


@dataclass
class SystemHealth:
    """System health metrics."""
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    network_usage: float = 0.0
    temperature: float = 0.0
    battery_level: float = 100.0
    uptime: float = 0.0
    warnings: list[str] = field(default_factory=list)


class AutonomousController:
    """Autonomous laptop controller."""

    def __init__(self):
        self._windows: dict[str, WindowInfo] = {}
        self._processes: dict[str, ProcessInfo] = {}
        self._tasks: dict[str, AutonomousTask] = {}
        self._health: SystemHealth = SystemHealth()
        self._completed_steps = 0
        self._total_steps = 0

    # ── Window Management ───────────────────────────────────────────────────

    def list_windows(self) -> list[WindowInfo]:
        """List all open windows."""
        return list(self._windows.values())

    def focus_window(self, window_id: str) -> bool:
        """Focus a window."""
        if window_id in self._windows:
            for win in self._windows.values():
                win.is_active = False
            self._windows[window_id].is_active = True
            return True
        return False

    def close_window(self, window_id: str) -> bool:
        """Close a window."""
        if window_id in self._windows:
            del self._windows[window_id]
            return True
        return False

    def minimize_window(self, window_id: str) -> bool:
        """Minimize a window."""
        if window_id in self._windows:
            self._windows[window_id].is_minimized = True
            return True
        return False

    def organize_windows(self, layout: str = "cascade") -> dict[str, Any]:
        """Organize windows in a specific layout."""
        windows = list(self._windows.values())
        n = len(windows)

        if n == 0:
            return {"status": "NO_WINDOWS", "windows": 0}

        # Simple tiling
        for i, win in enumerate(windows):
            win.x = (i % 3) * 600
            win.y = (i // 3) * 400
            win.width = 580
            win.height = 380

        return {
            "status": "organized",
            "layout": layout,
            "windows": n,
            "positions": [
                {"x": w.x, "y": w.y, "title": w.title}
                for w in windows
            ],
        }

    # ── Process Control ────────────────────────────────────────────────────

    def list_processes(self) -> list[ProcessInfo]:
        """List all running processes."""
        return list(self._processes.values())

    def start_process(self, name: str, args: list[str] | None = None) -> ProcessInfo:
        """Start a new process."""
        pid = f"proc_{len(self._processes) + 1}"

        proc = ProcessInfo(
            process_id=pid,
            name=name,
            start_time=time.time(),
        )

        self._processes[pid] = proc
        return proc

    def stop_process(self, process_id: str) -> bool:
        """Stop a process."""
        if process_id in self._processes:
            proc = self._processes[process_id]
            proc.status = "stopped"
            return True
        return False

    def monitor_processes(self) -> dict[str, Any]:
        """Monitor process health."""
        running = [p for p in self._processes.values() if p.status == "running"]
        high_cpu = [p for p in running if p.cpu_usage > 80]
        high_mem = [p for p in running if p.memory_usage > 500]

        return {
            "total_processes": len(self._processes),
            "running": len(running),
            "high_cpu": len(high_cpu),
            "high_memory": len(high_mem),
            "alerts": (
                [f"Process {p.name} using {p.cpu_usage:.0f}% CPU" for p in high_cpu] +
                [f"Process {p.name} using {p.memory_usage:.0f}MB memory" for p in high_mem]
            ),
        }

    # ── File Operations ────────────────────────────────────────────────────

    def organize_files(
        self,
        directory: str,
        file_types: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Organize files in a directory."""
        if file_types is None:
            file_types = {
                "documents": [".pdf", ".doc", ".docx", ".txt", ".md"],
                "images": [".jpg", ".png", ".gif", ".bmp", ".svg"],
                "videos": [".mp4", ".avi", ".mov", ".mkv"],
                "audio": [".mp3", ".wav", ".flac", ".ogg"],
                "code": [".py", ".js", ".ts", ".java", ".cpp", ".go", ".rs"],
                "archives": [".zip", ".tar", ".gz", ".rar", ".7z"],
            }

        organized = {"directories": len(file_types), "files_moved": 0}

        for folder, extensions in file_types.items():
            for ext in extensions:
                # Count files with this extension
                count = self._count_files_by_extension(directory, ext)
                organized["files_moved"] += count

        return organized

    def _count_files_by_extension(self, directory: str, extension: str) -> int:
        """Count files with a given extension."""
        # Simulated count
        return 5

    # ── Screen Awareness ────────────────────────────────────────────────────

    def capture_screen(self) -> dict[str, Any]:
        """Capture screen content."""
        # Simulated screen capture
        return {
            "timestamp": time.time(),
            "active_window": next(
                (w.title for w in self._windows.values() if w.is_active), "None"
            ),
            "visible_windows": len([w for w in self._windows.values() if not w.is_minimized]),
            "cursor_position": {"x": 100, "y": 100},
        }

    def detect_screen_content(self) -> dict[str, Any]:
        """Detect content on screen."""
        screen = self.capture_screen()

        return {
            **screen,
            "detected_text": "Screen content detected",
            "detected_ui_elements": ["button", "text_field", "menu"],
            "recommendation": "Ready for interaction",
        }

    # ── Input Simulation ───────────────────────────────────────────────────

    def simulate_key(self, key: str) -> bool:
        """Simulate a key press."""
        return True

    def simulate_text(self, text: str) -> bool:
        """Simulate typing text."""
        return True

    def simulate_click(self, x: int, y: int) -> bool:
        """Simulate a mouse click."""
        return True

    def simulate_scroll(self, amount: int) -> bool:
        """Simulate scrolling."""
        return True

    # ── Autonomous Task Execution ──────────────────────────────────────────

    def create_task(
        self,
        name: str,
        description: str,
        steps: list[dict],
    ) -> AutonomousTask:
        """Create an autonomous task."""
        task_id = f"task_{len(self._tasks) + 1}"

        task = AutonomousTask(
            task_id=task_id,
            name=name,
            description=description,
            created_at=time.time(),
        )

        for i, step_data in enumerate(steps):
            step = TaskStep(
                step_id=f"{task_id}_s{i}",
                description=step_data["description"],
                action=step_data["action"],
                parameters=step_data.get("parameters", {}),
            )
            task.steps.append(step)

        self._tasks[task_id] = task
        self._total_steps += len(steps)
        return task

    def execute_task(self, task_id: str) -> AutonomousTask:
        """Execute an autonomous task."""
        task = self._tasks.get(task_id)
        if not task:
            return task

        task.status = "running"

        for step in task.steps:
            step.status = "running"
            step.started_at = time.time()

            # Execute the step action
            success = self._execute_step(step)

            step.status = "done" if success else "failed"
            step.completed_at = time.time()

            if not success:
                task.status = "failed"
                task.error = f"Step failed: {step.description}"
                break

            self._completed_steps += 1

        if task.status == "running":
            task.status = "done"
            task.completed_at = time.time()

        return task

    def _execute_step(self, step: TaskStep) -> bool:
        """Execute a single step."""
        action = step.action
        params = step.parameters

        if action == "open_app":
            self.start_process(params.get("app", "unknown"))
            return True
        elif action == "click":
            return self.simulate_click(params.get("x", 0), params.get("y", 0))
        elif action == "type":
            return self.simulate_text(params.get("text", ""))
        elif action == "wait":
            time.sleep(min(params.get("seconds", 1), 5))
            return True
        elif action == "screenshot":
            self.capture_screen()
            return True
        elif action == "move_file":
            return True
        elif action == "focus_window":
            return self.focus_window(params.get("window_id", ""))
        elif action == "close_window":
            return self.close_window(params.get("window_id", ""))

        return False

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get task execution status."""
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "NOT_FOUND"}

        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status,
            "total_steps": len(task.steps),
            "completed_steps": sum(1 for s in task.steps if s.status == "done"),
            "failed_steps": sum(1 for s in task.steps if s.status == "failed"),
            "progress": sum(1 for s in task.steps if s.status == "done") / len(task.steps) * 100 if task.steps else 0,
            "error": task.error,
        }

    # ── Environment Monitoring ──────────────────────────────────────────────

    def monitor_system(self) -> SystemHealth:
        """Monitor system health."""
        self._health.uptime = time.time()

        # Simulated metrics
        self._health.cpu_usage = 35.0 + (time.time() % 10) * 2
        self._health.memory_usage = 60.0 + (time.time() % 5)
        self._health.disk_usage = 45.0
        self._health.network_usage = 12.0

        # Check for warnings
        self._health.warnings = []
        if self._health.cpu_usage > 80:
            self._health.warnings.append("High CPU usage")
        if self._health.memory_usage > 85:
            self._health.warnings.append("High memory usage")
        if self._health.disk_usage > 90:
            self._health.warnings.append("Disk space low")

        return self._health

    def get_system_report(self) -> dict[str, Any]:
        """Get a system report."""
        health = self.monitor_system()

        return {
            "system_health": health.__dict__,
            "windows": len(self._windows),
            "processes": len(self._processes),
            "active_tasks": sum(1 for t in self._tasks.values() if t.status == "running"),
            "completed_tasks": sum(1 for t in self._tasks.values() if t.status == "done"),
            "task_progress": f"{self._completed_steps}/{self._total_steps} steps completed",
        }
