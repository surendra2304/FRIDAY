# -*- coding: utf-8 -*-
"""Universe Orchestrator linking FRIDAY Agent loop to Universe API SDK (AI Universe Integration)."""

import json
import re
from typing import Any, Dict, List, Optional

from friday.agents.decomposer import TaskDecomposer
from friday.core.logging import get_logger
from friday.integrations.mock_universe import MockUniverseClient
from friday.integrations.universe_api import (
    BaseUniverseAPI,
    UniverseAgentConfig,
    UniverseExperimentResult,
    WorldConfig,
    WorldState,
)

logger = get_logger("integrations.universe_orchestrator")


class UniverseOrchestrator:
    """Coordinates high-level Universe workflows, agent spawning, and metric recording."""

    def __init__(
        self,
        universe_api: Optional[BaseUniverseAPI] = None,
        memory: Optional[Any] = None,
        decomposer: Optional[TaskDecomposer] = None,
    ) -> None:
        self.api: BaseUniverseAPI = universe_api or MockUniverseClient()
        self.memory = memory
        self.decomposer = decomposer

    def can_handle(self, user_prompt: str) -> bool:
        """Detect whether prompt requires AI Universe orchestration."""
        p = (user_prompt or "").lower()
        patterns = [
            r"\b(create|spawn|build|run)\s+(a\s+)?world\b",
            r"\b(universe|simulation)\s+(with|\d+|agents|experiment)\b",
            r"\b(run|start|execute)\s+(a\s+)?(simulation|universe experiment)\b",
            r"\b\d+\s+agents\b.*(world|simulation|experiment)",
        ]
        return any(re.search(pat, p) for pat in patterns)

    def execute_universe_goal(
        self,
        goal: str,
        agent_count: Optional[int] = None,
        steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Decompose request, control Universe API, record trial metrics, and return structured synthesis."""
        logger.info(f"Orchestrating Universe goal: {goal}")

        # 1. Parse or infer parameters if not explicitly provided
        count = agent_count
        if count is None:
            match = re.search(r"(\d+)\s+agents?", goal.lower())
            count = int(match.group(1)) if match else 5
        sim_steps = steps or 100

        # 2. Decompose subtasks if decomposer is available
        decomposition_plan = None
        if self.decomposer:
            try:
                decomposition_plan = self.decomposer.decompose(goal)
            except Exception as ex:
                logger.debug(f"Decomposition fallback: {ex}")

        # 3. Create World
        world_cfg = WorldConfig(name=f"Universe: {goal[:30]}")
        world_state: WorldState = self.api.create_world(world_cfg)

        # 4. Spawn Agents
        created_agents: List[Dict[str, Any]] = []
        for i in range(count):
            cfg = UniverseAgentConfig(
                name=f"Agent_{i+1}",
                persona=f"Simulated Persona {i+1}",
                goals=[f"Goal for Agent {i+1} in world {world_state.world_id}"],
            )
            created_agents.append(self.api.create_agent(cfg))

        # 5. Run Simulation
        self.api.start_simulation(steps=sim_steps)
        self.api.stop_simulation()

        # 6. Retrieve Experiment Results
        exp_result: UniverseExperimentResult = self.api.get_experiment_results()

        # 7. Record into SQLite experiments table (FRIDAY Lab Integration)
        if self.memory is not None and hasattr(self.memory, "record_experiment"):
            try:
                self.memory.record_experiment(
                    experiment_name=exp_result.experiment_name,
                    task_prompt=goal,
                    task_type="universe_simulation",
                    provider_name="UniverseAPI",
                    model_name="SimAgentEngine",
                    accuracy=exp_result.metrics.get("accuracy", 1.0),
                    success=exp_result.success,
                    latency_ms=exp_result.metrics.get("avg_agent_latency_ms", 50.0),
                    token_usage=0,
                    response_content=exp_result.summary,
                    metadata={
                        "world_id": exp_result.world_id,
                        "agent_count": exp_result.agent_count,
                        "total_steps": exp_result.total_steps,
                        "metrics": exp_result.metrics,
                    },
                )
                logger.info(f"Recorded Universe simulation results into experiments table for world '{exp_result.world_id}'")
            except Exception as ex:
                logger.warning(f"Could not record universe experiment in SQLite: {ex}")

        # 8. Synthesize outcome
        synthesis = (
            f"🪐 **Universe Simulation Completed**\n\n"
            f"- **World ID**: `{world_state.world_id}`\n"
            f"- **Agents Deployed**: {len(created_agents)}\n"
            f"- **Simulation Steps**: {exp_result.total_steps}\n"
            f"- **Outcome Summary**: {exp_result.summary}\n\n"
            f"**Key Metrics**:\n"
            f"- Accuracy: {exp_result.metrics.get('accuracy', 0.0)*100:.1f}%\n"
            f"- Cooperation Index: {exp_result.metrics.get('cooperation_index', 0.0):.2f}\n"
            f"- Resource Efficiency: {exp_result.metrics.get('resource_efficiency', 0.0):.2f}\n"
            f"- Average Agent Latency: {exp_result.metrics.get('avg_agent_latency_ms', 0.0):.1f}ms\n"
        )

        return {
            "world_id": world_state.world_id,
            "agent_count": len(created_agents),
            "total_steps": exp_result.total_steps,
            "metrics": exp_result.metrics,
            "synthesis": synthesis,
            "raw_result": exp_result,
            "decomposition": decomposition_plan,
        }
