"""Human Policy Interface for FRIDAY Ecosystem Governance.

Enables the human operator to declare, store, version, and enforce natural-language
governance policies (e.g. position caps, daily loss thresholds, mandatory approval mandates).
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("ecosystem.policy_interface")


class PolicyCategory(str, Enum):
    """Categorization of human-governed policies."""
    POSITION_SIZING = "POSITION_SIZING"
    RISK_THRESHOLD = "RISK_THRESHOLD"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    VENUE_ROUTING = "VENUE_ROUTING"
    CUSTOM = "CUSTOM"


@dataclass
class PolicyRule:
    """Individual human policy mandate."""
    policy_id: str
    category: PolicyCategory
    name: str
    natural_language_rule: str
    parameter_key: str
    parameter_value: Any
    version: int = 1
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HumanPolicyInterface:
    """Manages human-defined policies with versioning, enforcement, and conflict detection."""

    def __init__(self) -> None:
        self._policies: dict[str, PolicyRule] = {}
        self._version_counter: int = 1
        self._lock = threading.RLock()
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Initializes default production governance policies."""
        self._policies["POL_01"] = PolicyRule(
            policy_id="POL_01",
            category=PolicyCategory.POSITION_SIZING,
            name="Max Single Position Cap",
            natural_language_rule="Never trade more than 5% in a single position",
            parameter_key="max_single_position_size_pct",
            parameter_value=5.0,
            version=1,
        )

        self._policies["POL_02"] = PolicyRule(
            policy_id="POL_02",
            category=PolicyCategory.RISK_THRESHOLD,
            name="Daily Loss Alert Threshold",
            natural_language_rule="Alert me if daily loss exceeds 2%",
            parameter_key="daily_loss_alert_pct",
            parameter_value=2.0,
            version=1,
        )

        self._policies["POL_03"] = PolicyRule(
            policy_id="POL_03",
            category=PolicyCategory.HUMAN_APPROVAL,
            name="Mandatory Strategy Approval",
            natural_language_rule="Require my approval for any strategy change",
            parameter_key="require_human_approval_strategy_promotion",
            parameter_value=True,
            version=1,
        )

    def parse_and_add_policy(self, user_text: str) -> PolicyRule:
        """Parses natural language policy and records a new versioned rule."""
        with self._lock:
            self._version_counter += 1
            pid = f"POL_{len(self._policies)+1:02d}"
            clean = user_text.strip().lower()

            # Pattern 1: Position size
            match_pos = re.search(r"(?:never\s+trade\s+more\s+than|max\s+position(?:\s+size)?)\s+(\d+(?:\.\d+)?)\s*%", clean)
            if match_pos:
                val = float(match_pos.group(1))
                rule = PolicyRule(
                    policy_id=pid,
                    category=PolicyCategory.POSITION_SIZING,
                    name=f"Max Position Cap {val}%",
                    natural_language_rule=user_text.strip(),
                    parameter_key="max_single_position_size_pct",
                    parameter_value=val,
                    version=self._version_counter,
                )
                self._policies[pid] = rule
                logger.info(f"[POLICY_INTERFACE] Added position policy: {rule.name}")
                return rule

            # Pattern 2: Loss threshold
            match_loss = re.search(r"(?:daily\s+loss|loss\s+exceeds)\s+(\d+(?:\.\d+)?)\s*%", clean)
            if match_loss:
                val = float(match_loss.group(1))
                rule = PolicyRule(
                    policy_id=pid,
                    category=PolicyCategory.RISK_THRESHOLD,
                    name=f"Daily Loss Alert {val}%",
                    natural_language_rule=user_text.strip(),
                    parameter_key="daily_loss_alert_pct",
                    parameter_value=val,
                    version=self._version_counter,
                )
                self._policies[pid] = rule
                logger.info(f"[POLICY_INTERFACE] Added risk policy: {rule.name}")
                return rule

            # Pattern 3: Human approval
            if "require" in clean and "approval" in clean:
                rule = PolicyRule(
                    policy_id=pid,
                    category=PolicyCategory.HUMAN_APPROVAL,
                    name="Human Strategy Approval Mandate",
                    natural_language_rule=user_text.strip(),
                    parameter_key="require_human_approval_strategy_promotion",
                    parameter_value=True,
                    version=self._version_counter,
                )
                self._policies[pid] = rule
                logger.info(f"[POLICY_INTERFACE] Added approval policy: {rule.name}")
                return rule

            # Custom fallback
            rule = PolicyRule(
                policy_id=pid,
                category=PolicyCategory.CUSTOM,
                name="Custom Operator Mandate",
                natural_language_rule=user_text.strip(),
                parameter_key="custom_rule",
                parameter_value=user_text.strip(),
                version=self._version_counter,
            )
            self._policies[pid] = rule
            logger.info(f"[POLICY_INTERFACE] Added custom policy: {rule.name}")
            return rule

    def get_active_policies(self) -> list[PolicyRule]:
        """Returns all currently active policy rules."""
        with self._lock:
            return [p for p in self._policies.values() if p.active]

    def detect_conflicts(self) -> list[str]:
        """Scans active policies for conflicting rules."""
        with self._lock:
            conflicts: list[str] = []
            pos_rules = [p for p in self._policies.values() if p.active and p.category == PolicyCategory.POSITION_SIZING]
            if len(pos_rules) > 1:
                vals = [p.parameter_value for p in pos_rules]
                if len(set(vals)) > 1:
                    conflicts.append(f"Multiple conflicting position size caps found: {vals}")
            return conflicts

    def get_spoken_policy_summary(self) -> str:
        """Returns a conversational summary of active human policies."""
        policies = self.get_active_policies()
        conflicts = self.detect_conflicts()

        lines = [f"You currently have {len(policies)} active governance policies enforced:"]
        for p in policies:
            lines.append(f"• {p.name}: \"{p.natural_language_rule}\"")

        if conflicts:
            lines.append(f"Warning: {len(conflicts)} policy conflict detected.")

        return "\n".join(lines)
