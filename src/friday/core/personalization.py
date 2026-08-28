# -*- coding: utf-8 -*-
"""Personalization Engine for FRIDAY Operating System.

Learns, adapts, and tunes user interaction styles continuously:
1. Response length preference (brief vs detailed) learned from completion and interruption patterns
2. Alert timing preference learned from acknowledgment latencies
3. Subsystem interest priorities learned from command query distribution
4. Communication style adaptation (concise bullets vs conversational explanations)
5. Direct user preference commands ("Change my preferences")
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("core.personalization")


@dataclass
class PersonalizationProfile:
    """Dynamic profile capturing user's learned communication habits and preferences."""
    response_length: str = "brief"  # brief, normal, detailed
    communication_style: str = "concise_bullets"  # concise_bullets, conversational, formal
    alert_timing: str = "immediate"  # immediate, batched_briefing
    subsystem_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "trading_bot": 0.35,
            "nexus": 0.25,
            "forge": 0.25,
            "ai_universe": 0.15,
        }
    )
    interruption_count: int = 0
    total_responses_delivered: int = 0
    average_ack_latency_seconds: float = 12.0
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PersonalizationEngine:
    """Tracks behavioral signals and dynamically refines FRIDAY's voice and text delivery."""

    def __init__(self, profile_file_path: Optional[str] = None) -> None:
        self.profile_file = Path(profile_file_path or os.path.join("data", "personalization_profile.json"))
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        self.profile = PersonalizationProfile()
        self._lock = threading.RLock()
        self.load_profile()

    def load_profile(self) -> None:
        """Loads saved personalization profile from disk."""
        with self._lock:
            if self.profile_file.exists():
                try:
                    with open(self.profile_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.profile = PersonalizationProfile(**data)
                    logger.info(f"[PERSONALIZATION] Loaded profile. Length: {self.profile.response_length}, Style: {self.profile.communication_style}")
                except Exception as e:
                    logger.warning(f"[PERSONALIZATION] Failed to load profile: {e}. Using defaults.")
                    self.profile = PersonalizationProfile()

    def save_profile(self) -> None:
        """Persists personalization profile to disk."""
        with self._lock:
            self.profile.last_updated = datetime.now(timezone.utc).isoformat()
            try:
                with open(self.profile_file, "w", encoding="utf-8") as f:
                    json.dump(self.profile.__dict__, f, indent=2)
            except Exception as e:
                logger.error(f"[PERSONALIZATION] Failed to save profile: {e}")

    def record_interruption(self) -> None:
        """Called when the user interrupts FRIDAY mid-speech."""
        with self._lock:
            self.profile.interruption_count += 1
            # If user frequently interrupts (> 3 times), shift to briefer responses
            if self.profile.interruption_count >= 3:
                self.profile.response_length = "brief"
                self.profile.communication_style = "concise_bullets"
                logger.info("[PERSONALIZATION] High interruption frequency detected: adapting response length to 'brief'.")
            self.save_profile()

    def record_interaction_completion(self, subsystem: str, response_length_chars: int) -> None:
        """Updates query distribution and total interactions delivered."""
        with self._lock:
            self.profile.total_responses_delivered += 1
            if subsystem in self.profile.subsystem_weights:
                # Increment weight slightly for queried subsystem
                current = self.profile.subsystem_weights[subsystem]
                self.profile.subsystem_weights[subsystem] = round(min(0.60, current + 0.02), 2)
            self.save_profile()

    def record_alert_acknowledgment(self, latency_seconds: float) -> None:
        """Tracks how quickly user acknowledges notifications."""
        with self._lock:
            # Moving average of latency
            self.profile.average_ack_latency_seconds = round(
                (self.profile.average_ack_latency_seconds * 0.8) + (latency_seconds * 0.2), 1
            )
            # If latency > 120s consistently, recommend batched delivery
            if self.profile.average_ack_latency_seconds > 120.0:
                self.profile.alert_timing = "batched_briefing"
            self.save_profile()

    def update_preferences_explicitly(self, command_text: str) -> Dict[str, Any]:
        """Handles user voice requests like 'Change my preferences to detailed responses'."""
        with self._lock:
            clean = command_text.lower()
            changes: List[str] = []

            if "detailed" in clean or "elaborate" in clean:
                self.profile.response_length = "detailed"
                self.profile.communication_style = "conversational"
                changes.append("Response detail set to DETAILED")
            elif "brief" in clean or "concise" in clean or "short" in clean:
                self.profile.response_length = "brief"
                self.profile.communication_style = "concise_bullets"
                changes.append("Response detail set to BRIEF / CONCISE BULLETS")

            if "batch" in clean or "digest" in clean:
                self.profile.alert_timing = "batched_briefing"
                changes.append("Alert delivery set to BATCHED DIGEST")
            elif "immediate" in clean or "real-time" in clean:
                self.profile.alert_timing = "immediate"
                changes.append("Alert delivery set to IMMEDIATE")

            if not changes:
                changes.append(f"Current preferences: {self.profile.response_length.upper()} detail, {self.profile.alert_timing.upper()} alerts.")

            self.save_profile()
            spoken = "Preferences updated: " + ", ".join(changes)
            return {
                "success": True,
                "spoken_response": spoken,
                "profile": self.profile.__dict__,
            }


# Default singleton instance
personalization_engine = PersonalizationEngine()
