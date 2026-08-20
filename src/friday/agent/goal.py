# -*- coding: utf-8 -*-
"""Goal Understanding, Normalization, Classification and Hierarchical Decomposition for Phase 9.1.

Converts high-level natural language user requests into structured, validated Goal instances:
- goal_id, original_request, normalized_intent, desired_outcome, constraints, required_capabilities,
  dependencies, risk_level, authorization_requirements, success_conditions, and cancellation_conditions.
- Categorizes request types:
    * INFORMATION_REQUEST (read-only factual answers, time, search)
    * PLANNING_REQUEST (generating a plan/strategy without executing)
    * COMPUTER_CONTROL_REQUEST (mouse, keyboard, desktop UI operations)
    * MULTI_STEP_TASK (orchestrated actions across tools/steps)
    * LONG_RUNNING_TASK (background processing, async monitoring)
    * AMBIGUOUS_REQUEST (missing critical information, requires clarification)
    * PROHIBITED_REQUEST (destructive, malicious, or policy-violating)
- Hierarchical Subgoal Decomposition: Supports ordered and DAG dependency-aware subgoals without
  assuming all requests must be linear.
- Strict Security:
    * Request interpretation NEVER directly executes tools or computer control actions.
    * Untrusted visual/voice inputs are isolated and cannot override safety policies.
    * Ambiguities generate clarification prompts rather than inventing requirements.
    * Conflicting constraints and prohibited intents are explicitly flagged with risk levels.
- 100% Provider-Independent: Implemented against BaseLLMProvider without cloud vendor coupling.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from friday.core.logging import get_logger, redact_tool_args
from friday.core.types import Message, Role, SafetyLevel
from friday.llm.base import BaseLLMProvider
from friday.vision.vision_memory import redact_sensitive_visual_text

logger = get_logger("agent.goal")


class GoalRequestType(str, Enum):
    """Categorized nature of the user's intent."""
    INFORMATION_REQUEST = "INFORMATION_REQUEST"
    PLANNING_REQUEST = "PLANNING_REQUEST"
    COMPUTER_CONTROL_REQUEST = "COMPUTER_CONTROL_REQUEST"
    MULTI_STEP_TASK = "MULTI_STEP_TASK"
    LONG_RUNNING_TASK = "LONG_RUNNING_TASK"
    AMBIGUOUS_REQUEST = "AMBIGUOUS_REQUEST"
    PROHIBITED_REQUEST = "PROHIBITED_REQUEST"


class GoalRiskLevel(str, Enum):
    """Assessed risk tier of a Goal."""
    LOW = "LOW"             # Read-only, informational, non-state modifying
    MEDIUM = "MEDIUM"       # Safe modifications, single tool writes
    HIGH = "HIGH"           # Multi-file changes, sensitive tools, system config
    CRITICAL = "CRITICAL"   # Destructive commands, system-level overrides, dangerous actions


@dataclass
class SubGoal:
    """A constituent child subgoal in a hierarchical goal decomposition."""
    subgoal_id: str
    description: str
    desired_outcome: str
    dependencies: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.SAFE
    requires_confirmation: bool = False
    success_conditions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subgoal_id": self.subgoal_id,
            "description": self.description,
            "desired_outcome": self.desired_outcome,
            "dependencies": self.dependencies,
            "required_capabilities": self.required_capabilities,
            "safety_level": self.safety_level.value,
            "requires_confirmation": self.requires_confirmation,
            "success_conditions": self.success_conditions,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubGoal":
        safety_str = data.get("safety_level", SafetyLevel.SAFE.value)
        safety = SafetyLevel(safety_str) if safety_str in SafetyLevel._value2member_map_ else SafetyLevel.SAFE
        return cls(
            subgoal_id=data["subgoal_id"],
            description=data.get("description", ""),
            desired_outcome=data.get("desired_outcome", ""),
            dependencies=data.get("dependencies", []),
            required_capabilities=data.get("required_capabilities", []),
            safety_level=safety,
            requires_confirmation=data.get("requires_confirmation", False),
            success_conditions=data.get("success_conditions", []),
        )


