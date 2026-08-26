# -*- coding: utf-8 -*-
"""Universe API contract and data abstractions for FRIDAY AI Universe Integration (AI Universe Integration)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class WorldConfig:
    """Configuration for an AI Universe simulated environment."""

    world_id: str = field(default_factory=lambda: f"world_{uuid.uuid4().hex[:8]}")
    name: str = "Default Universe World"
    grid_size: tuple[int, int] = (50, 50)
    physics_rules: Dict[str, Any] = field(default_factory=dict)
    max_steps: int = 1000
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UniverseAgentConfig:
    """Configuration for an autonomous simulated entity in the Universe."""

    agent_id: str = field(default_factory=lambda: f"uagent_{uuid.uuid4().hex[:8]}")
    name: str = "SimAgent"
    persona: str = "Curious Explorer"
    goals: List[str] = field(default_factory=list)
    initial_position: tuple[int, int] = (0, 0)
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldState:
    """Snapshot of the simulated Universe world state at a point in time."""

    world_id: str
    step: int
    is_running: bool
    active_agents: List[Dict[str, Any]] = field(default_factory=list)
    environmental_variables: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UniverseExperimentResult:
    """Consolidated trial metrics and outcomes of a Universe simulation experiment."""

    experiment_id: str = field(default_factory=lambda: f"uexp_{uuid.uuid4().hex[:8]}")
    world_id: str = ""
    experiment_name: str = "Universe Experiment"
    total_steps: int = 0
    agent_count: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)  # e.g., accuracy, survival_rate, latency_ms
    success: bool = True
    summary: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_logs: List[Dict[str, Any]] = field(default_factory=list)


class BaseUniverseAPI(ABC):
    """Abstract interface defining the control SDK for the external AI Universe."""

    @abstractmethod
    def create_world(self, config: WorldConfig) -> WorldState:
        """Instantiate a new simulated universe world."""
        pass

    @abstractmethod
    def create_agent(self, agent_config: UniverseAgentConfig) -> Dict[str, Any]:
        """Deploy an autonomous simulated agent into the active world."""
        pass

    @abstractmethod
    def start_simulation(self, steps: Optional[int] = None) -> WorldState:
        """Start or unpause execution of the active universe simulation."""
        pass

    @abstractmethod
    def stop_simulation(self) -> WorldState:
        """Halt or pause execution of the universe simulation."""
        pass

    @abstractmethod
    def get_world_state(self) -> WorldState:
        """Query the live state and entity positions of the simulated world."""
        pass

    @abstractmethod
    def get_experiment_results(self) -> UniverseExperimentResult:
        """Retrieve aggregated experiment trial metrics and findings from the simulation."""
        pass
