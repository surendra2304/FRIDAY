import asyncio
from friday_deep.runtime.async_bridge import run_async_from_sync
from friday_deep.runtime.dedupe import DuplicateCallGuard
from friday_deep.runtime.executor import AgentRuntime


def test_dedupe():
    g = DuplicateCallGuard(2)
    assert g.allow("click", {"x": 1})
    assert g.allow("click", {"x": 1})
    assert not g.allow("click", {"x": 1})


def test_bridge_sync():
    async def c():
        return 7

    assert run_async_from_sync(c()) == 7


def test_bridge_live_loop():
    async def outer():
        async def c():
            return "ok"

        return run_async_from_sync(c())

    assert asyncio.run(outer()) == "ok"


def test_runtime_incomplete():
    r = AgentRuntime(max_steps=3)
    calls = []

    def it(step, dupe, b):
        calls.append(step)
        return False, "running"

    x = r.run("t", "a", it)
    assert x.status.value == "incomplete" and len(calls) == 3
