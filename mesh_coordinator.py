"""
FRIDAY/mesh_coordinator.py — FRIDAY Mesh Coordinator.

Extends FRIDAY's capabilities with:
1. Peer Discovery: discover and register agents in the mesh
2. Message Routing: route messages through the mesh network
3. Sync Protocol: coordinate data synchronization across agents
4. Consensus Mechanism: reach consensus on shared state
5. Failure Detection: detect and handle node failures
6. Load Balancing: distribute tasks across mesh nodes
7. Resilience: automatic rerouting and recovery
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MeshNode:
    """A node in the mesh network."""
    node_id: str
    agent_name: str
    address: str
    port: int = 0
    status: str = "discovered"  # discovered, active, inactive, failed
    last_heartbeat: float = 0.0
    capabilities: list[str] = field(default_factory=list)
    connected_nodes: list[str] = field(default_factory=list)
    load: float = 0.0
    uptime: float = 0.0


@dataclass
class MeshMessage:
    """A message routed through the mesh."""
    message_id: str
    source: str
    target: str
    payload: dict[str, Any]
    message_type: str = "data"  # data, sync, heartbeat, control
    priority: int = 5
    timestamp: float = 0.0
    route: list[str] = field(default_factory=list)
    acked: bool = False


@dataclass
class SyncState:
    """State for synchronization."""
    key: str
    version: int
    value: Any
    source: str
    timestamp: float = 0.0
    merged: bool = False


@dataclass
class ConsensusDecision:
    """A consensus decision."""
    topic: str
    proposal: dict[str, Any]
    votes: dict[str, str] = field(default_factory=dict)  # node_id -> vote
    decision: str = "pending"  # pending, approved, rejected
    quorum: int = 0
    required_quorum: int = 0
    decided_at: float = 0.0


class MeshCoordinator:
    """Mesh network coordinator for agent coordination."""

    def __init__(self):
        self._nodes: dict[str, MeshNode] = {}
        self._messages: list[MeshMessage] = {}
        self._sync_states: dict[str, SyncState] = {}
        self._consensus: dict[str, ConsensusDecision] = {}
        self._routes: dict[str, list[str]] = {}
        self._failed_nodes: set[str] = set()

    # ── Peer Discovery ─────────────────────────────────────────────────────

    def register_node(
        self,
        agent_name: str,
        address: str,
        port: int = 0,
        capabilities: list[str] | None = None,
    ) -> MeshNode:
        """Register a new node in the mesh."""
        node_id = hashlib.md5(
            f"{agent_name}:{address}:{port}".encode()
        ).hexdigest()[:12]

        node = MeshNode(
            node_id=node_id,
            agent_name=agent_name,
            address=address,
            port=port,
            status="active",
            last_heartbeat=time.time(),
            capabilities=capabilities or [],
        )

        self._nodes[node_id] = node

        # Connect to existing nodes
        for other_id, other in self._nodes.items():
            if other_id != node_id:
                node.connected_nodes.append(other_id)
                other.connected_nodes.append(node_id)

        return node

    def heartbeat(self, node_id: str) -> bool:
        """Update node heartbeat."""
        if node_id in self._nodes:
            self._nodes[node_id].last_heartbeat = time.time()
            self._nodes[node_id].status = "active"
            if node_id in self._failed_nodes:
                self._failed_nodes.remove(node_id)
            return True
        return False

    def detect_failed_nodes(self, timeout: float = 30.0) -> list[str]:
        """Detect failed nodes."""
        now = time.time()
        failed = []

        for node_id, node in self._nodes.items():
            if node.status == "inactive":
                continue
            if now - node.last_heartbeat > timeout:
                node.status = "failed"
                self._failed_nodes.add(node_id)
                failed.append(node_id)

                # Reroute messages
                self._reroute_messages(node_id)

        return failed

    # ── Message Routing ─────────────────────────────────────────────────────

    def send_message(
        self,
        source: str,
        target: str,
        payload: dict[str, Any],
        message_type: str = "data",
        priority: int = 5,
    ) -> MeshMessage:
        """Send a message through the mesh."""
        message_id = hashlib.md5(
            f"{source}:{target}:{time.time()}:{priority}".encode()
        ).hexdigest()[:12]

        # Find route
        route = self._find_route(source, target)

        message = MeshMessage(
            message_id=message_id,
            source=source,
            target=target,
            payload=payload,
            message_type=message_type,
            priority=priority,
            timestamp=time.time(),
            route=route,
        )

        self._messages[message_id] = message

        # Simulate routing
        return message

    def _find_route(self, source: str, target: str) -> list[str]:
        """Find a route from source to target using BFS."""
        if source == target:
            return [source]

        if source not in self._nodes or target not in self._nodes:
            return []

        # BFS
        visited = set()
        queue = [(source, [source])]

        while queue:
            current, path = queue.pop(0)

            if current in visited:
                continue
            visited.add(current)

            if current == target:
                self._routes[f"{source}:{target}"] = path
                return path

            for neighbor in self._nodes.get(current, MeshNode("", "", "")).connected_nodes:
                if neighbor not in visited:
                    queue.append((neighbor, path + [neighbor]))

        return []

    def _reroute_messages(self, failed_node: str) -> None:
        """Reroute messages through failed nodes."""
        for message in self._messages.values():
            if failed_node in message.route:
                # Try to find alternative route
                new_route = self._find_route(message.source, message.target)
                if new_route:
                    message.route = new_route

    # ── Sync Protocol ───────────────────────────────────────────────────────

    def sync_state(
        self,
        key: str,
        value: Any,
        source: str,
        version: int | None = None,
    ) -> SyncState:
        """Sync state across the mesh."""
        existing = self._sync_states.get(key)

        if existing and existing.version >= (version or 0):
            return existing

        new_version = (existing.version + 1) if existing else 1

        state = SyncState(
            key=key,
            version=new_version,
            value=value,
            source=source,
            timestamp=time.time(),
            merged=True,
        )

        self._sync_states[key] = state
        return state

    def merge_sync(
        self,
        incoming: dict[str, Any],
        source: str,
    ) -> list[SyncState]:
        """Merge incoming sync data."""
        updated = []

        for key, value in incoming.items():
            state = self.sync_state(key, value, source)
            if state.merged:
                updated.append(state)

        return updated

    def get_sync_state(self, key: str) -> SyncState | None:
        """Get current sync state for a key."""
        return self._sync_states.get(key)

    # ── Consensus Mechanism ─────────────────────────────────────────────────

    def propose_consensus(
        self,
        topic: str,
        proposal: dict[str, Any],
        required_quorum: int | None = None,
    ) -> ConsensusDecision:
        """Propose a consensus decision."""
        decision = ConsensusDecision(
            topic=topic,
            proposal=proposal,
            required_quorum=required_quorum or (len(self._nodes) // 2 + 1),
        )

        self._consensus[topic] = decision
        return decision

    def vote(self, topic: str, node_id: str, vote: str) -> bool:
        """Cast a vote on a consensus proposal."""
        decision = self._consensus.get(topic)
        if not decision:
            return False

        decision.votes[node_id] = vote

        # Check if quorum reached
        yes_votes = sum(1 for v in decision.votes.values() if v == "approve")
        no_votes = sum(1 for v in decision.votes.values() if v == "reject")

        if yes_votes >= decision.required_quorum:
            decision.decision = "approved"
            decision.decided_at = time.time()
        elif no_votes >= decision.required_quorum:
            decision.decision = "rejected"
            decision.decided_at = time.time()

        return True

    def get_consensus_status(self, topic: str) -> dict[str, Any]:
        """Get consensus status."""
        decision = self._consensus.get(topic)
        if not decision:
            return {"status": "NOT_FOUND"}

        return {
            "topic": decision.topic,
            "proposal": decision.proposal,
            "decision": decision.decision,
            "votes": decision.votes,
            "quorum": len(decision.votes),
            "required_quorum": decision.required_quorum,
        }

    # ── Load Balancing ──────────────────────────────────────────────────────

    def get_best_node(
        self,
        required_capability: str | None = None,
    ) -> MeshNode | None:
        """Get the best node for a task."""
        candidates = [
            node for node in self._nodes.values()
            if node.status == "active" and node.node_id not in self._failed_nodes
        ]

        if required_capability:
            candidates = [
                node for node in candidates
                if required_capability in node.capabilities
            ]

        if not candidates:
            return None

        # Pick least loaded
        candidates.sort(key=lambda n: n.load)
        return candidates[0]

    def distribute_load(
        self,
        task_description: str,
        required_capability: str | None = None,
    ) -> MeshNode | None:
        """Distribute a task to the best node."""
        node = self.get_best_node(required_capability)
        if node:
            node.load += 1

            # Send task message
            self.send_message(
                source="MeshCoordinator",
                target=node.node_id,
                payload={"task": task_description},
                message_type="control",
            )

        return node

    def update_node_load(self, node_id: str, load: float):
        """Update node load."""
        if node_id in self._nodes:
            self._nodes[node_id].load = load

    # ── Resilience ──────────────────────────────────────────────────────────

    def recover_from_failure(self, failed_node: str) -> bool:
        """Recover from a node failure."""
        if failed_node not in self._nodes:
            return False

        node = self._nodes[failed_node]
        node.status = "active"
        node.last_heartbeat = time.time()

        # Re-establish connections
        for other_id in self._nodes:
            if other_id != failed_node and other_id not in node.connected_nodes:
                node.connected_nodes.append(other_id)
                self._nodes[other_id].connected_nodes.append(failed_node)

        self._failed_nodes.remove(failed_node)
        return True

    def get_mesh_health(self) -> dict[str, Any]:
        """Get mesh health report."""
        active = sum(1 for n in self._nodes.values() if n.status == "active")
        failed = len(self._failed_nodes)
        total_load = sum(n.load for n in self._nodes.values())

        return {
            "total_nodes": len(self._nodes),
            "active_nodes": active,
            "failed_nodes": failed,
            "avg_load": total_load / max(1, len(self._nodes)),
            "connectivity": (
                sum(len(n.connected_nodes) for n in self._nodes.values()) /
                max(1, len(self._nodes) * (len(self._nodes) - 1))
            ),
            "consensus_topics": len(self._consensus),
            "sync_keys": len(self._sync_states),
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_mesh_report(self) -> dict[str, Any]:
        """Generate a mesh report."""
        return {
            "nodes": len(self._nodes),
            "active": sum(1 for n in self._nodes.values() if n.status == "active"),
            "messages": len(self._messages),
            "sync_keys": len(self._sync_states),
            "consensus": len(self._consensus),
            "health": self.get_mesh_health(),
        }


# Module-level singleton
mesh_coordinator = MeshCoordinator()
