"""
FRIDAY/universe_integration.py — Unified FRIDAY Universe Integration Layer.

Connects all 10 agents into a cohesive autonomous system:
1. Agent Registry: central registry of all agents with capabilities
2. Cross-Agent Messaging: structured communication between agents
3. Shared Knowledge Bus: shared state and knowledge across agents
4. Task Routing: intelligent task routing to the best agent
5. Event Bus: publish-subscribe event system
6. Universe Snapshot: real-time snapshot of the entire universe
7. Agent Health Checks: continuous health monitoring
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentDescriptor:
    """Descriptor for an agent in the universe."""
    name: str
    version: str = "1.0.0"
    status: str = "idle"
    capabilities: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    last_heartbeat: float = 0.0
    health: float = 1.0
    uptime: float = 0.0


@dataclass
class UniverseEvent:
    """An event in the universe event bus."""
    event_id: str
    event_type: str
    source: str
    target: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    priority: int = 5  # 1-10, lower = higher priority


@dataclass
class KnowledgeEntry:
    """An entry in the shared knowledge bus."""
    key: str
    value: Any
    source: str
    timestamp: float = 0.0
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class TaskRoute:
    """A routed task."""
    task_id: str
    description: str
    agent: str
    reason: str = ""
    priority: int = 5
    dependencies: list[str] = field(default_factory=list)
    created_at: float = 0.0


class UniverseIntegration:
    """Unified integration layer for the FRIDAY Universe."""

    AGENT_REGISTRY = {
        "FRIDAY": {
            "capabilities": ["orchestration", "coordination", "monitoring", "orchestration", "self_healing"],
            "endpoints": ["/api/v1/orchestrate", "/api/v1/progress", "/api/v1/alerts"],
        },
        "Cortex": {
            "capabilities": ["crm", "lead_scoring", "customer_intelligence", "data_analytics", "enhanced_crm"],
            "endpoints": ["/api/v1/leads", "/api/v1/crm", "/api/v1/profiles"],
        },
        "Stratex": {
            "capabilities": ["trading", "portfolio_management", "risk_management", "regime_detection", "pair_trading", "enhanced_risk"],
            "endpoints": ["/api/v1/portfolio", "/api/v1/trade", "/api/v1/risk"],
        },
        "VyralX": {
            "capabilities": ["youtube", "content_generation", "content_optimization", "audience_growth", "analytics"],
            "endpoints": ["/api/v1/content", "/api/v1/analytics", "/api/v1/publish"],
        },
        "Memora": {
            "capabilities": ["memory", "knowledge_storage", "memory_enhancement", "consolidation", "recall"],
            "endpoints": ["/api/v1/memories", "/api/v1/memory/enhance", "/api/v1/knowledge"],
        },
        "IntelX": {
            "capabilities": ["research", "multi_source_synthesis", "cross_reference", "bias_detection", "citation_graph"],
            "endpoints": ["/api/v1/research", "/api/v1/synthesis", "/api/v1/verification"],
        },
        "Forge": {
            "capabilities": ["code_generation", "test_driven_development", "refactoring", "security_scanning", "performance_profiling"],
            "endpoints": ["/api/v1/generate", "/api/v1/refactor", "/api/v1/scan"],
        },
        "Inference": {
            "capabilities": ["reasoning", "deliberation", "formal_verification", "argument_graph", "consensus_building"],
            "endpoints": ["/api/v1/reason", "/api/v1/deliberate", "/api/v1/verify"],
        },
        "Mesh": {
            "capabilities": ["coordination", "communication", "routing", "sync", "resilience"],
            "endpoints": ["/api/v1/mesh", "/api/v1/sync", "/api/v1/route"],
        },
        "Sentinel": {
            "capabilities": ["security", "threat_detection", "vulnerability_scanning", "monitoring", "protection"],
            "endpoints": ["/api/v1/scan", "/api/v1/threats", "/api/v1/monitor"],
        },
    }

    def __init__(self):
        self._agents: dict[str, AgentDescriptor] = {}
        self._event_bus: list[UniverseEvent] = []
        self._event_subscribers: dict[str, list[Callable]] = {}
        self._knowledge_bus: dict[str, KnowledgeEntry] = {}
        self._routed_tasks: list[TaskRoute] = []
        self._start_time = time.time()

        # Register all agents
        for name, info in self.AGENT_REGISTRY.items():
            self.register_agent(name, **info)

    # ── Agent Registry ─────────────────────────────────────────────────────

    def register_agent(
        self,
        name: str,
        capabilities: list[str] | None = None,
        endpoints: list[str] | None = None,
        version: str = "1.0.0",
    ) -> AgentDescriptor:
        """Register an agent."""
        agent = AgentDescriptor(
            name=name,
            version=version,
            capabilities=capabilities or [],
            endpoints=endpoints or [],
            last_heartbeat=time.time(),
            uptime=0.0,
        )
        self._agents[name] = agent
        return agent

    def get_agent(self, name: str) -> AgentDescriptor | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def get_all_agents(self) -> dict[str, AgentDescriptor]:
        """Get all registered agents."""
        return self._agents

    def update_agent_health(self, name: str, health: float):
        """Update agent health score."""
        if name in self._agents:
            self._agents[name].health = health
            self._agents[name].last_heartbeat = time.time()

    def get_healthy_agents(self, threshold: float = 0.5) -> list[str]:
        """Get agents with health above threshold."""
        return [
            name for name, agent in self._agents.items()
            if agent.health >= threshold
        ]

    def get_agents_by_capability(self, capability: str) -> list[str]:
        """Get agents that have a specific capability."""
        return [
            name for name, agent in self._agents.items()
            if capability in agent.capabilities
        ]

    # ── Event Bus ──────────────────────────────────────────────────────────

    def publish_event(
        self,
        event_type: str,
        source: str,
        data: dict[str, Any] | None = None,
        target: str = "",
        priority: int = 5,
    ) -> UniverseEvent:
        """Publish an event to the bus."""
        event = UniverseEvent(
            event_id=hashlib.md5(
                f"{event_type}:{source}:{time.time()}".encode()
            ).hexdigest()[:12],
            event_type=event_type,
            source=source,
            target=target,
            data=data or {},
            timestamp=time.time(),
            priority=priority,
        )

        self._event_bus.append(event)

        # Notify subscribers
        for subscriber in self._event_subscribers.get(event_type, []):
            try:
                subscriber(event)
            except Exception:
                pass

        return event

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to events of a type."""
        if event_type not in self._event_subscribers:
            self._event_subscribers[event_type] = []
        self._event_subscribers[event_type].append(callback)

    def get_recent_events(
        self,
        event_type: str | None = None,
        limit: int = 20,
    ) -> list[UniverseEvent]:
        """Get recent events."""
        events = self._event_bus
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    # ── Shared Knowledge Bus ─────────────────────────────────────────────────

    def publish_knowledge(
        self,
        key: str,
        value: Any,
        source: str,
        tags: list[str] | None = None,
        confidence: float = 0.5,
    ) -> KnowledgeEntry:
        """Publish knowledge to the shared bus."""
        entry = KnowledgeEntry(
            key=key,
            value=value,
            source=source,
            timestamp=time.time(),
            tags=tags or [],
            confidence=confidence,
        )
        self._knowledge_bus[key] = entry

        # Notify event subscribers
        self.publish_event(
            "knowledge_updated",
            source,
            {"key": key, "tags": tags},
        )

        return entry

    def get_knowledge(self, key: str) -> KnowledgeEntry | None:
        """Get knowledge by key."""
        return self._knowledge_bus.get(key)

    def search_knowledge(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """Search knowledge by query and tags."""
        results = []
        query_lower = query.lower()

        for entry in self._knowledge_bus.values():
            # Tag matching
            if tags and not all(tag in entry.tags for tag in tags):
                continue

            # Value matching
            value_str = str(entry.value).lower()
            if query_lower in value_str or query_lower in entry.key.lower():
                results.append(entry)

        # Sort by confidence and recency
        results.sort(
            key=lambda e: e.confidence * 0.7 + (1.0 if time.time() - e.timestamp < 3600 else 0.3),
            reverse=True,
        )

        return results[:limit]

    def get_all_knowledge(self) -> dict[str, KnowledgeEntry]:
        """Get all knowledge."""
        return self._knowledge_bus

    # ── Task Routing ───────────────────────────────────────────────────────

    def route_task(
        self,
        description: str,
        priority: int = 5,
        dependencies: list[str] | None = None,
    ) -> TaskRoute:
        """Route a task to the best agent."""
        # Keyword-based routing
        routing_rules = {
            "trade": ("Stratex", "Trading task"),
            "portfolio": ("Stratex", "Portfolio management"),
            "risk": ("Stratex", "Risk management"),
            "youtube": ("VyralX", "YouTube content"),
            "video": ("VyralX", "Video production"),
            "content": ("VyralX", "Content generation"),
            "research": ("IntelX", "Research task"),
            "synthesis": ("IntelX", "Multi-source synthesis"),
            "code": ("Forge", "Code generation"),
            "develop": ("Forge", "Software development"),
            "test": ("Forge", "Testing"),
            "reason": ("Inference", "Reasoning"),
            "verify": ("Inference", "Verification"),
            "deliberate": ("Inference", "Deliberation"),
            "memory": ("Memora", "Memory management"),
            "knowledge": ("Memora", "Knowledge storage"),
            "crm": ("Cortex", "CRM task"),
            "lead": ("Cortex", "Lead management"),
            "security": ("Sentinel", "Security scan"),
            "threat": ("Sentinel", "Threat detection"),
            "orchestrate": ("FRIDAY", "Orchestration"),
            "mesh": ("Mesh", "Mesh coordination"),
            "sync": ("Mesh", "Synchronization"),
        }

        lower = description.lower()
        routed_agent = "FRIDAY"  # Default fallback
        reason = "Default to FRIDAY orchestrator"

        for keyword, (agent, reason_text) in routing_rules.items():
            if keyword in lower:
                # Check if agent is healthy
                agent_info = self._agents.get(agent)
                if agent_info and agent_info.health > 0.3:
                    routed_agent = agent
                    reason = reason_text
                    break

        task = TaskRoute(
            task_id=hashlib.md5(
                f"{description}:{time.time()}".encode()
            ).hexdigest()[:12],
            description=description,
            agent=routed_agent,
            reason=reason,
            priority=priority,
            dependencies=dependencies or [],
            created_at=time.time(),
        )

        self._routed_tasks.append(task)

        # Publish routing event
        self.publish_event(
            "task_routed",
            "UniverseIntegration",
            {"task_id": task.task_id, "agent": task.agent, "description": description},
            target=task.agent,
            priority=priority,
        )

        return task

    def get_routed_tasks(
        self,
        agent: str | None = None,
        limit: int = 20,
    ) -> list[TaskRoute]:
        """Get routed tasks."""
        tasks = self._routed_tasks
        if agent:
            tasks = [t for t in tasks if t.agent == agent]
        return tasks[-limit:]

    # ── Cross-Agent Messaging ────────────────────────────────────────────────

    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        data: dict[str, Any],
    ) -> UniverseEvent:
        """Send a message between agents."""
        return self.publish_event(
            event_type="agent_message",
            source=from_agent,
            target=to_agent,
            data={"message_type": message_type, "payload": data},
            priority=3,
        )

    def broadcast(
        self,
        from_agent: str,
        message_type: str,
        data: dict[str, Any],
        except_agent: str = "",
    ) -> list[UniverseEvent]:
        """Broadcast a message to all agents."""
        events = []
        for agent_name in self._agents:
            if agent_name == from_agent or agent_name == except_agent:
                continue
            event = self.send_message(from_agent, agent_name, message_type, data)
            events.append(event)
        return events

    # ── Universe Snapshot ───────────────────────────────────────────────────

    def get_universe_snapshot(self) -> dict[str, Any]:
        """Get a real-time snapshot of the entire universe."""
        now = time.time()
        uptime = now - self._start_time

        agents_info = {}
        for name, agent in self._agents.items():
            agents_info[name] = {
                "version": agent.version,
                "status": agent.status,
                "capabilities": agent.capabilities,
                "health": agent.health,
                "last_heartbeat": agent.last_heartbeat,
                "age_seconds": now - agent.last_heartbeat,
                "endpoints": agent.endpoints,
            }

        return {
            "timestamp": now,
            "uptime_hours": uptime / 3600,
            "total_agents": len(self._agents),
            "healthy_agents": len(self.get_healthy_agents()),
            "agents": agents_info,
            "knowledge_entries": len(self._knowledge_bus),
            "events_published": len(self._event_bus),
            "tasks_routed": len(self._routed_tasks),
        }

    def get_universe_health_report(self) -> dict[str, Any]:
        """Get a health report for the universe."""
        now = time.time()

        health_report = {
            "timestamp": now,
            "overall_health": 0.0,
            "agents": {},
            "alerts": [],
            "recommendations": [],
        }

        total_health = 0.0
        critical_agents = []
        warning_agents = []

        for name, agent in self._agents.items():
            age = now - agent.last_heartbeat
            agent_health = agent.health

            health_report["agents"][name] = {
                "health": agent_health,
                "last_heartbeat_age": age,
                "status": agent.status,
                "capabilities": len(agent.capabilities),
            }

            total_health += agent_health

            if age > 300:  # 5 minutes without heartbeat
                critical_agents.append(name)
                health_report["alerts"].append({
                    "severity": "critical",
                    "agent": name,
                    "message": f"No heartbeat for {age:.0f} seconds",
                })
            elif age > 60:  # 1 minute without heartbeat
                warning_agents.append(name)
                health_report["alerts"].append({
                    "severity": "warning",
                    "agent": name,
                    "message": f"No heartbeat for {age:.0f} seconds",
                })

            if agent_health < 0.3:
                health_report["alerts"].append({
                    "severity": "critical",
                    "agent": name,
                    "message": f"Agent health critical: {agent_health:.1f}",
                })

        # Overall health
        health_report["overall_health"] = total_health / max(1, len(self._agents))

        # Recommendations
        if critical_agents:
            health_report["recommendations"].append(
                f"Restart critical agents: {', '.join(critical_agents)}"
            )

        if warning_agents:
            health_report["recommendations"].append(
                f"Monitor warning agents: {', '.join(warning_agents)}"
            )

        if health_report["overall_health"] < 0.7:
            health_report["recommendations"].append(
                "Overall universe health is below threshold. Consider scaling resources."
            )

        return health_report

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_integration_report(self) -> dict[str, Any]:
        """Generate an integration report."""
        snapshot = self.get_universe_snapshot()

        return {
            "universe_snapshot": {
                "total_agents": snapshot["total_agents"],
                "healthy_agents": snapshot["healthy_agents"],
                "knowledge_entries": snapshot["knowledge_entries"],
                "events_published": snapshot["events_published"],
                "tasks_routed": snapshot["tasks_routed"],
            },
            "agent_capabilities": {
                name: len(agent.capabilities)
                for name, agent in self._agents.items()
            },
            "event_types": list(self._event_subscribers.keys()),
        }


# Module-level singleton
universe_integration = UniverseIntegration()
