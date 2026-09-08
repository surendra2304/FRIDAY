"""FRIDAY Skills System (Inspired by open-source operator frameworks)."""

from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.registry import SkillRegistry, skill_registry

__all__ = [
    "BaseSkill",
    "SkillExecutionResult",
    "SkillRegistry",
    "skill_registry",
]
