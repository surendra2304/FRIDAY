"""Cross-Session Learning Engine for FRIDAY.

Extracts long-term patterns across user sessions:
1. Recurring command sequences -> Suggests proactive shortcuts (e.g. trading status then forge status)
2. User preference learning: response length (brief/detailed), alert timing (immediate/batched), subsystem interest weights
3. Behavioral contradiction detection: surfaces conflicts between user instructions and behavior
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("memory.cross_session")


@dataclass
class CommandPattern:
    """Recurring sequential command workflow discovered across sessions."""
    pattern_id: str
    sequence: list[str]
    occurrence_count: int
    suggested_shortcut: str
    time_window: str = "morning"


@dataclass
class LearnedPreferences:
    """Dynamically adapted user preferences based on cross-session history."""
    response_length: str = "brief"  # brief, normal, detailed
    alert_timing: str = "immediate"  # immediate, batched
    subsystem_interest_weights: dict[str, float] = field(
        default_factory=lambda: {
            "trading_bot": 0.35,
            "nexus": 0.25,
            "forge": 0.25,
            "ai_universe": 0.15,
        }
    )
    confidence: float = 0.88


@dataclass
class ContradictionAlert:
    """Alert surfaced when user behavior contradicts explicit settings."""
    rule_statement: str
    conflicting_behavior: str
    explanation: str
    recommendation: str
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CrossSessionLearning:
    """Extracts shortcuts, adapts preferences, and detects behavioral contradictions."""

    def __init__(self) -> None:
        self.session_command_history: list[dict[str, Any]] = []
        self.discovered_patterns: dict[str, CommandPattern] = {}
        self.preferences = LearnedPreferences()
        self._lock = threading.RLock()

    def record_command(self, command: str, subsystem: str) -> None:
        """Records command entry into multi-session sequence tracker."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.session_command_history.append({
                "command": command.strip().lower(),
                "subsystem": subsystem,
                "timestamp": now,
            })
            self._update_subsystem_interest(subsystem)

    def _update_subsystem_interest(self, subsystem: str) -> None:
        """Dynamically shifts interest weights toward frequently queried subsystems."""
        if subsystem in self.preferences.subsystem_interest_weights:
            total = len(self.session_command_history)
            if total >= 5:
                counts = {}
                for item in self.session_command_history:
                    sub = item["subsystem"]
                    counts[sub] = counts.get(sub, 0) + 1
                for sub, count in counts.items():
                    self.preferences.subsystem_interest_weights[sub] = round(count / total, 2)

    def detect_recurring_shortcuts(self) -> list[CommandPattern]:
        """Discovers command sequences that occur consecutively (e.g. trading status -> forge status)."""
        with self._lock:
            if len(self.session_command_history) < 2:
                return list(self.discovered_patterns.values())

            # Detect trading_status followed by forge_status
            subs = [c["subsystem"] for c in self.session_command_history]
            for i in range(len(subs) - 1):
                if subs[i] == "trading_bot" and subs[i + 1] == "forge":
                    pat_id = "seq_trading_forge_morning"
                    if pat_id not in self.discovered_patterns:
                        self.discovered_patterns[pat_id] = CommandPattern(
                            pattern_id=pat_id,
                            sequence=["trading_status", "forge_status"],
                            occurrence_count=1,
                            suggested_shortcut="Offer combined Trading & Forge Morning Briefing",
                            time_window="morning",
                        )
                    else:
                        self.discovered_patterns[pat_id].occurrence_count += 1

            return list(self.discovered_patterns.values())

    def learn_user_preferences(self, explicit_feedback: str | None = None) -> LearnedPreferences:
        """Learns and refines user preference model."""
        with self._lock:
            if explicit_feedback:
                clean = explicit_feedback.lower()
                if "shorter" in clean or "brief" in clean or "concise" in clean:
                    self.preferences.response_length = "brief"
                elif "detailed" in clean or "elaborate" in clean:
                    self.preferences.response_length = "detailed"

                if "batch" in clean or "digest" in clean:
                    self.preferences.alert_timing = "batched"
                elif "immediate" in clean or "real-time" in clean:
                    self.preferences.alert_timing = "immediate"

            return self.preferences

    def detect_contradictions(
        self,
        negative_rule: str,
        recent_commands: list[str] | None = None,
    ) -> ContradictionAlert | None:
        """Detects contradictions between explicit negative rules and actual usage."""
        with self._lock:
            rule_clean = negative_rule.lower()
            cmds = recent_commands or [c["command"] for c in self.session_command_history[-10:]]

            # Example: user says "stop alerting me about bitcoin" but queries "bitcoin positions" 3 times
            if "stop alerting me about" in rule_clean or "don't show me" in rule_clean:
                target_topic = rule_clean.replace("stop alerting me about", "").replace("don't show me", "").strip()
                matches = [c for c in cmds if target_topic in c]
                if len(matches) >= 2:
                    alert = ContradictionAlert(
                        rule_statement=negative_rule,
                        conflicting_behavior=f"User manually requested '{target_topic}' {len(matches)} times recently.",
                        explanation=f"You configured a rule to mute alerts for '{target_topic}', but frequently query it manually.",
                        recommendation=f"Would you like me to re-enable subtle notifications for '{target_topic}'?",
                    )
                    logger.warning(f"[CONTRADICTION_DETECTOR] {alert.explanation}")
                    return alert

            return None


# Default singleton instance
cross_session_learning = CrossSessionLearning()
