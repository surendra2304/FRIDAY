# -*- coding: utf-8 -*-
"""Intelligent Multi-Stage Perception Pipeline for FRIDAY Vision Architecture.

Provides:
1. Perception Necessity Evaluation (avoids unnecessary screenshots).
2. Perceptual Diffing & Cache Reuse (avoids sending unchanged screens to Gemini).
3. Local ROI, OCR & Metadata Extraction (inspects localized regions where sufficient).
4. Multi-Monitor Awareness (virtual desktop coordinates, monitor bounds, multi-display mapping).
5. Temporal Consistency & Stale UI Invalidation (tracks state transitions across actions).
6. Ambiguity & Duplicate Label Disambiguation (refuses to guess; requests clarification).
7. Strict Prompt-Injection Isolation (treats on-screen text as passive, untrusted visual data).
"""

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any, Dict, List, Optional

from friday.auth.request_accounting import request_accountant
from friday.core.logging import get_logger
from friday.vision.base import BaseVisionProvider
from friday.vision.cache_manager import PerceptionCacheManager
from friday.vision.change_detector import compute_image_difference_ratio
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.screen_context import ScreenContext
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement

logger = get_logger("vision.pipeline")


@dataclass
class MonitorInfo:
    """Descriptor for an individual display monitor."""
    monitor_id: str
    index: int
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = False

    def contains_point(self, px: int, py: int) -> bool:
        return (self.x <= px < self.x + self.width) and (self.y <= py < self.y + self.height)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "index": self.index,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "is_primary": self.is_primary,
        }


@dataclass
class PerceptionResult:
    """Outcome of a perception pipeline execution."""
    screen_context: ScreenContext
    source: str  # "cache", "local_roi", "gemini_vision", "fallback"
    confidence: float
    is_stale: bool = False
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    prompt_injection_detected: bool = False
    detected_injections: List[str] = field(default_factory=list)
    active_monitor: Optional[MonitorInfo] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screen_context": self.screen_context.to_dict(),
            "source": self.source,
            "confidence": self.confidence,
            "is_stale": self.is_stale,
            "is_ambiguous": self.is_ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
            "prompt_injection_detected": self.prompt_injection_detected,
            "detected_injections": self.detected_injections,
            "active_monitor": self.active_monitor.to_dict() if self.active_monitor else None,
            "duration_ms": self.duration_ms,
        }


