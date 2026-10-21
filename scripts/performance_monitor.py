"""Lightweight process CPU and memory measurement for FRIDAY scripts."""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import psutil


@contextmanager
def monitor_performance(name: str = "", log_dir: str | Path | None = None):
    """Record elapsed time and process resource usage to a predictable log path.

    The log directory defaults to the repository root rather than the caller's
    current directory, so running a script from another directory does not scatter logs.
    """
    process = psutil.Process()
    start_cpu = process.cpu_percent(interval=None)
    start_mem = process.memory_info().rss / (1024 * 1024)
    peak_mem = start_mem
    start_time = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start_time
        end_cpu = process.cpu_percent(interval=None)
        end_mem = process.memory_info().rss / (1024 * 1024)
        peak_mem = max(peak_mem, end_mem)
        avg_cpu = (end_cpu - start_cpu) / elapsed if elapsed > 0 else 0
        result = {
            "name": name,
            "elapsed_seconds": round(elapsed, 4),
            "average_cpu_percent": round(avg_cpu, 2),
            "peak_ram_mb": round(peak_mem, 2),
        }
        filename = f"performance_{name.replace(' ', '_').lower()}.log" if name else "performance.log"
        destination = Path(log_dir) if log_dir is not None else Path(__file__).resolve().parents[1]
        destination.mkdir(parents=True, exist_ok=True)
        with (destination / filename).open("a", encoding="utf-8") as log:
            log.write(str(result) + "\n")
        print(f"Performance for {name}: {result}")
