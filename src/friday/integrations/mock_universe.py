"""Mock Universe API Client for standalone testing and simulation (AI Universe Integration)."""

import random
from datetime import datetime, timezone
from typing import Any

from friday.integrations.universe_api import (
    BaseUniverseAPI,
    UniverseAgentConfig,
    UniverseExperimentResult,
    WorldConfig,
    WorldState,
)


class MockUniverseClient(BaseUniverseAPI):
    """Mock implementation of BaseUniverseAPI returning simulated synthetic data."""

    def __init__(self) -> None:
        self.active_world: WorldConfig | None = None
        self.agents: dict[str, UniverseAgentConfig] = {}
        self.is_running: bool = False
        self.current_step: int = 0
        self.simulation_logs: list[dict[str, Any]] = []

    def create_world(self, config: WorldConfig | None = None) -> WorldState:
        """Create and reset simulated world environment."""
        self.active_world = config or WorldConfig()
        self.agents.clear()
        self.is_running = False
        self.current_step = 0
        self.simulation_logs.clear()
        return self.get_world_state()

    def create_agent(self, agent_config: UniverseAgentConfig) -> dict[str, Any]:
        """Add simulated agent entity to world."""
        if not self.active_world:
            self.create_world()
        self.agents[agent_config.agent_id] = agent_config
        return {
            "agent_id": agent_config.agent_id,
            "name": agent_config.name,
            "persona": agent_config.persona,
            "status": "active",
        }

    def start_simulation(self, steps: int | None = 100) -> WorldState:
        """Simulate execution ticks across active agents."""
        if not self.active_world:
            self.create_world()
        self.is_running = True
        step_count = steps or 100
        self.current_step += step_count

        # Generate mock interaction events
        for i in range(min(step_count, 10)):
            self.simulation_logs.append({
                "step": self.current_step - step_count + i,
                "event": f"Interaction between agents in world '{self.active_world.world_id}'",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return self.get_world_state()

    def stop_simulation(self) -> WorldState:
        """Stop mock simulation."""
        self.is_running = False
        return self.get_world_state()

    def get_world_state(self) -> WorldState:
        """Return snapshot of current mock world."""
        w_id = self.active_world.world_id if self.active_world else "world_none"
        agent_list = [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "persona": a.persona,
                "position": (random.randint(0, 50), random.randint(0, 50)),
                "health": 100.0,
            }
            for a in self.agents.values()
        ]
        return WorldState(
            world_id=w_id,
            step=self.current_step,
            is_running=self.is_running,
            active_agents=agent_list,
            environmental_variables={"temperature": 22.5, "gravity": 9.8, "resource_density": 0.85},
        )

    def get_experiment_results(self) -> UniverseExperimentResult:
        """Compute aggregated performance metrics across simulated agents."""
        w_id = self.active_world.world_id if self.active_world else "world_none"
        agent_count = len(self.agents)
        return UniverseExperimentResult(
            world_id=w_id,
            experiment_name=f"Simulation Experiment on {w_id}",
            total_steps=self.current_step,
            agent_count=agent_count,
            metrics={
                "accuracy": 0.94,
                "cooperation_index": 0.88,
                "resource_efficiency": 0.91,
                "avg_agent_latency_ms": 42.5,
            },
            success=True,
            summary=f"Simulation successfully executed across {agent_count} agents over {self.current_step} steps.",
            raw_logs=list(self.simulation_logs),
        )
