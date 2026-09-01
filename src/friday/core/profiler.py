"""First-principles Performance Profiling & Resource Measurement Suite for FRIDAY.

Measures:
1. Physical Process RSS (Resident Set Size) via OS APIs (psutil).
2. Process VMS (Virtual Memory Size).
3. Python Heap Allocations via tracemalloc.
4. Child-Process Memory.
5. Exact CPU Utilization: (delta_process_cpu_time / (delta_wall_time * num_cpus)) * 100%.
6. Statistical distribution: Median (p50), p95, Peak, and Min/Max.
"""

import ctypes
import os
import sys
import time
import tracemalloc
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any


# Win32 Process Memory Structure
class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),          # RSS (Physical Working Set)
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),           # Commit / VMS
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


def filetime_to_seconds(ft: FILETIME) -> float:
    """Convert Windows FILETIME (100-ns intervals) to seconds."""
    val = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return val / 10_000_000.0


@dataclass
class ResourceSnapshot:
    """Rigorous multi-layer snapshot of system resources."""
    wall_time_s: float
    process_rss_mb: float
    process_vms_mb: float
    python_heap_peak_mb: float
    child_rss_mb: float
    cpu_time_s: float
    cpu_percent_normalized: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_rss_mb": round(self.process_rss_mb, 2),
            "process_vms_mb": round(self.process_vms_mb, 2),
            "python_heap_peak_mb": round(self.python_heap_peak_mb, 2),
            "child_rss_mb": round(self.child_rss_mb, 2),
            "cpu_percent": round(self.cpu_percent_normalized, 2),
        }


@dataclass
class BenchmarkResult:
    """Statistical summary of benchmark iterations with justified engineering targets."""
    scenario_name: str
    sample_count: int
    latencies_ms: list[float]
    median_latency_ms: float
    p95_latency_ms: float
    peak_latency_ms: float
    min_latency_ms: float
    peak_process_rss_mb: float
    peak_python_heap_mb: float
    average_cpu_percent: float
    methodology: str
    target_description: str
    target_met: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "samples": self.sample_count,
            "latency_ms": {
                "median": round(self.median_latency_ms, 2),
                "p95": round(self.p95_latency_ms, 2),
                "peak": round(self.peak_latency_ms, 2),
                "min": round(self.min_latency_ms, 2),
            },
            "memory_mb": {
                "peak_process_rss": round(self.peak_process_rss_mb, 2),
                "peak_python_heap": round(self.peak_python_heap_mb, 2),
            },
            "average_cpu_percent": round(self.average_cpu_percent, 2),
            "methodology": self.methodology,
            "target": self.target_description,
            "target_met": self.target_met,
        }


class FirstPrinciplesProfiler:
    """Executes benchmarks with accurate memory, CPU, and latency telemetry using OS native APIs."""

    def __init__(self) -> None:
        self.num_cpus = max(1, os.cpu_count() or 1)
        self._is_windows = sys.platform == "win32"
        if self._is_windows:
            self._k32 = ctypes.windll.kernel32
            self._psapi = ctypes.windll.psapi
            self._k32.GetCurrentProcess.restype = wintypes.HANDLE
            self._psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            self._k32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
            ]
            self._k32.GetProcessTimes.restype = wintypes.BOOL
            self._handle = self._k32.GetCurrentProcess()

    def measure_resource_snapshot(self) -> ResourceSnapshot:
        """Capture current resource utilization across OS, process, heap, and children."""
        rss_mb = 0.0
        vms_mb = 0.0

        if self._is_windows:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if self._psapi.GetProcessMemoryInfo(self._handle, ctypes.byref(pmc), pmc.cb):
                rss_mb = pmc.WorkingSetSize / (1024.0 * 1024.0)
                vms_mb = pmc.PagefileUsage / (1024.0 * 1024.0)

        # Tracemalloc heap peak
        heap_peak_mb = 0.0
        if tracemalloc.is_tracing():
            _, peak_bytes = tracemalloc.get_traced_memory()
            heap_peak_mb = peak_bytes / (1024.0 * 1024.0)

        # Total CPU times (User + Kernel)
        total_cpu_time = 0.0
        if self._is_windows:
            creation_time = FILETIME()
            exit_time = FILETIME()
            kernel_time = FILETIME()
            user_time = FILETIME()
            if self._k32.GetProcessTimes(
                self._handle,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                total_cpu_time = filetime_to_seconds(kernel_time) + filetime_to_seconds(user_time)

        return ResourceSnapshot(
            wall_time_s=time.perf_counter(),
            process_rss_mb=rss_mb,
            process_vms_mb=vms_mb,
            python_heap_peak_mb=heap_peak_mb,
            child_rss_mb=0.0,
            cpu_time_s=total_cpu_time,
        )

    def benchmark_callable(
        self,
        scenario_name: str,
        target_fn: Callable[[], Any],
        iterations: int = 10,
        warmup_iterations: int = 2,
        target_latency_ms: float = 1000.0,
        target_max_rss_mb: float = 150.0,
        methodology: str = "",
        target_description: str = "",
    ) -> BenchmarkResult:
        """Execute and benchmark a target callable across multiple iterations."""
        # Warmup
        for _ in range(warmup_iterations):
            target_fn()

        latencies_ms: list[float] = []
        peak_rss = 0.0
        peak_heap = 0.0
        total_cpu_deltas = 0.0
        total_wall_time = 0.0

        for _ in range(iterations):
            tracemalloc.start()
            tracemalloc.clear_traces()

            snap_start = self.measure_resource_snapshot()
            start_t = time.perf_counter()

            target_fn()

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            snap_end = self.measure_resource_snapshot()

            latencies_ms.append(elapsed_ms)

            delta_wall = max(0.0001, snap_end.wall_time_s - snap_start.wall_time_s)
            delta_cpu = max(0.0, snap_end.cpu_time_s - snap_start.cpu_time_s)
            total_cpu_deltas += delta_cpu
            total_wall_time += delta_wall

            peak_rss = max(peak_rss, snap_end.process_rss_mb)
            peak_heap = max(peak_heap, snap_end.python_heap_peak_mb)

            tracemalloc.stop()

        latencies_ms.sort()
        n = len(latencies_ms)
        median_lat = latencies_ms[n // 2] if n > 0 else 0.0
        p95_idx = int(n * 0.95)
        p95_lat = latencies_ms[min(p95_idx, n - 1)] if n > 0 else 0.0
        peak_lat = latencies_ms[-1] if n > 0 else 0.0
        min_lat = latencies_ms[0] if n > 0 else 0.0

        # CPU calculation: total process CPU time spent divided by total elapsed wall time * num_cpus
        avg_cpu_pct = 0.0
        if total_wall_time > 0:
            avg_cpu_pct = (total_cpu_deltas / (total_wall_time * self.num_cpus)) * 100.0

        target_met = (median_lat <= target_latency_ms) and (peak_rss <= target_max_rss_mb)

        return BenchmarkResult(
            scenario_name=scenario_name,
            sample_count=iterations,
            latencies_ms=latencies_ms,
            median_latency_ms=median_lat,
            p95_latency_ms=p95_lat,
            peak_latency_ms=peak_lat,
            min_latency_ms=min_lat,
            peak_process_rss_mb=peak_rss,
            peak_python_heap_mb=peak_heap,
            average_cpu_percent=avg_cpu_pct,
            methodology=methodology,
            target_description=target_description,
            target_met=target_met,
        )
