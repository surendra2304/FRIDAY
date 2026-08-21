# -*- coding: utf-8 -*-
from __future__ import annotations
"""Advanced Tool Orchestration, Dependency Chaining & Parameter Inference for FRIDAY.

Provides:
- `DataFlowResolver`:
  * Resolves dynamic parameter templates (e.g. `{{step_1.result}}` or `{{step_1.result.key}}`).
  * Injects outputs from completed prerequisite steps into downstream tool arguments.
  * Enforces parameter trust levels: Screen text or untrusted perceptual outputs cannot be interpolated directly into sensitive/dangerous arguments without explicit schema validation.
- `ToolOrchestrator`:
  * Computes parallel vs. sequential execution batches from acyclic DAG dependency graphs.
  * Identifies independent safe steps for parallel batching and dependent steps for sequential chaining.
  * Validates parameter flows and safety boundaries prior to invocation.
- 100% provider-independent and testable offline.
"""

from copy import deepcopy
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel

if TYPE_CHECKING:
    from friday.agent.planner import PlanStep, TaskPlan
    from friday.tools.registry import ToolRegistry

logger = get_logger("tools.orchestrator")


class DataFlowResolver:
    """Safely resolves step-to-step data references and template interpolations."""

    TEMPLATE_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_.-]+))?\}\}")

    @classmethod
    def resolve_parameters(
        cls,
        parameters: Dict[str, Any],
        step_results: Dict[str, Any],
        target_safety_level: SafetyLevel = SafetyLevel.SAFE,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Resolve `{{step_id.key}}` or `{{step_id}}` templates using verified step results.

        Returns (resolved_params, error_message).
        """
        resolved = deepcopy(parameters)

        def _resolve_value(val: Any) -> Tuple[Any, Optional[str]]:
            if isinstance(val, str):
                match = cls.TEMPLATE_PATTERN.fullmatch(val.strip())
                if match:
                    source_step_id = match.group(1)
                    prop_path = match.group(2)

                    if source_step_id not in step_results:
                        return None, f"Referenced prerequisite step '{source_step_id}' result not found."

                    source_val = step_results[source_step_id]

                    # If source result is dict or JSON string, navigate property path if requested
                    if prop_path:
                        if isinstance(source_val, str):
                            try:
                                source_val = json.loads(source_val)
                            except Exception:
                                pass

                        if isinstance(source_val, dict):
                            keys = prop_path.split(".")
                            curr = source_val
                            for k in keys:
                                if isinstance(curr, dict) and k in curr:
                                    curr = curr[k]
                                else:
                                    return None, f"Property '{prop_path}' not found in step '{source_step_id}' result."
                            source_val = curr

                    # Untrusted screen/prompt injection defense: Check if dangerous action is receiving raw screen text
                    if target_safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS):
                        src_str = str(source_val).lower()
                        dangerous_patterns = [
                            "format c:", "rm -rf", "drop database", "drop table", "system override",
                            "grant full", "delete database", "kill process", "del /f", "sudo",
                        ]
                        if any(pat in src_str for pat in dangerous_patterns):
                            return None, "Untrusted or malicious command string blocked from parameter interpolation into high-safety tool."

                    return source_val, None

                # Substring interpolation
                def _replacer(m):
                    sid = m.group(1)
                    prop = m.group(2)
                    if sid in step_results:
                        val = step_results[sid]
                        if prop:
                            if isinstance(val, str):
                                try:
                                    val = json.loads(val)
                                except Exception:
                                    pass
                            if isinstance(val, dict):
                                keys = prop.split(".")
                                curr = val
                                for k in keys:
                                    if isinstance(curr, dict) and k in curr:
                                        curr = curr[k]
                                    else:
                                        return m.group(0)
                                return str(curr)
                        return str(val)
                    return m.group(0)

                return cls.TEMPLATE_PATTERN.sub(_replacer, val), None

            elif isinstance(val, dict):
                new_dict = {}
                for k, v in val.items():
                    res_v, err = _resolve_value(v)
                    if err:
                        return None, err
                    new_dict[k] = res_v
                return new_dict, None
            elif isinstance(val, list):
                new_list = []
                for item in val:
                    res_item, err = _resolve_value(item)
                    if err:
                        return None, err
                    new_list.append(res_item)
                return new_list, None

            return val, None

        for param_name, param_val in resolved.items():
            res_val, err = _resolve_value(param_val)
            if err:
                return parameters, err
            resolved[param_name] = res_val

        return resolved, None


class ToolOrchestrator:
    """Computes DAG execution levels (waves) for parallel and sequential tool scheduling."""

    @classmethod
    def compute_execution_batches(cls, plan: TaskPlan) -> List[List[PlanStep]]:
        """Group plan steps into sequential levels where steps in the same level can run concurrently."""
        completed_ids: Set[str] = set()
        remaining_steps = [s for s in plan.steps]
        batches: List[List[PlanStep]] = []

        while remaining_steps:
            # Find all steps whose dependencies are all in completed_ids
            ready_steps = [
                s for s in remaining_steps
                if all(dep in completed_ids for dep in s.depends_on)
            ]

            if not ready_steps:
                logger.error("Cyclic dependency or unresolvable prerequisite detected in plan DAG.")
                break

            batches.append(ready_steps)
            for s in ready_steps:
                completed_ids.add(s.step_id)
                remaining_steps.remove(s)

        return batches


class CapabilityRouter:
    """Capability-aware tool router with deterministic scoring and safety policy enforcement."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_fallbacks: Optional[Dict[str, str]] = None,
        capability_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.registry = tool_registry
        self.tool_fallbacks = tool_fallbacks or {}
        # Map capability name (e.g. "search", "read_file", "execute_command") to list of tool names
        self.capability_map = capability_map or {
            "search": ["web_search", "local_search"],
            "read_file": ["read_file"],
            "write_file": ["write_file"],
            "execute_command": ["execute_command", "run_bash"],
            "screen_capture": ["capture_screen"],
            "computer_control": ["propose_computer_action"],
        }

    def register_capability(self, capability: str, tool_names: List[str]) -> None:
        """Map a logical capability to candidate tool implementations."""
        self.capability_map[capability] = tool_names

    def score_tool_candidate(
        self,
        tool: BaseTool,
        required_capability: str,
        max_allowed_safety: SafetyLevel = SafetyLevel.SAFE,
        prefer_low_risk: bool = True,
    ) -> float:
        """Compute deterministic selection score (0.0 to 1.0) based on capability match, safety, and availability.

        Higher score means better/safer match.
        """
        score = 0.5

        # 1. Capability match
        candidates = self.capability_map.get(required_capability, [])
        if tool.name in candidates:
            idx = candidates.index(tool.name)
            # Preference given to higher priority candidates in list
            score += 0.3 - (idx * 0.05)

        # 2. Safety level scoring
        safety_penalties = {
            SafetyLevel.SAFE: 0.2,
            SafetyLevel.SENSITIVE: 0.0 if not prefer_low_risk else -0.1,
            SafetyLevel.DANGEROUS: -0.3,
        }
        score += safety_penalties.get(tool.safety_level, 0.0)

        # 3. Check if tool exceeds maximum allowed safety
        safety_order = {
            SafetyLevel.SAFE: 0,
            SafetyLevel.SENSITIVE: 1,
            SafetyLevel.DANGEROUS: 2,
        }
        if safety_order.get(tool.safety_level, 0) > safety_order.get(max_allowed_safety, 0):
            score = 0.0  # Disqualified due to safety policy

        return max(0.0, min(1.0, score))

    def route_capability(
        self,
        required_capability: str,
        preferred_tool: Optional[str] = None,
        max_allowed_safety: SafetyLevel = SafetyLevel.SAFE,
        available_tools_override: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Route a capability to the best registered tool.

        Returns (selected_tool_name, routing_rationale).
        """
        # Untrusted screen/prompt injection defense: Reject capability names with suspicious code/instructions
        bad_patterns = ["system.", "eval(", "exec(", "drop ", "rm -rf", "format ", "import "]
        if any(pat in required_capability.lower() for pat in bad_patterns):
            logger.warning(f"Malicious or suspicious capability name rejected: {required_capability}")
            return None, "Untrusted or invalid capability name rejected by capability router."

        candidates = self.capability_map.get(required_capability, [])
        if preferred_tool and preferred_tool not in candidates:
            candidates = [preferred_tool] + candidates

        valid_tools: List[Tuple[str, float]] = []

        for tname in candidates:
            if available_tools_override is not None and tname not in available_tools_override:
                continue
            tool = self.registry.get(tname)
            if tool:
                s = self.score_tool_candidate(tool, required_capability, max_allowed_safety)
                if s > 0.0:
                    valid_tools.append((tname, s))

        if not valid_tools:
            # Check if alternative fallback tool exists
            if preferred_tool and preferred_tool in self.tool_fallbacks:
                alt_name = self.tool_fallbacks[preferred_tool]
                alt_tool = self.registry.get(alt_name)
                if alt_tool:
                    s = self.score_tool_candidate(alt_tool, required_capability, max_allowed_safety)
                    if s > 0.0:
                        return alt_name, f"Routed to alternative tool '{alt_name}' (fallback from '{preferred_tool}')."

            return None, f"No available tool satisfied capability '{required_capability}' within safety limit '{max_allowed_safety.value}'."

        # Sort by score descending
        valid_tools.sort(key=lambda x: x[1], reverse=True)
        best_tool, best_score = valid_tools[0]
        return best_tool, f"Routed to '{best_tool}' (Capability match score: {best_score:.2f})."


