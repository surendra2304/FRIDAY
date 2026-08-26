# -*- coding: utf-8 -*-
"""Perception Cache & Cost Optimization Manager for Evidence-Based Verification.9.

Orchestrates multi-level caching for visual observations, element groundings, and screen analysis:
1. Fast perceptual SHA256 / Mean Absolute Difference (MAD) image hashing.
2. Context cache with TTL and state invalidation triggers (screen diff, app switch, task change).
3. Stale-context rejection (expired caches are never returned as CURRENT_STATE).
4. Telemetry and cost instrumentation tracking suppressed calls, cache hits/misses, and API efficiency.
5. Strict quota & credential failover preservation.
"""

from dataclasses import dataclass
import hashlib
import time
from typing import Any, Dict, Optional

from friday.core.logging import get_logger
from friday.vision.base import BaseVisionProvider
from friday.vision.change_detector import compute_image_difference_ratio
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.vision.screen_base import BaseScreenCaptureProvider
from friday.vision.screen_context import ScreenContext

logger = get_logger("vision.cache_manager")


@dataclass
class CachedObservation:
    """A timestamped visual observation cached with perceptual validation hashes."""
    screen_context: ScreenContext
    image_sha256: str
    cached_at: float
    ttl_seconds: float
    active_application: Optional[str] = None
    task_id: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has surpassed its TTL."""
        return (time.time() - self.cached_at) > self.ttl_seconds

    def is_valid_for(
        self,
        current_image_bytes: bytes,
        current_app: Optional[str] = None,
        current_task_id: Optional[str] = None,
        change_threshold: float = 0.05,
    ) -> bool:
        """Check if cached observation is still valid under current environmental state."""
        if self.is_expired:
            return False

        if current_app and self.active_application and current_app != self.active_application:
            return False

        if current_task_id and self.task_id and current_task_id != self.task_id:
            return False

        # Fast exact hash match
        new_sha = hashlib.sha256(current_image_bytes).hexdigest()
        if new_sha == self.image_sha256:
            return True

        # Perceptual difference check
        diff = compute_image_difference_ratio(
            bytes.fromhex(self.image_sha256) if len(self.image_sha256) == 64 else b"",
            current_image_bytes,
        )
        return diff < change_threshold


@dataclass
class PerceptionCacheTelemetry:
    """Instrumentation metrics tracking visual perception cache performance and cost savings."""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    suppressed_api_calls: int = 0
    total_vision_api_calls: int = 0
    invalidations_by_time: int = 0
    invalidations_by_diff: int = 0
    invalidations_by_app: int = 0
    invalidations_by_task: int = 0

    @property
    def hit_ratio(self) -> float:
        return (self.cache_hits / self.total_requests) if self.total_requests > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "suppressed_api_calls": self.suppressed_api_calls,
            "total_vision_api_calls": self.total_vision_api_calls,
            "hit_ratio": round(self.hit_ratio, 4),
            "invalidations_by_time": self.invalidations_by_time,
            "invalidations_by_diff": self.invalidations_by_diff,
            "invalidations_by_app": self.invalidations_by_app,
            "invalidations_by_task": self.invalidations_by_task,
        }


class PerceptionCacheManager:
    """Optimized caching layer wrapping ScreenAnalyzer to minimize vision API costs."""

    def __init__(
        self,
        analyzer: Optional[ScreenAnalyzer] = None,
        capture_provider: Optional[BaseScreenCaptureProvider] = None,
        vision_provider: Optional[BaseVisionProvider] = None,
        default_ttl_seconds: float = 15.0,
        change_threshold: float = 0.05,
    ) -> None:
        self.analyzer = analyzer or ScreenAnalyzer(
            capture_provider=capture_provider,
            vision_provider=vision_provider,
        )
        self.default_ttl_seconds = default_ttl_seconds
        self.change_threshold = change_threshold
        self._cache: Optional[CachedObservation] = None
        self._last_image_bytes: Optional[bytes] = None
        self.telemetry = PerceptionCacheTelemetry()

    def get_screen_context_cached(
        self,
        display: str = "primary",
        user_query: Optional[str] = None,
        active_application: Optional[str] = None,
        task_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ScreenContext:
        """Retrieve screen context using cached observation if valid, else perform targeted analysis."""
        self.telemetry.total_requests += 1

        # 1. Capture current screen image
        capture_prov = self.analyzer._get_capture_provider()
        snapshot = capture_prov.capture_screen(display=display)
        if snapshot.is_error or not snapshot.image_data:
            return ScreenContext(
                summary="Screen capture failed",
                width=snapshot.width,
                height=snapshot.height,
                display_id=display,
                is_error=True,
                error_message=snapshot.error_message,
            )

        img_bytes = snapshot.image_data
        img_sha = hashlib.sha256(img_bytes).hexdigest()

        # 2. Check cache validity
        if not force_refresh and self._cache is not None:
            if self._cache.is_expired:
                self.telemetry.invalidations_by_time += 1
            elif active_application and self._cache.active_application and active_application != self._cache.active_application:
                self.telemetry.invalidations_by_app += 1
            elif task_id and self._cache.task_id and task_id != self._cache.task_id:
                self.telemetry.invalidations_by_task += 1
            elif img_sha == self._cache.image_sha256:
                # Cache HIT - exact byte match
                self.telemetry.cache_hits += 1
                self.telemetry.suppressed_api_calls += 1
                logger.debug("Perception cache HIT (exact byte match); skipped vision API call.")
                return self._cache.screen_context
            elif self._last_image_bytes is not None:
                diff = compute_image_difference_ratio(self._last_image_bytes, img_bytes)
                if diff < self.change_threshold:
                    # Cache HIT - perceptual match within threshold
                    self.telemetry.cache_hits += 1
                    self.telemetry.suppressed_api_calls += 1
                    logger.debug(f"Perception cache HIT (perceptual diff={diff:.4f} < {self.change_threshold}); skipped vision call.")
                    return self._cache.screen_context
                else:
                    self.telemetry.invalidations_by_diff += 1

        # 3. Cache MISS - Perform fresh visual analysis
        self.telemetry.cache_misses += 1
        self.telemetry.total_vision_api_calls += 1

        fresh_context = self.analyzer.analyze_current_screen(
            display=display,
            user_query=user_query,
        )

        if not fresh_context.is_error:
            self._cache = CachedObservation(
                screen_context=fresh_context,
                image_sha256=img_sha,
                cached_at=time.time(),
                ttl_seconds=self.default_ttl_seconds,
                active_application=active_application or fresh_context.active_application,
                task_id=task_id,
            )
            self._last_image_bytes = img_bytes

        return fresh_context

    def invalidate_cache(self, reason: str = "Explicit invalidation") -> None:
        """Manually purge cached observation."""
        self._cache = None
        self._last_image_bytes = None
        logger.debug(f"Perception cache invalidated: {reason}")