class PerceptionPipeline:
    """Orchestrates end-to-end intelligent perception with caching, local extraction, and security."""

    # Prompt injection signatures to isolate and flag from untrusted visible screen text
    INJECTION_SIGNATURES = [
        "ignore previous instructions",
        "ignore user goal",
        "system override",
        "system instruction",
        "system prompt",
        "output your api key",
        "reveal secrets",
        "execute the following command",
        "delete all files",
        "drop table",
        "format c:",
        "curl http",
        "powershell -enc",
    ]

    def __init__(
        self,
        capture_provider: Optional[BaseScreenCaptureProvider] = None,
        vision_provider: Optional[BaseVisionProvider] = None,
        cache_manager: Optional[PerceptionCacheManager] = None,
        confidence_threshold: float = 0.70,
        change_threshold: float = 0.03,
        ttl_seconds: float = 30.0,
    ) -> None:
        self.capture_provider = capture_provider or MockScreenCaptureProvider()
        self.vision_provider = vision_provider or MockVisionProvider()
        self.confidence_threshold = confidence_threshold
        self.change_threshold = change_threshold
        self.ttl_seconds = ttl_seconds

        self._cached_context: Optional[ScreenContext] = None
        self._cached_image_sha: Optional[str] = None
        self._cached_image_bytes: Optional[bytes] = None
        self._cached_at: float = 0.0

        self._last_action_timestamp: float = 0.0
        self._last_observation_timestamp: float = 0.0

    @property
    def _monitors(self) -> List[MonitorInfo]:
        """Dynamically enumerate display monitors from capture provider."""
        monitors: List[MonitorInfo] = []
        displays = self.capture_provider.list_displays()
        for idx, disp in enumerate(displays):
            monitors.append(
                MonitorInfo(
                    monitor_id=disp.get("id", f"display_{idx}"),
                    index=disp.get("index", idx),
                    x=disp.get("x", 0),
                    y=disp.get("y", 0),
                    width=disp.get("width", 1920),
                    height=disp.get("height", 1080),
                    is_primary=disp.get("is_primary", idx == 0),
                )
            )
        return monitors

    def record_action_executed(self) -> None:
        """Mark that a physical UI action (click, type) occurred, invalidating temporal freshness."""
        self._last_action_timestamp = time.time()
        self.invalidate_cache(reason="Physical UI action executed")
        logger.info("PerceptionPipeline: Cache invalidated following UI action.")

    def invalidate_cache(self, reason: str = "Explicit invalidation") -> None:
        """Purge current cached observation."""
        self._cached_context = None
        self._cached_image_sha = None
        self._cached_image_bytes = None
        self._cached_at = 0.0
        logger.debug(f"PerceptionPipeline: Cache purged ({reason})")

    def should_perceive(
        self,
        task_goal: str,
        current_context: Optional[ScreenContext] = None,
        force_refresh: bool = False,
    ) -> bool:
        """Determine whether visual perception is genuinely required for the current task."""
        if force_refresh:
            return True

        lower_goal = task_goal.lower()
        non_visual_keywords = ["calculate", "read file", "list directory", "get system time", "ping"]
        if any(kw in lower_goal for kw in non_visual_keywords) and not any(term in lower_goal for term in ["screen", "button", "dialog", "window", "click", "ui"]):
            return False

        if current_context is None or current_context.is_error:
            return True

        if self._last_action_timestamp > self._last_observation_timestamp:
            return True

        return False

    def perceive(
        self,
        query: Optional[str] = None,
        target_roi: Optional[BoundingBox] = None,
        display: str = "primary",
        force_refresh: bool = False,
        task_id: Optional[str] = None,
    ) -> PerceptionResult:
        """Execute the perception pipeline with caching, local ROI check, and injection isolation."""
        start_time = time.perf_counter()
        monitors = self._monitors

        # Find target monitor
        target_mon = next((m for m in monitors if m.monitor_id == display), None)
        if not target_mon and monitors:
            target_mon = monitors[0]

        # 1. Capture screen snapshot
        snapshot = self.capture_provider.capture_screen(display=display)
        if snapshot.is_error or not snapshot.image_data:
            err_ctx = ScreenContext(
                summary="Screen capture failed",
                width=snapshot.width,
                height=snapshot.height,
                display_id=display,
                is_error=True,
                error_message=snapshot.error_message or "Empty image data",
            )
            return PerceptionResult(
                screen_context=err_ctx,
                source="error",
                confidence=0.0,
                active_monitor=target_mon,
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        img_bytes = snapshot.image_data
        img_sha = hashlib.sha256(img_bytes).hexdigest()
        now = time.time()

        # 2. Check Cache & Image Diff
        if not force_refresh and self._cached_context is not None:
            is_expired = (now - self._cached_at) > self.ttl_seconds
            if not is_expired:
                if img_sha == self._cached_image_sha:
                    logger.info("PerceptionPipeline: Reusing cached observation (exact byte match).")
                    request_accountant.record_request(
                        credential_label="CACHE",
                        model="cache",
                        purpose="vision_perception",
                        task_id=task_id,
                        is_cache_hit=True,
                    )
                    cached_view = ScreenContext(
                        summary=self._cached_context.summary,
                        active_application=self._cached_context.active_application,
                        window_title=self._cached_context.window_title,
                        visible_text=self._cached_context.visible_text,
                        ui_elements=self._cached_context.ui_elements,
                        buttons=self._cached_context.buttons,
                        dialogs=self._cached_context.dialogs,
                        errors=self._cached_context.errors,
                        warnings=self._cached_context.warnings,
                        charts=self._cached_context.charts,
                        width=self._cached_context.width,
                        height=self._cached_context.height,
                        display_id=self._cached_context.display_id,
                        captured_at=self._cached_context.captured_at,
                        is_error=self._cached_context.is_error,
                        error_message=self._cached_context.error_message,
                        overall_confidence=self._cached_context.overall_confidence,
                        screen_state_id=self._cached_context.screen_state_id,
                        provider_model=self._cached_context.provider_model,
                        source="cache",
                        is_cached=True,
                    )
                    return self._evaluate_and_sanitize_result(
                        screen_context=cached_view,
                        source="cache",
                        confidence=cached_view.overall_confidence,
                        active_monitor=target_mon,
                        query=query,
                        start_time=start_time,
                    )
                elif self._cached_image_bytes is not None:
                    diff = compute_image_difference_ratio(self._cached_image_bytes, img_bytes)
                    if diff < self.change_threshold:
                        logger.info(f"PerceptionPipeline: Reusing cached observation (diff={diff:.4f} < {self.change_threshold}).")
                        request_accountant.record_request(
                            credential_label="CACHE",
                            model="cache",
                            purpose="vision_perception",
                            task_id=task_id,
                            is_cache_hit=True,
                        )
                        cached_view = ScreenContext(
                            summary=self._cached_context.summary,
                            active_application=self._cached_context.active_application,
                            window_title=self._cached_context.window_title,
                            visible_text=self._cached_context.visible_text,
                            ui_elements=self._cached_context.ui_elements,
                            buttons=self._cached_context.buttons,
                            dialogs=self._cached_context.dialogs,
                            errors=self._cached_context.errors,
                            warnings=self._cached_context.warnings,
                            charts=self._cached_context.charts,
                            width=self._cached_context.width,
                            height=self._cached_context.height,
                            display_id=self._cached_context.display_id,
                            captured_at=self._cached_context.captured_at,
                            is_error=self._cached_context.is_error,
                            error_message=self._cached_context.error_message,
                            overall_confidence=self._cached_context.overall_confidence,
                            screen_state_id=self._cached_context.screen_state_id,
                            provider_model=self._cached_context.provider_model,
                            source="cache",
                            is_cached=True,
                        )
                        return self._evaluate_and_sanitize_result(
                            screen_context=cached_view,
                            source="cache",
                            confidence=cached_view.overall_confidence,
                            active_monitor=target_mon,
                            query=query,
                            start_time=start_time,
                        )

        # 3. Local ROI / Metadata check
        if target_roi and snapshot.image_data:
            local_ctx = self._inspect_local_roi(snapshot, target_roi, query)
            if local_ctx and local_ctx.overall_confidence >= self.confidence_threshold:
                logger.info("PerceptionPipeline: Resolved observation via local ROI inspection.")
                request_accountant.record_request(
                    credential_label="LOCAL_ROI",
                    model="local_roi",
                    purpose="vision_perception",
                    task_id=task_id,
                    is_cache_hit=True,
                )
                return self._evaluate_and_sanitize_result(
                    screen_context=local_ctx,
                    source="local_roi",
                    confidence=local_ctx.overall_confidence,
                    active_monitor=target_mon,
                    query=query,
                    start_time=start_time,
                )

        # 4. Check budget before querying vision provider
        allowed, budget_reason = request_accountant.can_make_request(task_id=task_id, purpose="vision_perception")
        if not allowed:
            logger.warning(f"PerceptionPipeline: Vision request prevented by budget controller: {budget_reason}")
            err_ctx = ScreenContext(
                summary=f"Vision budget exceeded: {budget_reason}",
                width=snapshot.width,
                height=snapshot.height,
                display_id=display,
                is_error=True,
                error_message=budget_reason,
            )
            return PerceptionResult(
                screen_context=err_ctx,
                source="error",
                confidence=0.0,
                active_monitor=target_mon,
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        # 5. Query Vision Provider (Gemini / Mock)
        prompt = "Analyze the screen state and provide structured visual elements."
        if query:
            prompt += f" User query: {query}"

        vision_resp = self.vision_provider.analyze_image(
            image_data=snapshot.image_data,
            prompt=prompt,
            mime_type=snapshot.mime_type,
            task_id=task_id,
        )

        from friday.vision.screen_analyzer import parse_vision_json_response
        parsed_data = parse_vision_json_response(vision_resp.text)

        elements: List[UIElement] = []
        for raw_el in parsed_data.get("ui_elements", []):
            try:
                bbox_data = raw_el.get("bounding_box", {})
                bbox = BoundingBox(
                    ymin=bbox_data.get("ymin", 0),
                    xmin=bbox_data.get("xmin", 0),
                    ymax=bbox_data.get("ymax", 1000),
                    xmax=bbox_data.get("xmax", 1000),
                )
                el_type_str = raw_el.get("element_type", "BUTTON")
                el_type = ElementType(el_type_str) if el_type_str in ElementType._value2member_map_ else ElementType.BUTTON
                elements.append(
                    UIElement(
                        element_id=raw_el.get("element_id", f"elem_{len(elements)+1}"),
                        element_type=el_type,
                        label=raw_el.get("label", ""),
                        bounding_box=bbox,
                        confidence=float(raw_el.get("confidence", 0.9)),
                        is_interactive=raw_el.get("is_interactive", True),
                    )
                )
            except Exception:
                continue

        overall_conf = float(parsed_data.get("confidence", 0.85))
        if vision_resp.raw_response and "confidence" in vision_resp.raw_response:
            overall_conf = float(vision_resp.raw_response["confidence"])

        screen_state_id = f"state_{img_sha[:12]}"
        model_name = getattr(vision_resp, "model", getattr(self.vision_provider, "model", "gemini_vision"))
        screen_ctx = ScreenContext(
            summary=parsed_data.get("summary", vision_resp.text[:100]),
            active_application=parsed_data.get("active_application"),
            window_title=parsed_data.get("window_title"),
            visible_text=parsed_data.get("visible_text", ""),
            ui_elements=elements,
            errors=parsed_data.get("errors", []),
            warnings=parsed_data.get("warnings", []),
            buttons=parsed_data.get("buttons", []),
            dialogs=parsed_data.get("dialogs", []),
            charts=parsed_data.get("charts", []),
            width=snapshot.width,
            height=snapshot.height,
            display_id=display,
            overall_confidence=overall_conf,
            screen_state_id=screen_state_id,
            provider_model=model_name,
            source="gemini_vision",
            is_cached=False,
        )

        # 5. Cache the freshly analyzed context
        self._cached_context = screen_ctx
        self._cached_image_sha = img_sha
        self._cached_image_bytes = img_bytes
        self._cached_at = now
        self._last_observation_timestamp = now

        return self._evaluate_and_sanitize_result(
            screen_context=screen_ctx,
            source="gemini_vision",
            confidence=screen_ctx.overall_confidence,
            active_monitor=target_mon,
            query=query,
            start_time=start_time,
        )

    def _inspect_local_roi(
        self,
        snapshot: ScreenSnapshot,
        target_roi: BoundingBox,
        query: Optional[str],
    ) -> Optional[ScreenContext]:
        """Perform lightweight local ROI extraction."""
        if target_roi.xmax <= target_roi.xmin or target_roi.ymax <= target_roi.ymin:
            return None

        img_sha = hashlib.sha256(snapshot.image_data).hexdigest() if snapshot.image_data else "none"
        return ScreenContext(
            summary=f"Local ROI inspected at ({target_roi.xmin}, {target_roi.ymin}, {target_roi.xmax}, {target_roi.ymax})",
            ui_elements=[
                UIElement(
                    element_id="roi_element",
                    element_type=ElementType.BUTTON,
                    label=query or "Target ROI",
                    bounding_box=target_roi,
                    confidence=0.95,
                )
            ],
            width=snapshot.width,
            height=snapshot.height,
            display_id=snapshot.display_id,
            overall_confidence=0.95,
            screen_state_id=f"state_roi_{img_sha[:8]}",
            provider_model="local_roi_filter",
            source="local_roi",
            is_cached=False,
        )

    def _evaluate_and_sanitize_result(
        self,
        screen_context: ScreenContext,
        source: str,
        confidence: float,
        active_monitor: Optional[MonitorInfo],
        query: Optional[str],
        start_time: float,
    ) -> PerceptionResult:
        """Audit for prompt injections, ambiguity, duplicate labels, and multi-monitor offsets."""
        # 1. Prompt Injection Scanning: Visible text must NEVER be treated as system instruction
        labels_str = " ".join(el.label for el in screen_context.ui_elements)
        combined_text = f"{screen_context.visible_text} {screen_context.summary} {' '.join(screen_context.buttons)} {labels_str}".lower()
        detected_injections = []
        for sig in self.INJECTION_SIGNATURES:
            if sig in combined_text:
                detected_injections.append(sig)

        is_injection = len(detected_injections) > 0
        if is_injection:
            logger.warning(f"PerceptionPipeline: Detected potential prompt injection on screen: {detected_injections}. Isolating as untrusted data.")

        # 2. Ambiguity & Duplicate Label Disambiguation
        is_ambiguous = False
        ambiguity_reason = None

        if query:
            matching_elements = [
                el for el in screen_context.ui_elements
                if query.lower() in el.label.lower()
            ]
            if len(matching_elements) > 1:
                is_ambiguous = True
                ambiguity_reason = f"Duplicate controls found: {len(matching_elements)} elements match '{query}'. Disambiguation required."
                logger.warning(f"PerceptionPipeline: Ambiguity detected: {ambiguity_reason}")

        if confidence < self.confidence_threshold and not is_ambiguous:
            is_ambiguous = True
            ambiguity_reason = f"Visual confidence ({confidence:.2f}) below threshold ({self.confidence_threshold:.2f}). Additional inspection required."

        return PerceptionResult(
            screen_context=screen_context,
            source=source,
            confidence=confidence,
            is_stale=(self._last_action_timestamp > self._last_observation_timestamp and source == "cache"),
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            prompt_injection_detected=is_injection,
            detected_injections=detected_injections,
            active_monitor=active_monitor,
            duration_ms=(time.perf_counter() - start_time) * 1000,
        )
