# -*- coding: utf-8 -*-
"""Temporal and environmental state tracking for multimodal perception in Phase 8.3.

Provides structured tracking of CURRENT_STATE, PREVIOUS_STATE, meaningful CHANGE events,
change timestamps, relevant task context associations, and confidence metrics over time.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from friday.core.logging import get_logger
from friday.vision.screen_context import ScreenContext
from friday.vision.ui_elements import ElementType, UIElement

logger = get_logger("vision.temporal")


class EnvironmentalChangeType(str, Enum):
    """Categorized types of environmental and desktop visual state transitions."""
    APPLICATION_FOCUS_SWITCH = "APPLICATION_FOCUS_SWITCH"
    WINDOW_TITLE_CHANGED = "WINDOW_TITLE_CHANGED"
    DIALOG_OPENED = "DIALOG_OPENED"
    DIALOG_CLOSED = "DIALOG_CLOSED"
    ERROR_APPEARED = "ERROR_APPEARED"
    ERROR_RESOLVED = "ERROR_RESOLVED"
    UI_ELEMENTS_MODIFIED = "UI_ELEMENTS_MODIFIED"
    TEXT_CONTENT_UPDATED = "TEXT_CONTENT_UPDATED"
    PROGRESS_ADVANCED = "PROGRESS_ADVANCED"
    INSIGNIFICANT_NOISE = "INSIGNIFICANT_NOISE"
    NO_CHANGE = "NO_CHANGE"


@dataclass
class EnvironmentalChange:
    """Structured record of a detected state change between consecutive observations."""
    change_id: str
    change_type: EnvironmentalChangeType
    description: str
    previous_value: Optional[str]
    current_value: Optional[str]
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_meaningful: bool = True
    relevant_task_context: Optional[str] = None
    affected_elements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "change_type": self.change_type.value,
            "description": self.description,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "is_meaningful": self.is_meaningful,
            "relevant_task_context": self.relevant_task_context,
            "affected_elements": self.affected_elements,
        }


@dataclass
class TemporalObservation:
    """Timestamped snapshot of environmental and task state."""
    observation_id: str
    screen_context: ScreenContext
    timestamp: datetime
    task_id: Optional[str] = None
    task_state: Optional[str] = None
    active_step_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "screen_context": self.screen_context.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "task_id": self.task_id,
            "task_state": self.task_state,
            "active_step_id": self.active_step_id,
        }


class TemporalEnvironmentTracker:
    """Maintains sliding-window temporal history and computes semantic environmental deltas."""

    def __init__(
        self,
        max_history_entries: int = 10,
        significance_threshold: float = 0.5,
    ) -> None:
        self.max_history_entries = max_history_entries
        self.significance_threshold = significance_threshold
        self.history: List[TemporalObservation] = []
        self.change_log: List[EnvironmentalChange] = []
        self._change_counter: int = 0

    @property
    def current_observation(self) -> Optional[TemporalObservation]:
        """Return the most recent temporal observation (CURRENT_STATE)."""
        return self.history[-1] if self.history else None

    @property
    def previous_observation(self) -> Optional[TemporalObservation]:
        """Return the preceding temporal observation (PREVIOUS_STATE)."""
        return self.history[-2] if len(self.history) >= 2 else None

    def record_observation(
        self,
        screen_context: ScreenContext,
        task_id: Optional[str] = None,
        task_state: Optional[str] = None,
        active_step_id: Optional[str] = None,
    ) -> Tuple[Optional[TemporalObservation], List[EnvironmentalChange]]:
        """Record a new observation and compute meaningful changes against previous state."""
        now = datetime.now(timezone.utc)
        obs_id = f"obs_{len(self.history) + 1}_{int(now.timestamp())}"

        new_obs = TemporalObservation(
            observation_id=obs_id,
            screen_context=screen_context,
            timestamp=now,
            task_id=task_id,
            task_state=task_state,
            active_step_id=active_step_id,
        )

        detected_changes: List[EnvironmentalChange] = []
        prev_obs = self.current_observation

        if prev_obs is not None:
            detected_changes = self._compute_environmental_delta(
                prev_obs=prev_obs,
                curr_obs=new_obs,
                task_id=task_id,
            )

        # Append to sliding history window
        self.history.append(new_obs)
        if len(self.history) > self.max_history_entries:
            self.history.pop(0)

        for chg in detected_changes:
            if chg.is_meaningful:
                self.change_log.append(chg)

        return new_obs, detected_changes

    def _compute_environmental_delta(
        self,
        prev_obs: TemporalObservation,
        curr_obs: TemporalObservation,
        task_id: Optional[str] = None,
    ) -> List[EnvironmentalChange]:
        """Analyze differences between PREVIOUS_STATE and CURRENT_STATE."""
        changes: List[EnvironmentalChange] = []
        prev_ctx = prev_obs.screen_context
        curr_ctx = curr_obs.screen_context

        # 1. Application Focus Switch
        if prev_ctx.active_application != curr_ctx.active_application:
            self._change_counter += 1
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.APPLICATION_FOCUS_SWITCH,
                    description=f"Active application changed from '{prev_ctx.active_application}' to '{curr_ctx.active_application}'",
                    previous_value=prev_ctx.active_application,
                    current_value=curr_ctx.active_application,
                    confidence=0.95,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                )
            )

        # 2. Window Title Change
        if prev_ctx.window_title != curr_ctx.window_title and curr_ctx.window_title:
            self._change_counter += 1
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.WINDOW_TITLE_CHANGED,
                    description=f"Window title updated to '{curr_ctx.window_title}'",
                    previous_value=prev_ctx.window_title,
                    current_value=curr_ctx.window_title,
                    confidence=0.90,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                )
            )

        # 3. Dialogs opened / closed
        prev_dialogs = set(prev_ctx.dialogs)
        curr_dialogs = set(curr_ctx.dialogs)

        opened = curr_dialogs - prev_dialogs
        for d in opened:
            self._change_counter += 1
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.DIALOG_OPENED,
                    description=f"Modal dialog opened: '{d}'",
                    previous_value=None,
                    current_value=d,
                    confidence=0.92,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                )
            )

        closed = prev_dialogs - curr_dialogs
        for d in closed:
            self._change_counter += 1
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.DIALOG_CLOSED,
                    description=f"Modal dialog closed: '{d}'",
                    previous_value=d,
                    current_value=None,
                    confidence=0.92,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                )
            )

        # 4. Error Appearance / Resolution
        prev_errs = set(prev_ctx.errors)
        curr_errs = set(curr_ctx.errors)

        new_errors = curr_errs - prev_errs
        for err in new_errors:
            self._change_counter += 1
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.ERROR_APPEARED,
                    description=f"New error appeared on screen: '{err}'",
                    previous_value=None,
                    current_value=err,
                    confidence=0.95,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                )
            )

        # 5. UI Elements modifications (labels, count, presence)
        prev_labels = {el.label for el in prev_ctx.ui_elements if el.label}
        curr_labels = {el.label for el in curr_ctx.ui_elements if el.label}
        added_labels = curr_labels - prev_labels
        removed_labels = prev_labels - curr_labels

        if added_labels or removed_labels:
            self._change_counter += 1
            desc_parts = []
            if added_labels:
                desc_parts.append(f"Added: {list(added_labels)[:3]}")
            if removed_labels:
                desc_parts.append(f"Removed: {list(removed_labels)[:3]}")
            changes.append(
                EnvironmentalChange(
                    change_id=f"chg_{self._change_counter}",
                    change_type=EnvironmentalChangeType.UI_ELEMENTS_MODIFIED,
                    description="UI Elements modified: " + "; ".join(desc_parts),
                    previous_value=f"{len(prev_labels)} elements",
                    current_value=f"{len(curr_labels)} elements",
                    confidence=0.85,
                    is_meaningful=True,
                    relevant_task_context=task_id,
                    affected_elements=list(added_labels | removed_labels)[:5],
                )
            )

        # If no meaningful semantic change was identified, tag as insignificant or no change
        if not changes:
            if prev_ctx.summary != curr_ctx.summary:
                self._change_counter += 1
                changes.append(
                    EnvironmentalChange(
                        change_id=f"chg_{self._change_counter}",
                        change_type=EnvironmentalChangeType.INSIGNIFICANT_NOISE,
                        description="Minor visual difference below semantic threshold",
                        previous_value=prev_ctx.summary[:60],
                        current_value=curr_ctx.summary[:60],
                        confidence=0.50,
                        is_meaningful=False,
                        relevant_task_context=task_id,
                    )
                )

        return changes

    def get_recent_meaningful_changes(self, limit: int = 5) -> List[EnvironmentalChange]:
        """Return the most recent meaningful changes."""
        return self.change_log[-limit:]

    def format_temporal_context_for_prompt(self) -> str:
        """Format temporal changes for LLM context injection."""
        if not self.change_log:
            return ""

        lines = ["=== RECENT ENVIRONMENTAL & TEMPORAL CHANGES ==="]
        for chg in self.change_log[-5:]:
            lines.append(
                f"- [{chg.timestamp.strftime('%H:%M:%S')}] [{chg.change_type.value}] {chg.description} "
                f"(conf: {chg.confidence:.2f})"
            )
        lines.append("=== END TEMPORAL CHANGES ===")
        return "\n".join(lines)
