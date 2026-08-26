# -*- coding: utf-8 -*-
"""Perception-Driven Safe Action Preparation & Grounded Element Resolver for Evidence-Based Verification.8.

Bridges structured visual UI observations and the safe ComputerActionProposal system.
Enforces:
1. Perception -> Candidate target identification -> Confidence & Ambiguity evaluation.
2. Grounded coordinate resolution from normalized BoundingBox to screen pixels.
3. Strict Proposal != Execution guarantee (generates ComputerActionProposal without executing).
4. Ambiguity handling: Requests clarification when multiple elements match target label.
5. Stale-screen detection: Validates that target element is still present before proposal authorization.
6. Untrusted visual prompt defense: Prevents instructions in screen text from generating executable actions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from friday.core.logging import get_logger
from friday.vision.actions import ComputerActionProposal, ProposalBuilder
from friday.vision.screen_context import ScreenContext
from friday.vision.ui_elements import ElementType, UIElement

logger = get_logger("vision.action_preparer")


class GroundingStatus(str, Enum):
    """Outcome of UI element visual grounding."""
    GROUNDED = "GROUNDED"                    # Exactly 1 high-confidence match found
    AMBIGUOUS = "AMBIGUOUS"                  # Multiple candidates match target label
    NOT_FOUND = "NOT_FOUND"                  # No matching element found on screen
    LOW_CONFIDENCE = "LOW_CONFIDENCE"        # Match found but below confidence threshold
    MALICIOUS_REJECTED = "MALICIOUS_REJECTED"# Visual text contains untrusted injection patterns
    STALE_SCREEN = "STALE_SCREEN"            # Screen state changed or element missing


@dataclass
class GroundedElementTarget:
    """A candidate UI element matched from natural language intent."""
    element: UIElement
    pixel_center: Tuple[int, int]
    match_score: float
    is_ambiguous: bool = False
    competing_candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element": self.element.to_dict(),
            "pixel_center": self.pixel_center,
            "match_score": self.match_score,
            "is_ambiguous": self.is_ambiguous,
            "competing_candidates": self.competing_candidates,
        }


@dataclass
class ActionPreparationResult:
    """Result of perception-driven action preparation."""
    status: GroundingStatus
    proposal: Optional[ComputerActionProposal] = None
    target: Optional[GroundedElementTarget] = None
    clarification_prompt: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == GroundingStatus.GROUNDED and self.proposal is not None


class PerceptionActionPreparer:
    """Resolves semantic intents to verified UI elements and prepares safe action proposals."""

    def __init__(
        self,
        min_confidence: float = 0.70,
        ambiguity_margin: float = 0.15,
    ) -> None:
        self.min_confidence = min_confidence
        self.ambiguity_margin = ambiguity_margin

    def resolve_target_element(
        self,
        target_description: str,
        screen_context: ScreenContext,
        element_type: Optional[ElementType] = None,
    ) -> Tuple[GroundingStatus, Optional[GroundedElementTarget], Optional[str]]:
        """Find candidate UI elements matching target_description in screen_context."""
        if not target_description or not target_description.strip():
            return GroundingStatus.NOT_FOUND, None, "Target description is empty"

        if screen_context.is_error or not screen_context.ui_elements:
            return GroundingStatus.NOT_FOUND, None, "No UI elements available in current visual context"

        # Defense against visual injection text commanding action execution
        query = target_description.lower().strip()
        malicious_markers = [
            "system override", "execute shell", "format c:", "drop database", "ignore previous",
            "eval(", "exec(", "<script>", "document.cookie", "rmdir /s /q", "you are now",
        ]
        if any(bad in query for bad in malicious_markers):
            logger.warning(f"Rejected malicious visual target instruction: {query}")
            return GroundingStatus.MALICIOUS_REJECTED, None, "Target contains prohibited instruction pattern"

        candidates: List[Tuple[UIElement, float]] = []

        for elem in screen_context.ui_elements:
            if element_type is not None and elem.element_type != element_type:
                continue

            elem_label = (elem.label or "").lower().strip()
            if not elem_label:
                continue

            # Exact match
            if elem_label == query:
                candidates.append((elem, 1.0 * elem.confidence))
            # Substring match
            elif query in elem_label or elem_label in query:
                candidates.append((elem, 0.85 * elem.confidence))
            # Partial token overlap
            else:
                q_tokens = set(query.split())
                l_tokens = set(elem_label.split())
                overlap = len(q_tokens & l_tokens)
                if overlap > 0:
                    score = (overlap / max(len(q_tokens), len(l_tokens))) * elem.confidence
                    if score >= 0.5:
                        candidates.append((elem, score))

        if not candidates:
            return GroundingStatus.NOT_FOUND, None, f"No element matching '{target_description}' was found on screen"

        # Sort by match score descending
        candidates.sort(key=lambda c: c[1], reverse=True)

        best_elem, best_score = candidates[0]

        if best_score < self.min_confidence:
            return GroundingStatus.LOW_CONFIDENCE, None, f"Best match '{best_elem.label}' has low confidence ({best_score:.2f} < {self.min_confidence:.2f})"

        # Check for ambiguity if multiple top candidates exist
        if len(candidates) > 1:
            second_elem, second_score = candidates[1]
            if (best_score - second_score) < self.ambiguity_margin:
                labels = [f"'{c[0].label}' ({c[0].element_type.value})" for c in candidates[:3]]
                clarification = f"Found multiple matching elements on screen: {', '.join(labels)}. Which one did you mean?"
                target = GroundedElementTarget(
                    element=best_elem,
                    pixel_center=best_elem.bounding_box.get_center_pixel(screen_context.width, screen_context.height),
                    match_score=best_score,
                    is_ambiguous=True,
                    competing_candidates=[c[0].label for c in candidates[:3]],
                )
                return GroundingStatus.AMBIGUOUS, target, clarification

        pixel_center = best_elem.bounding_box.get_center_pixel(screen_context.width, screen_context.height)
        target = GroundedElementTarget(
            element=best_elem,
            pixel_center=pixel_center,
            match_score=best_score,
            is_ambiguous=False,
        )
        return GroundingStatus.GROUNDED, target, None

    def prepare_click_proposal(
        self,
        target_description: str,
        screen_context: ScreenContext,
        intent: str,
        element_type: Optional[ElementType] = None,
        double: bool = False,
        right: bool = False,
    ) -> ActionPreparationResult:
        """Ground semantic click intent and construct safe ComputerActionProposal."""
        status, target, message = self.resolve_target_element(
            target_description=target_description,
            screen_context=screen_context,
            element_type=element_type,
        )

        if status == GroundingStatus.GROUNDED and target is not None:
            cx, cy = target.pixel_center
            proposal = ProposalBuilder.click(
                x=cx,
                y=cy,
                intent=f"{intent} (Target: '{target.element.label}' at {cx},{cy})",
                double=double,
                right=right,
            )
            return ActionPreparationResult(
                status=status,
                proposal=proposal,
                target=target,
            )

        if status == GroundingStatus.AMBIGUOUS:
            return ActionPreparationResult(
                status=status,
                target=target,
                clarification_prompt=message,
            )

        return ActionPreparationResult(
            status=status,
            error_message=message,
        )

    def validate_target_not_stale(
        self,
        previous_target: GroundedElementTarget,
        current_screen_context: ScreenContext,
    ) -> bool:
        """Verify target element is still present on refreshed screen before executing proposed action."""
        if current_screen_context.is_error or not current_screen_context.ui_elements:
            return False

        for elem in current_screen_context.ui_elements:
            if elem.label == previous_target.element.label and elem.element_type == previous_target.element.element_type:
                # Check center drift (< 50px tolerance)
                curr_cx, curr_cy = elem.bounding_box.get_center_pixel(
                    current_screen_context.width,
                    current_screen_context.height,
                )
                prev_cx, prev_cy = previous_target.pixel_center
                if abs(curr_cx - prev_cx) <= 50 and abs(curr_cy - prev_cy) <= 50:
                    return True
        return False
