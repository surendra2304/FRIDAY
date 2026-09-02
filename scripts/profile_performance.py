import gc
import os
import time
import tracemalloc
from typing import Dict, Any

from friday.agent.agent import FridayAgent
from friday.agent.goal import GoalUnderstandingEngine
from friday.agent.planner import GoalDecomposer
from friday.agent.executor import TaskExecutionEngine
from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.registry import ToolRegistry
from friday.vision.cache_manager import PerceptionCacheManager
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.mock_vision import MockVisionProvider


def measure_startup_and_memory():
    tracemalloc.start()
    t0 = time.perf_counter()
    settings = Settings(env="testing", llm_provider="mock")
    reg = ToolRegistry()
    mem = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, tool_registry=reg, memory=mem)
    t_startup = (time.perf_counter() - t0) * 1000

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "startup_ms": round(t_startup, 2),
        "peak_mem_kb": round(peak / 1024, 2),
        "current_mem_kb": round(current / 1024, 2),
    }


def measure_single_turn_performance():
    settings = Settings(env="testing", llm_provider="mock")
    reg = ToolRegistry()
    mem = InMemoryConversationMemory(max_messages=10)
    agent = FridayAgent(settings=settings, tool_registry=reg, memory=mem)

    tracemalloc.start()
    t0 = time.perf_counter()
    resp = agent.process_message("What is your name?")
    t_turn = (time.perf_counter() - t0) * 1000
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "turn_ms": round(t_turn, 2),
        "response_len": len(resp.content),
        "peak_mem_kb": round(peak / 1024, 2),
    }


def measure_perception_cache_throughput(iterations: int = 200):
    mock_cap = MockScreenCaptureProvider(width=200, height=200)
    mock_vis = MockVisionProvider(default_response='{"summary": "Test UI Screen"}')
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    t0 = time.perf_counter()
    for _ in range(iterations):
        cache_mgr.get_screen_context_cached()

    t_total = (time.perf_counter() - t0) * 1000

    return {
        "cache_ops": iterations,
        "total_ms": round(t_total, 2),
        "ops_per_sec": round(iterations / ((t_total) / 1000), 2),
        "cache_hits": cache_mgr.telemetry.cache_hits,
        "suppressed_api_calls": cache_mgr.telemetry.suppressed_api_calls,
    }


def main():
    print("[*] Running Phase 10.4 Local Performance & Resource Benchmark...")
    startup = measure_startup_and_memory()
    print(f"[+] Startup Time: {startup['startup_ms']} ms | Peak Memory: {startup['peak_mem_kb']} KB")

    turn = measure_single_turn_performance()
    print(f"[+] Agent Message Turn: {turn['turn_ms']} ms | Response Size: {turn['response_len']} chars | Peak Memory: {turn['peak_mem_kb']} KB")

    cache = measure_perception_cache_throughput(200)
    print(f"[+] Perception Cache: {cache['ops_per_sec']} ops/sec ({cache['total_ms']} ms for 200 operations, {cache['suppressed_api_calls']} API calls saved)")


if __name__ == "__main__":
    main()
