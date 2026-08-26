# -*- coding: utf-8 -*-
"""Base Skill Abstraction for FRIDAY Skills System (Inspired by OpenJarvis).

A Skill is a cohesive macro that groups multiple tools, declared required capabilities,
and specialized system prompts to accomplish complex, reusable workflows autonomously.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class SkillExecutionResult:
    """Standard result structure for executed skills."""
    skill_name: str
    success: bool
    output: str
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "success": self.success,
            "output": self.output,
            "step_results": self.step_results,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseSkill(ABC):
    """Abstract Base Class for all FRIDAY Skills.

    Attributes:
        name: Unique string identifier for the skill.
        description: Brief explanation of what the skill does and when it should trigger.
        required_capabilities: List of required system capability permissions (e.g. ["shell_exec", "file_write"]).
        tools: List of tool names required and orchestrated by this skill.
        system_prompt: Specialized prompt or guidelines injected when executing this skill.
        match_patterns: List of regex patterns to identify user intent matching this skill.
    """

    name: str = "base_skill"
    description: str = "Base skill template"
    required_capabilities: List[str] = []
    tools: List[str] = []
    system_prompt: str = ""
    match_patterns: List[str] = []

    def can_handle(self, user_request: str) -> bool:
        """Evaluate if the user request matches this skill's triggers."""
        clean = (user_request or "").strip().lower()
        if not clean:
            return False
        for pat in self.match_patterns:
            if re.search(pat, clean, re.IGNORECASE):
                return True
        return False

    def match_score(self, user_request: str) -> float:
        """Calculate confidence score (0.0 to 1.0) for routing."""
        clean = (user_request or "").strip().lower()
        if not clean:
            return 0.0
        for pat in self.match_patterns:
            if re.search(pat, clean, re.IGNORECASE):
                return 0.95
        return 0.0

    @abstractmethod
    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Execute the skill's autonomous tool chain and return the result."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Serialize skill definition."""
        return {
            "name": self.name,
            "description": self.description,
            "required_capabilities": self.required_capabilities,
            "tools": self.tools,
            "system_prompt": self.system_prompt,
            "match_patterns": self.match_patterns,
        }
