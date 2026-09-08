from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpecialistContract:
    agent_id: str
    role: str
    mission: str
    competencies: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    preferred_models: tuple[str, ...] = ()
    max_iterations: int = 8
    network: bool = False
    desktop: bool = False
    write_files: bool = False
    external_agents: bool = False
    memory_scope: str = "task"
    output_schema: str = "text"

    def validate(self):
        if not self.agent_id or not self.role:
            raise ValueError("agent identity is required")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        overlap = set(self.allowed_tools) & set(self.forbidden_tools)
        if overlap:
            raise ValueError(f"tool appears in both allow and deny lists: {sorted(overlap)}")

    def can_use(self, tool: str):
        return tool not in self.forbidden_tools and (not self.allowed_tools or tool in self.allowed_tools)
