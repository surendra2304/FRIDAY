"""Universe Orchestrator linking FRIDAY Agent loop to Universe API SDK (AI Universe Integration)."""

import asyncio
import re
from typing import Any

from friday.planning.planner import DynamicTaskPlanner
from friday.core.logging import get_logger
from friday.core.task_envelope import TaskEnvelope, TaskResult, TaskPriority
from friday.ecosystem.fleet_client import fleet_client
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
        universe_api: BaseUniverseAPI | None = None,
        memory: Any | None = None,
        planner: DynamicTaskPlanner | None = None,
    ) -> None:
        self.api: BaseUniverseAPI | None = universe_api
        self.fleet = fleet_client
        self.memory = memory
        self.planner = planner

    def _live_path_without_universe_api(self, goal: str, decomposition_plan: Any) -> dict[str, Any]:
        """No Universe API is configured, so the goal is not executed.

        A real fleet health probe is attempted so the caller sees who answered.
        The result is never reported as dispatched, and peer counts are never invented.
        """
        logger.info("No Universe API configured; probing fleet and refusing a fabricated dispatch")
        probe = self._probe_live_fleet()
        if not probe.get("ok"):
            error = str(probe.get("error") or "fleet probe failed")
            return {
                "world_id": None,
                "agent_count": 0,
                "total_steps": 0,
                "metrics": {},
                "synthesis": (
                    "No Universe API is configured, so this goal was not executed. "
                    f"The live fleet probe failed: {error}"
                ),
                "raw_result": {
                    "status": "not_executed",
                    "reason": "no_universe_api",
                    "goal": goal,
                    "error": error,
                },
                "decomposition": decomposition_plan,
            }

        meta = probe["metadata"]
        online = int(meta.get("online_count") or 0)
        total = int(meta.get("total_count") or 0)
        return {
            "world_id": None,
            "agent_count": online,
            "total_steps": 0,
            "metrics": {
                "online_count": online,
                "total_count": total,
                "real_agents": online,
            },
            "synthesis": (
                "No Universe API is configured, so this goal was not executed. "
                f"Live fleet probe: {online} of {total} peers answered."
            ),
            "raw_result": {
                "status": "not_executed",
                "reason": "no_universe_api",
                "goal": goal,
                "fleet": {
                    "online_count": online,
                    "total_count": total,
                },
            },
            "decomposition": decomposition_plan,
        }

    def _probe_live_fleet(self) -> dict[str, Any]:
        """Call FleetClient.get_fleet_summary. Never invent a successful dispatch."""

        async def _call() -> Any:
            return await self.fleet.get_fleet_summary()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                summary = asyncio.run(_call())
            except Exception as ex:
                logger.warning(f"Live fleet probe failed: {ex}")
                return {"ok": False, "error": str(ex)}
        else:
            return {
                "ok": False,
                "error": "event loop already running; refusing a fake dispatch",
            }

        meta = summary.get("metadata") if isinstance(summary, dict) else None
        if not isinstance(meta, dict):
            return {"ok": False, "error": "fleet summary missing metadata"}
        return {"ok": True, "summary": summary, "metadata": meta}

    def can_handle(self, user_prompt: str) -> bool:
        """Detect whether prompt requires AI Universe orchestration."""
        p = (user_prompt or "").lower()
        patterns = [
            r"\b(create|spawn|build|run)\s+(a\s+)?world\b",
            r"\b(universe|simulation)\s+(with|\d+|agents|experiment)\b",
            r"\b(run|start|execute)\s+(a\s+)?(simulation|universe experiment)\b",
            r"\b\d+\s+agents\b.*(world|simulation|experiment)",
            r"\b(friday universe|all agents|fleet status|delegate to \w+)\b",
        ]
        return any(re.search(pat, p) for pat in patterns)

    def execute_universe_goal(
        self,
        goal: str,
        agent_count: int | None = None,
        steps: int | None = None,
    ) -> dict[str, Any]:
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
        if self.planner:
            try:
                decomposition_plan = self.planner.plan(goal)
            except Exception as ex:
                logger.debug(f"Decomposition fallback: {ex}")

        # 3. Create World, or refuse to pretend a live dispatch happened.
        if self.api is None:
            return self._live_path_without_universe_api(goal, decomposition_plan)

        world_cfg = WorldConfig(name=f"Universe: {goal[:30]}")
        world_state: WorldState = self.api.create_world(world_cfg)

        # 4. Spawn Agents
        created_agents: list[dict[str, Any]] = []
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

        # 7. Record into the Oracle experiments table (FRIDAY Lab Integration)
        if self.memory is not None and hasattr(self.memory, "record_experiment"):
            try:
                self.memory.record_experiment(
                    experiment_name=exp_result.experiment_name,
                    task_prompt=goal,
                    task_type="universe_simulation",
                    provider_name="UniverseAPI",
                    model_name="SimAgentEngine",
                    # A missing metric is stored as NULL and left out of the
                    # averages; it used to be recorded as accuracy 1.0 (perfect)
                    # and latency 50.0 ms (fast), flattering both.
                    accuracy=exp_result.metrics.get("accuracy"),
                    success=exp_result.success,
                    latency_ms=exp_result.metrics.get("avg_agent_latency_ms"),
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
                logger.warning(f"Could not record universe experiment in Oracle: {ex}")

        # 8. Synthesize outcome
        synthesis = (
            f"🪐 **Universe Simulation Completed**\n\n"
            f"- **World ID**: `{world_state.world_id}`\n"
            f"- **Agents Deployed**: {len(created_agents)}\n"
            f"- **Simulation Steps**: {exp_result.total_steps}\n"
            f"- **Outcome Summary**: {exp_result.summary}\n\n"
            + (
                "**Key Metrics**:\n"
                + "".join(
                    f"- {label}: {value}\n"
                    for label, value in (
                        ("Accuracy", f"{exp_result.metrics['accuracy'] * 100:.1f}%"
                         if isinstance(exp_result.metrics.get("accuracy"), (int, float)) else None),
                        ("Cooperation Index", f"{exp_result.metrics['cooperation_index']:.2f}"
                         if isinstance(exp_result.metrics.get("cooperation_index"), (int, float)) else None),
                        ("Resource Efficiency", f"{exp_result.metrics['resource_efficiency']:.2f}"
                         if isinstance(exp_result.metrics.get("resource_efficiency"), (int, float)) else None),
                        ("Average Agent Latency", f"{exp_result.metrics['avg_agent_latency_ms']:.1f}ms"
                         if isinstance(exp_result.metrics.get("avg_agent_latency_ms"), (int, float)) else None),
                    )
                    if value is not None
                )
                if exp_result.metrics else
                # Four metrics were printed with 0.0 defaults, so a simulation
                # that measured nothing reported perfect-looking zeros.
                "**Key Metrics**: none reported by the simulation.\n"
            )
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
