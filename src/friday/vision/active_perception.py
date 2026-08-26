# -*- coding: utf-8 -*-
"""Active Perception & Information Seeking Engine for Evidence-Based Verification.6.

Determines whether current multimodal / task context is sufficient to proceed or if
further targeted visual observation or memory retrieval is necessary.
Enforces strict observation bounds to prevent recursive loops, protects quotas,
handles uncertainty, and strictly ignores untrusted screen instructions attempting
to force observation loops.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from friday.core.logging import get_logger
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.vision.screen_base import BaseScreenCaptureProvider
from friday.vision.base import BaseVisionProvider
from friday.vision.screen_context import ScreenContext
from friday.vision.change_detector import ScreenChangeDetector

logger = get_logger("vision.active_perception")


class ObservationNecessity(str, Enum):
    """Decision category for active observation request."""
    SUFFICIENT = "SUFFICIENT"            # Current context is sufficient; DO NOT observe
    UNCERTAIN_STATE = "UNCERTAIN_STATE"  # Low confidence in current state; need targeted observation
    ENVIRONMENT_CHANGED = "ENVIRONMENT_CHANGED" # Significant change detected; observation needed
    ACTION_VERIFICATION = "ACTION_VERIFICATION" # Need to verify action side effect on screen
    BOUND_EXCEEDED = "BOUND_EXCEEDED"    # Max observation loop limit reached; force STOP


@dataclass
class ObservationDecision:
    """Structured decision explaining why an observation was requested or skipped."""
    necessity: ObservationNecessity
    should_observe: bool
    reason: str
    confidence: float
    target_area: Optional[str] = None
    observation_count: int = 0
    quota_exhausted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "necessity": self.necessity.value,
            "should_observe": self.should_observe,
            "reason": self.reason,
            "confidence": self.confidence,
            "target_area": self.target_area,
            "observation_count": self.observation_count,
            "quota_exhausted": self.quota_exhausted,
        }


class ActivePerceptionEngine:
    """Evaluates context sufficiency and orchestrates bounded observe-reason-observe cycles."""

    def __init__(
        self,
        capture_provider: Optional[BaseScreenCaptureProvider] = None,
        vision_provider: Optional[BaseVisionProvider] = None,
        max_consecutive_observations: int = 3,
        confidence_threshold: float = 0.75,
    ) -> None:
        self.max_consecutive_observations = max_consecutive_observations
        self.confidence_threshold = confidence_threshold
        self._analyzer = ScreenAnalyzer(
            capture_provider=capture_provider,
            vision_provider=vision_provider,
        )
        self._change_detector = ScreenChangeDetector(change_threshold=0.05)
        self._consecutive_observations: int = 0
        self._last_context: Optional[ScreenContext] = None

    def evaluate_necessity(
        self,
        current_context: Optional[ScreenContext] = None,
        task_requirement: Optional[str] = None,
        uncertainty_score: float = 0.0,
        has_executed_action: bool = False,
    ) -> ObservationDecision:
        """Evaluate whether an observation is genuinely needed.

        Args:
            current_context: Existing screen context if available.
            task_requirement: Semantic requirement or query from task.
            uncertainty_score: 0.0 (certain) to 1.0 (completely uncertain).
            has_executed_action: True if an action was just executed and requires verification.
        """
        # 1. Strict Loop Limit Check
        if self._consecutive_observations >= self.max_consecutive_observations:
            logger.warning(
                f"Active perception loop limit reached ({self._consecutive_observations}/{self.max_consecutive_observations}). Forcing SUFFICIENT."
            )
            return ObservationDecision(
                necessity=ObservationNecessity.BOUND_EXCEEDED,
                should_observe=False,
                reason="Max observation limit reached; preventing recursive loop.",
                confidence=0.5,
                observation_count=self._consecutive_observations,
            )

        # 2. Action Verification
        if has_executed_action:
            return ObservationDecision(
                necessity=ObservationNecessity.ACTION_VERIFICATION,
                should_observe=True,
                reason="Verifying UI state changes after executed action.",
                confidence=0.9,
                observation_count=self._consecutive_observations,
            )

        # 3. If no existing context, observation is mandatory
        if current_context is None or current_context.is_error:
            return ObservationDecision(
                necessity=ObservationNecessity.UNCERTAIN_STATE,
                should_observe=True,
                reason="No current visual context available.",
                confidence=0.95,
                observation_count=self._consecutive_observations,
            )

        # 4. Uncertainty & Confidence Check
        if uncertainty_score > (1.0 - self.confidence_threshold) or current_context.overall_confidence < self.confidence_threshold:
            return ObservationDecision(
                necessity=ObservationNecessity.UNCERTAIN_STATE,
                should_observe=True,
                reason=f"High uncertainty ({uncertainty_score:.2f}) or low context confidence ({current_context.overall_confidence:.2f}).",
                confidence=0.85,
                observation_count=self._consecutive_observations,
            )

        # 5. Otherwise, existing context is SUFFICIENT -> Do NOT observe
        return ObservationDecision(
            necessity=ObservationNecessity.SUFFICIENT,
            should_observe=False,
            reason="Existing visual and task context is sufficient for reasoning.",
            confidence=current_context.overall_confidence,
            observation_count=self._consecutive_observations,
        )

    def observe_if_needed(
        self,
        current_context: Optional[ScreenContext] = None,
        task_requirement: Optional[str] = None,
        uncertainty_score: float = 0.0,
        has_executed_action: bool = False,
        display: str = "primary",
    ) -> Tuple[Optional[ScreenContext], ObservationDecision]:
        """Perform targeted observation only when decision indicates necessity."""
        decision = self.evaluate_necessity(
            current_context=current_context,
            task_requirement=task_requirement,
            uncertainty_score=uncertainty_score,
            has_executed_action=has_executed_action,
        )

        if not decision.should_observe:
            return current_context, decision

        # Check for changed screen / deduplication before calling vision API
        capture_prov = self._analyzer._get_capture_provider()
        snapshot = capture_prov.capture_screen(display=display)
        if snapshot.is_error or not snapshot.image_data:
            decision.reason = f"Capture failed: {snapshot.error_message}"
            decision.should_observe = False
            return current_context, decision

        # Evaluate screen change
        has_changed, diff_ratio = self._change_detector.evaluate_change(snapshot.image_data)
        if not has_changed and current_context is not None and not has_executed_action:
            decision.necessity = ObservationNecessity.SUFFICIENT
            decision.should_observe = False
            decision.reason = f"Screen image unchanged (diff={diff_ratio:.4f}); suppressed vision call."
            return current_context, decision

        # Perform targeted analysis
        new_ctx = self._analyzer.analyze_current_screen(
            display=display,
            user_query=task_requirement,
        )
        self._consecutive_observations += 1
        decision.observation_count = self._consecutive_observations

        if new_ctx.is_error:
            if "quota" in str(new_ctx.error_message).lower() or "429" in str(new_ctx.error_message):
                decision.quota_exhausted = True
            logger.warning(f"Active perception analysis encountered error: {new_ctx.error_message}")

        self._last_context = new_ctx
        return new_ctx, decision

    def reset_loop_counter(self) -> None:
        """Reset observation counter when a task step or reasoning cycle completes."""
        self._consecutive_observations = 0
