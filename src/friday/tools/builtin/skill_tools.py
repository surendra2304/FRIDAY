"""Bridge tools that make FRIDAY's skill layer reachable from the agent loop.

The repository ships a skill layer - 24 built-in skills in
``friday.skills.registry``, each a reusable macro over several tools with its own
matching patterns and required capabilities - and nothing in the running agent
ever called it. ``FridayAgent.skill_registry`` existed as a lazy property that no
code path read, so every skill was dead code in production while the tests that
exercised them passed by calling ``skill.execute(...)`` directly.

These two tools close that gap:

* ``list_skills`` lets the model discover what the skill layer can do.
* ``run_skill`` lets the model *use* one, under the same authorization rules the
  skill's own actions require.

``run_skill`` is SENSITIVE, so the tool registry demands a scoped authorization
capability before it runs at all, and the authorizer is forwarded into the skill
so an inner tool call cannot bypass the check the tool path would have applied.
"""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.skills")


def _format_skill(skill: Any, verbose: bool = False) -> str:
    capabilities = ", ".join(skill.required_capabilities) or "none declared"
    line = f"- `{skill.name}`: {skill.description} (capabilities: {capabilities})"
    if verbose and skill.match_patterns:
        line += f"\n  trigger patterns: {'; '.join(skill.match_patterns)}"
    return line


class ListSkillsTool(BaseTool):
    """Lists the skills FRIDAY can actually dispatch."""

    name = "list_skills"
    description = (
        "List FRIDAY's registered skills (reusable multi-tool workflows such as ecosystem "
        "control, advisor briefings and software-build management). Use this when the user "
        "asks what FRIDAY can do in a domain, then use `run_skill` to run one."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional filter; only skills whose name or description contains this text are listed.",
            },
            "verbose": {
                "type": "boolean",
                "description": "Include each skill's trigger patterns.",
            },
        },
        "required": [],
    }

    def __init__(self, skill_registry: Any | None = None) -> None:
        self._skill_registry = skill_registry

    @property
    def skill_registry(self) -> Any:
        if self._skill_registry is None:
            from friday.skills.registry import skill_registry as default_registry

            self._skill_registry = default_registry
        return self._skill_registry

    def execute(self, query: str = "", verbose: bool = False, **kwargs: Any) -> ToolResult:
        try:
            skills = list(self.skill_registry.list_skills())
        except Exception as exc:
            return ToolResult(
                name=self.name,
                content=f"Could not read the skill registry: {type(exc).__name__}: {exc}",
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
            )

        text = (query or "").strip().lower()
        if text:
            skills = [s for s in skills if text in s.name.lower() or text in s.description.lower()]

        if not skills:
            scope = f" matching '{query}'" if text else ""
            return ToolResult(
                name=self.name,
                content=f"No registered skill{scope}. Run `list_skills` without a filter to see all of them.",
                safety_level=self.safety_level,
            )

        body = "\n".join(_format_skill(s, verbose=verbose) for s in sorted(skills, key=lambda s: s.name))
        header = f"{len(skills)} registered skill(s):" if len(skills) != 1 else "1 registered skill:"
        return ToolResult(
            name=self.name,
            content=f"{header}\n{body}\n\nRun one with `run_skill` (skill_name, request).",
            safety_level=self.safety_level,
        )


class RunSkillTool(BaseTool):
    """Runs one registered skill and reports exactly what it did."""

    name = "run_skill"
    description = (
        "Execute a named FRIDAY skill from the skill registry (see `list_skills`). "
        "The skill runs its own tool chain and returns its report. Requires user "
        "authorization because a skill can perform sensitive work."
    )
    safety_level = SafetyLevel.SENSITIVE
    risk_level = "SENSITIVE"
    auth_requirement = "USER"
    side_effects = ["skill_execution"]
    parameters = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Exact skill name as reported by `list_skills`.",
            },
            "request": {
                "type": "string",
                "description": "The user's original request in their own words; the skill parses it.",
            },
        },
        "required": ["skill_name", "request"],
    }

    def __init__(
        self,
        skill_registry: Any | None = None,
        authorizer: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._authorizer = authorizer
        self._tool_registry = tool_registry
        self._llm_provider = llm_provider

    @property
    def skill_registry(self) -> Any:
        if self._skill_registry is None:
            from friday.skills.registry import skill_registry as default_registry

            self._skill_registry = default_registry
        return self._skill_registry

    def execute(self, skill_name: str, request: str, **kwargs: Any) -> ToolResult:
        wanted = (skill_name or "").strip()
        if not wanted:
            return ToolResult(
                name=self.name,
                content="No skill_name was given. Call `list_skills` to see the available skills.",
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
            )

        skill = self.skill_registry.get(wanted)
        if skill is None:
            available = ", ".join(sorted(s.name for s in self.skill_registry.list_skills()))
            return ToolResult(
                name=self.name,
                content=(
                    f"There is no skill named '{wanted}'. Available skills: {available}."
                ),
                is_error=True,
                refused=True,
                safety_level=self.safety_level,
            )

        try:
            result = skill.execute(
                request or wanted,
                agent=kwargs.get("agent"),
                tool_registry=self._tool_registry,
                llm_provider=self._llm_provider,
                authorizer=self._authorizer,
            )
        except Exception as exc:
            logger.error("Skill '%s' raised: %s", wanted, exc, exc_info=True)
            return ToolResult(
                name=self.name,
                content=(
                    f"Skill '{wanted}' failed with {type(exc).__name__}: {exc}. "
                    "Nothing is being reported as done."
                ),
                is_error=True,
                safety_level=self.safety_level,
            )

        success = bool(getattr(result, "success", False))
        output = getattr(result, "output", "") or ""
        error = getattr(result, "error", None)

        if success:
            content = output
        else:
            # A skill that failed must not read as a report of work done. The
            # skill's own output is still shown, clearly labelled as a failure.
            content = f"Skill '{wanted}' did not complete. {output}".strip()
            if error:
                content += f" (reported error: {error})"

        return ToolResult(
            name=self.name,
            content=content,
            is_error=not success,
            safety_level=self.safety_level,
            metadata={
                "skill_name": getattr(result, "skill_name", wanted),
                "skill_success": success,
                "step_count": len(getattr(result, "step_results", []) or []),
            },
        )