@dataclass
class Goal:
    """Comprehensive structured representation of an analyzed user goal."""
    goal_id: str
    original_request: str
    normalized_intent: str
    desired_outcome: str
    request_type: GoalRequestType
    constraints: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    risk_level: GoalRiskLevel = GoalRiskLevel.LOW
    authorization_requirements: List[str] = field(default_factory=list)
    success_conditions: List[str] = field(default_factory=list)
    cancellation_conditions: List[str] = field(default_factory=list)
    subgoals: List[SubGoal] = field(default_factory=list)
    is_ambiguous: bool = False
    clarification_needed: Optional[str] = None
    is_prohibited: bool = False
    prohibition_reason: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize goal to dictionary."""
        return {
            "goal_id": self.goal_id,
            "original_request": self.original_request,
            "normalized_intent": self.normalized_intent,
            "desired_outcome": self.desired_outcome,
            "request_type": self.request_type.value,
            "constraints": self.constraints,
            "required_capabilities": self.required_capabilities,
            "dependencies": self.dependencies,
            "risk_level": self.risk_level.value,
            "authorization_requirements": self.authorization_requirements,
            "success_conditions": self.success_conditions,
            "cancellation_conditions": self.cancellation_conditions,
            "subgoals": [s.to_dict() for s in self.subgoals],
            "is_ambiguous": self.is_ambiguous,
            "clarification_needed": self.clarification_needed,
            "is_prohibited": self.is_prohibited,
            "prohibition_reason": self.prohibition_reason,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        req_type_str = data.get("request_type", GoalRequestType.INFORMATION_REQUEST.value)
        req_type = GoalRequestType(req_type_str) if req_type_str in GoalRequestType._value2member_map_ else GoalRequestType.INFORMATION_REQUEST
        risk_str = data.get("risk_level", GoalRiskLevel.LOW.value)
        risk = GoalRiskLevel(risk_str) if risk_str in GoalRiskLevel._value2member_map_ else GoalRiskLevel.LOW

        subgoals = [SubGoal.from_dict(s) for s in data.get("subgoals", [])]
        created = datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc)

        return cls(
            goal_id=data.get("goal_id", str(uuid.uuid4())),
            original_request=data.get("original_request", ""),
            normalized_intent=data.get("normalized_intent", ""),
            desired_outcome=data.get("desired_outcome", ""),
            request_type=req_type,
            constraints=data.get("constraints", []),
            required_capabilities=data.get("required_capabilities", []),
            dependencies=data.get("dependencies", []),
            risk_level=risk,
            authorization_requirements=data.get("authorization_requirements", []),
            success_conditions=data.get("success_conditions", []),
            cancellation_conditions=data.get("cancellation_conditions", []),
            subgoals=subgoals,
            is_ambiguous=data.get("is_ambiguous", False),
            clarification_needed=data.get("clarification_needed"),
            is_prohibited=data.get("is_prohibited", False),
            prohibition_reason=data.get("prohibition_reason"),
            created_at=created,
            metadata=data.get("metadata", {}),
        )


# Prohibited intent patterns (destructive or dangerous system attacks)
PROHIBITED_PATTERNS = [
    (re.compile(r"\b(format\s+[c-z]:|rm\s+-rf\s+/|drop\s+database|delete\s+system32)\b", re.IGNORECASE), "Destructive file or system deletion"),
    (re.compile(r"\b(override\s+system\s+policy|bypass\s+auth|disable\s+security|grant\s+root)\b", re.IGNORECASE), "Unauthorized privilege escalation or policy override"),
    (re.compile(r"\b(dump\s+passwords?|steal\s+keys?|exfiltrate\s+secrets?)\b", re.IGNORECASE), "Credential theft or exfiltration"),
]

# Computer control keywords
COMPUTER_CONTROL_KEYWORDS = [
    "click", "press", "type", "drag", "scroll", "move mouse", "double click",
    "hotkey", "minimize window", "focus application", "screen click"
]

# Long running / background keywords
LONG_RUNNING_KEYWORDS = [
    "monitor", "keep checking", "run in background", "listen for", "watch directory",
    "poll every", "continuously track", "periodically check"
]


class GoalUnderstandingEngine:
    """Analyzes and decomposes natural language requests into structured Goal models."""

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.llm = llm_provider

    def analyze_goal(
        self,
        user_request: str,
        context_summary: Optional[str] = None,
        environmental_context: Optional[str] = None,
    ) -> Goal:
        """Parse user request, classify request type, evaluate safety/risk, and formulate Goal."""
        goal_id = f"goal_{uuid.uuid4().hex[:12]}"
        clean_request = redact_sensitive_visual_text(user_request.strip())

        # 1. Prohibited Intent Detection
        for pattern, reason in PROHIBITED_PATTERNS:
            if pattern.search(clean_request):
                return Goal(
                    goal_id=goal_id,
                    original_request=clean_request,
                    normalized_intent="Blocked prohibited action",
                    desired_outcome="Refusal of dangerous action",
                    request_type=GoalRequestType.PROHIBITED_REQUEST,
                    risk_level=GoalRiskLevel.CRITICAL,
                    is_prohibited=True,
                    prohibition_reason=f"Prohibited operation: {reason}",
                    authorization_requirements=["HARD_BLOCKED"],
                    cancellation_conditions=["Immediate cancellation on dangerous intent"],
                )

        # 2. Ambiguity & Underspecification Check
        lower_req = clean_request.lower()
        if len(clean_request) < 4 or clean_request in ("do it", "fix it", "run that", "open it", "start"):
            return Goal(
                goal_id=goal_id,
                original_request=clean_request,
                normalized_intent="Ambiguous reference request",
                desired_outcome="Clarification from user",
                request_type=GoalRequestType.AMBIGUOUS_REQUEST,
                risk_level=GoalRiskLevel.LOW,
                is_ambiguous=True,
                clarification_needed=f"Could you please specify which file, application, or action you would like me to process? ('{clean_request}' is ambiguous).",
                cancellation_conditions=["User cancels clarification request"],
            )

        # 3. Check for Constraints and Conflicting Instructions
        constraints = self._extract_constraints(clean_request)
        is_conflicting, conflict_reason = self._detect_conflicting_constraints(constraints, clean_request)
        if is_conflicting:
            return Goal(
                goal_id=goal_id,
                original_request=clean_request,
                normalized_intent="Conflicting constraints in request",
                desired_outcome="Resolution of contradictory instructions",
                request_type=GoalRequestType.AMBIGUOUS_REQUEST,
                risk_level=GoalRiskLevel.MEDIUM,
                constraints=constraints,
                is_ambiguous=True,
                clarification_needed=f"Your request contains contradictory constraints: {conflict_reason}. Please clarify how you would like to proceed.",
                cancellation_conditions=["Contradiction unresolved"],
            )

        # 4. Classify Request Type
        req_type, risk_level, caps = self._classify_request_heuristics(clean_request)

        # 5. Extract Subgoals (Hierarchical Decomposition)
        subgoals = self.decompose_hierarchical_subgoals(
            request=clean_request,
            request_type=req_type,
            risk_level=risk_level,
        )

        # 6. Normalize Intent and Desired Outcome
        normalized_intent = self._normalize_intent_string(clean_request, req_type)
        desired_outcome = f"Complete task: {normalized_intent}"

        # 7. Authorization Requirements
        auth_reqs = []
        if risk_level in (GoalRiskLevel.HIGH, GoalRiskLevel.CRITICAL) or req_type == GoalRequestType.COMPUTER_CONTROL_REQUEST:
            auth_reqs.append("USER_CONFIRMATION_REQUIRED")
        if req_type == GoalRequestType.LONG_RUNNING_TASK:
            auth_reqs.append("BACKGROUND_EXECUTION_AUTHORIZED")

        # 8. Success & Cancellation Conditions
        success_conditions = [
            f"All required subgoals ({len(subgoals)} total) completed successfully",
            "Verification assertions pass without errors",
        ]
        cancellation_conditions = [
            "User explicitly cancels task execution",
            "Prerequisite step unrecoverably fails",
            "Authorization rejected by user",
        ]

        return Goal(
            goal_id=goal_id,
            original_request=clean_request,
            normalized_intent=normalized_intent,
            desired_outcome=desired_outcome,
            request_type=req_type,
            constraints=constraints,
            required_capabilities=caps,
            dependencies=[],
            risk_level=risk_level,
            authorization_requirements=auth_reqs,
            success_conditions=success_conditions,
            cancellation_conditions=cancellation_conditions,
            subgoals=subgoals,
            is_ambiguous=False,
            is_prohibited=False,
            metadata={
                "decomposed_subgoal_count": len(subgoals),
                "has_environmental_context": bool(environmental_context),
            },
        )

    def decompose_hierarchical_subgoals(
        self,
        request: str,
        request_type: GoalRequestType,
        risk_level: GoalRiskLevel,
    ) -> List[SubGoal]:
        """Decompose request into ordered or dependency-aware SubGoal nodes."""
        subgoals: List[SubGoal] = []
        lower = request.lower()

        # For multi-step compound requests (e.g. "read file X then calculate Y and search memory")
        if " then " in lower or " and then " in lower or " followed by " in lower or " after that " in lower:
            parts = re.split(r"\b(?:and\s+then|then|followed\s+by|after\s+that)\b", request, flags=re.IGNORECASE)
            prev_id: Optional[str] = None
            for idx, p in enumerate(parts, start=1):
                clean_p = p.strip(" ,.;")
                if not clean_p:
                    continue
                sg_id = f"subgoal_{idx}"
                deps = [prev_id] if prev_id else []
                subgoals.append(
                    SubGoal(
                        subgoal_id=sg_id,
                        description=clean_p,
                        desired_outcome=f"Completed {clean_p}",
                        dependencies=deps,
                        required_capabilities=["tool_execution"],
                        safety_level=SafetyLevel.SENSITIVE if risk_level in (GoalRiskLevel.HIGH, GoalRiskLevel.CRITICAL) else SafetyLevel.SAFE,
                        requires_confirmation=risk_level in (GoalRiskLevel.HIGH, GoalRiskLevel.CRITICAL),
                        success_conditions=[f"Subgoal '{sg_id}' result verified"],
                    )
                )
                prev_id = sg_id
        elif request_type == GoalRequestType.COMPUTER_CONTROL_REQUEST:
            # Standard safe computer action lifecycle: Observe -> Ground -> Propose -> Confirm -> Verify
            subgoals.append(
                SubGoal(
                    subgoal_id="subgoal_1",
                    description="Capture and observe target UI on screen",
                    desired_outcome="Target UI element localized with coordinates",
                    dependencies=[],
                    required_capabilities=["screen_capture", "ui_grounding"],
                    safety_level=SafetyLevel.SAFE,
                    requires_confirmation=False,
                )
            )
            subgoals.append(
                SubGoal(
                    subgoal_id="subgoal_2",
                    description=f"Formulate and propose action: {request}",
                    desired_outcome="Structured action proposal prepared for authorization",
                    dependencies=["subgoal_1"],
                    required_capabilities=["action_proposal"],
                    safety_level=SafetyLevel.SENSITIVE,
                    requires_confirmation=True,
                )
            )
        elif request_type == GoalRequestType.LONG_RUNNING_TASK:
            subgoals.append(
                SubGoal(
                    subgoal_id="subgoal_1",
                    description="Initialize background worker and monitoring telemetry",
                    desired_outcome="Task registered in background manager",
                    dependencies=[],
                    required_capabilities=["background_task_management"],
                    safety_level=SafetyLevel.SAFE,
                )
            )
            subgoals.append(
                SubGoal(
                    subgoal_id="subgoal_2",
                    description=f"Execute monitoring cycle for: {request}",
                    desired_outcome="Continuous progress reports until termination",
                    dependencies=["subgoal_1"],
                    required_capabilities=["periodic_polling", "progress_callback"],
                    safety_level=SafetyLevel.SAFE,
                )
            )
        else:
            # Single atomic goal
            subgoals.append(
                SubGoal(
                    subgoal_id="subgoal_1",
                    description=request,
                    desired_outcome=f"Successfully addressed: {request}",
                    dependencies=[],
                    required_capabilities=["llm_reasoning", "tool_execution"],
                    safety_level=SafetyLevel.SAFE,
                )
            )

        return subgoals

    def _classify_request_heuristics(self, request: str) -> Tuple[GoalRequestType, GoalRiskLevel, List[str]]:
        """Heuristically categorize request type, risk tier, and capability tags."""
        lower = request.lower()

        # Check computer control
        if any(k in lower for k in COMPUTER_CONTROL_KEYWORDS):
            return GoalRequestType.COMPUTER_CONTROL_REQUEST, GoalRiskLevel.HIGH, ["screen_capture", "ui_grounding", "computer_action_proposal"]

        # Check long running / background
        if any(k in lower for k in LONG_RUNNING_KEYWORDS):
            return GoalRequestType.LONG_RUNNING_TASK, GoalRiskLevel.MEDIUM, ["background_execution", "progress_reporting"]

        # Check multi-step
        if " then " in lower or " and then " in lower or " followed by " in lower:
            return GoalRequestType.MULTI_STEP_TASK, GoalRiskLevel.MEDIUM, ["multi_step_planning", "tool_orchestration"]

        # Check planning request
        if lower.startswith("plan ") or "create a plan" in lower or "how should we approach" in lower:
            return GoalRequestType.PLANNING_REQUEST, GoalRiskLevel.LOW, ["task_planning", "goal_decomposition"]

        # Default to information request
        return GoalRequestType.INFORMATION_REQUEST, GoalRiskLevel.LOW, ["llm_reasoning"]

    def _extract_constraints(self, request: str) -> List[str]:
        """Extract explicit operational constraints mentioned in prompt."""
        constraints = []
        lower = request.lower()

        if "without using" in lower:
            m = re.search(r"without using\s+([^,.;]+)", request, re.IGNORECASE)
            if m:
                constraints.append(f"DO_NOT_USE: {m.group(1).strip()}")
        if "read only" in lower or "read-only" in lower or "do not modify" in lower or "without changing" in lower:
            constraints.append("READ_ONLY_MODE")
        if "offline only" in lower or "without internet" in lower:
            constraints.append("OFFLINE_ONLY")
        if "timeout" in lower or "within " in lower:
            m = re.search(r"within\s+(\d+\s*(?:seconds?|minutes?|hours?|s|m|h))", request, re.IGNORECASE)
            if m:
                constraints.append(f"MAX_TIMEOUT: {m.group(1).strip()}")

        return constraints

    def _detect_conflicting_constraints(self, constraints: List[str], request: str) -> Tuple[bool, Optional[str]]:
        """Detect mutually contradictory instructions in user request."""
        lower = request.lower()

        # Conflict 1: Read-only request combined with explicit write/delete instruction
        is_read_only = "READ_ONLY_MODE" in constraints or "read only" in lower or "do not modify" in lower
        has_write = "write " in lower or "delete " in lower or "overwrite " in lower or "create file" in lower
        if is_read_only and has_write:
            return True, "Request specifies 'read-only/do not modify' but also requests writing or creating files"

        # Conflict 2: Offline only combined with cloud/external web query
        is_offline = "OFFLINE_ONLY" in constraints or "offline only" in lower
        has_online = "search google" in lower or "fetch website" in lower or "download from internet" in lower
        if is_offline and has_online:
            return True, "Request specifies 'offline only' but also requests online web fetching"

        return False, None

    def _normalize_intent_string(self, request: str, req_type: GoalRequestType) -> str:
        """Strip conversational filler to yield normalized intent."""
        clean = re.sub(r"^(please\s+|can you\s+|could you\s+|i want you to\s+|friday\s*,?\s*)", "", request, flags=re.IGNORECASE).strip()
        clean = clean[0].upper() + clean[1:] if clean else clean
        return clean
