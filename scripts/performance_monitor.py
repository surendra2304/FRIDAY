import psutil
import time
from contextlib import contextmanager

@contextmanager
def monitor_performance(name: str = ""):
    """Context manager that records CPU usage (percent) and RAM usage (MB) while the block runs.
    Returns a dictionary with the average CPU percent and peak RAM MB.
    """
    process = psutil.Process()
    start_cpu = process.cpu_percent(interval=None)
    start_mem = process.memory_info().rss / (1024 * 1024)  # MB
    peak_mem = start_mem
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        end_cpu = process.cpu_percent(interval=None)
        end_mem = process.memory_info().rss / (1024 * 1024)
        peak_mem = max(peak_mem, end_mem)
        avg_cpu = (end_cpu - start_cpu) / elapsed if elapsed > 0 else 0
        result = {
            "name": name,
            "elapsed_seconds": elapsed,
            "average_cpu_percent": round(avg_cpu, 2),
            "peak_ram_mb": round(peak_mem, 2),
        }
        # Log to a file per run
        log_file = f"performance_{name.replace(' ', '_').lower()}.log" if name else "performance.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(str(result) + "\n")
        print(f"Performance for {name}: {result}")
