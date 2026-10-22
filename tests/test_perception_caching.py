"""Comprehensive unit test suite for Evidence-Based Verification.9: Perception Reliability, Caching & Cost Optimization.

Tests:
1. Unchanged screen suppression (proves identical screen byte payloads do not trigger redundant vision calls).
2. Relevant changes cause required calls (meaningful screen diff triggers fresh vision analysis).
3. Cache invalidation by TTL expiration (expired context is rejected and refreshed).
4. Cache invalidation by application focus switch.
5. Cache invalidation by task context change.
6. Forced refresh bypasses cache.
7. Telemetry & cost savings metrics accurately track suppressed calls and hit ratio.
8. Quota exhaustion resilience during cache misses.
"""

import time

import pytest

from friday.vision.cache_manager import PerceptionCacheManager
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.mock_vision import MockVisionProvider


# 1. Unchanged Screen Suppression
def test_unchanged_screen_suppresses_redundant_vision_calls():
    """Verify multiple requests on an unchanged screen yield cache hits and 1 API call."""
    mock_cap = MockScreenCaptureProvider(width=800, height=600)
    mock_vis = MockVisionProvider(default_response='{"summary": "Static code editor"}')
    cache_mgr = PerceptionCacheManager(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        default_ttl_seconds=30.0,
    )

    # 1st request -> Cache MISS, invokes vision API
    ctx1 = cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 1
    assert "Static code editor" in ctx1.summary

    # 2nd and 3rd requests with same screenshot -> Cache HIT, 0 new API calls
    ctx2 = cache_mgr.get_screen_context_cached()
    ctx3 = cache_mgr.get_screen_context_cached()

    assert len(mock_vis.call_history) == 1
    assert ctx2 == ctx1
    assert ctx3 == ctx1
    assert cache_mgr.telemetry.cache_hits == 2
    assert cache_mgr.telemetry.suppressed_api_calls == 2
    assert cache_mgr.telemetry.hit_ratio == pytest.approx(2 / 3, 0.01)


# 2. Meaningful Screen Change Causes Required Call
def test_meaningful_screen_change_causes_required_call():
    """Verify changing screen image triggers fresh analysis and cache update."""
    mock_cap = MockScreenCaptureProvider(width=100, height=100, synthetic_color=(255, 0, 0))
    mock_vis = MockVisionProvider(default_response='{"summary": "Red Screen"}')
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    ctx1 = cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 1
    assert "Red Screen" in ctx1.summary

    # Screen changes significantly to Green
    mock_cap.synthetic_color = (0, 255, 0)
    mock_vis.default_response = '{"summary": "Green Screen"}'

    ctx2 = cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 2
    assert "Green Screen" in ctx2.summary
    assert cache_mgr.telemetry.cache_misses == 2


# 3. Cache Invalidation by TTL Expiration
def test_cache_invalidation_by_ttl():
    """Verify expired cache entries are discarded and not returned as CURRENT_STATE."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider(default_response='{"summary": "Temporary State"}')
    cache_mgr = PerceptionCacheManager(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        default_ttl_seconds=0.1,  # 100ms TTL
    )

    ctx1 = cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 1

    # Sleep past TTL
    time.sleep(0.15)

    ctx2 = cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 2
    assert cache_mgr.telemetry.invalidations_by_time >= 1


# 4. Cache Invalidation by Application Focus Change
def test_cache_invalidation_by_application_switch():
    """Verify switching active application invalidates cache even if image bytes are unchanged."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider(default_response='{"summary": "App Window"}')
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    cache_mgr.get_screen_context_cached(active_application="Code.exe")
    assert len(mock_vis.call_history) == 1

    # Switch app to Chrome
    cache_mgr.get_screen_context_cached(active_application="chrome.exe")
    assert len(mock_vis.call_history) == 2
    assert cache_mgr.telemetry.invalidations_by_app >= 1


# 5. Cache Invalidation by Task ID Change
def test_cache_invalidation_by_task_change():
    """Verify changing task ID triggers fresh observation."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider()
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    cache_mgr.get_screen_context_cached(task_id="task_alpha")
    assert len(mock_vis.call_history) == 1

    cache_mgr.get_screen_context_cached(task_id="task_beta")
    assert len(mock_vis.call_history) == 2
    assert cache_mgr.telemetry.invalidations_by_task >= 1


# 6. Forced Refresh Bypasses Cache
def test_forced_refresh_bypasses_cache():
    """Verify force_refresh=True always queries vision model."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider()
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    cache_mgr.get_screen_context_cached()
    assert len(mock_vis.call_history) == 1

    cache_mgr.get_screen_context_cached(force_refresh=True)
    assert len(mock_vis.call_history) == 2


# 7. Quota Exhaustion Handling on Cache Miss
def test_quota_exhaustion_on_cache_miss():
    """Verify provider quota errors on cache misses return clean error context without crashing."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider()
    mock_vis.should_fail = True
    mock_vis.failure_error = "429 Quota limit reached"
    cache_mgr = PerceptionCacheManager(capture_provider=mock_cap, vision_provider=mock_vis)

    ctx = cache_mgr.get_screen_context_cached()
    assert ctx.is_error is True
    assert "quota" in ctx.error_message.lower()
    # Errored contexts must NOT be cached
    assert cache_mgr._cache is None
