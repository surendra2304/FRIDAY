"""
FRIDAY/apps/core/src/friday_core/universe_knowledge_graph.py — FRIDAY Universe Knowledge Graph.

Cross-agent knowledge graph, entity relationship mapping,
semantic query engine, and knowledge graph evolution tracking.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class KnowledgeEntity:
    """An entity in the universe knowledge graph."""
    entity_id: str
    name: str
    entity_type: str = "concept"  # concept, agent, domain, skill, relationship, fact
    properties: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_updated: float = 0.0


@dataclass
class KnowledgeEdge:
    """A relationship between entities."""
    edge_id: str
    source: str
    target: str
    relationship: str = "related_to"  # related_to, depends_on, specializes_in, uses, produces
    weight: float = 1.0
    properties: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class KnowledgeQuery:
    """A semantic knowledge query."""
    query_id: str
    query_text: str
    results: list[dict] = field(default_factory=list)
    entities_found: int = 0
    relationships_found: int = 0
    latency_ms: float = 0.0


class UniverseKnowledgeGraph:
    """Engine for universe-wide knowledge graph management."""

    def __init__(self) -> None:
        self._entities: dict[str, KnowledgeEntity] = {}
        self._edges: dict[str, KnowledgeEdge] = {}
        self._queries: list[KnowledgeQuery] = []

    def add_entity(self, name: str, entity_type: str = "concept",
                   properties: dict | None = None) -> KnowledgeEntity:
        """Add an entity to the knowledge graph."""
        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        entity = KnowledgeEntity(
            entity_id=entity_id, name=name, entity_type=entity_type,
            properties=properties or {},
        )
        entity.last_updated = time.time()
        self._entities[entity_id] = entity
        return entity

    def add_edge(self, source_id: str, target_id: str,
                relationship: str = "related_to", weight: float = 1.0,
                properties: dict | None = None) -> KnowledgeEdge:
        """Add a relationship between entities."""
        if source_id not in self._entities or target_id not in self._entities:
            raise HTTPException(status_code=404, detail="Entity not found")

        edge_id = f"edge_{uuid.uuid4().hex[:12]}"
        edge = KnowledgeEdge(
            edge_id=edge_id, source=source_id, target=target_id,
            relationship=relationship, weight=weight,
            properties=properties or {},
        )
        self._edges[edge_id] = edge
        return edge

    def query(self, query_text: str, max_results: int = 10) -> KnowledgeQuery:
        """Query the knowledge graph."""
        query_id = f"q_{uuid.uuid4().hex[:12]}"
        query = KnowledgeQuery(query_id=query_id, query_text=query_text)

        start = time.time()
        words = [w.lower() for w in query_text.split() if len(w) > 2]

        # Find matching entities
        for entity in self._entities.values():
            entity_words = [w.lower() for w in entity.name.split()]
            matches = sum(1 for w in words if w in entity_words or w in entity.name.lower())
            if matches > 0:
                query.results.append({
                    "entity_id": entity.entity_id,
                    "name": entity.name,
                    "type": entity.entity_type,
                    "matches": matches,
                })

        # Find related relationships
        related_edges = []
        for edge in self._edges.values():
            source_entity = self._entities.get(edge.source)
            target_entity = self._entities.get(edge.target)
            if source_entity and any(w in source_entity.name.lower() for w in words):
                related_edges.append({
                    "relationship": edge.relationship,
                    "target": target_entity.name if target_entity else "unknown",
                })
            elif target_entity and any(w in target_entity.name.lower() for w in words):
                related_edges.append({
                    "relationship": edge.relationship,
                    "target": source_entity.name if source_entity else "unknown",
                })

        query.results.extend(related_edges[:max_results])
        query.entities_found = len([r for r in query.results if "entity_id" in r])
        query.relationships_found = len(related_edges)
        query.latency_ms = (time.time() - start) * 1000

        self._queries.append(query)
        return query

    def get_entity_relations(self, entity_id: str) -> dict[str, Any]:
        """Get all relationships for an entity."""
        entity = self._entities.get(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        relations = {"outgoing": [], "incoming": []}
        for edge in self._edges.values():
            if edge.source == entity_id:
                target = self._entities.get(edge.target)
                relations["outgoing"].append({
                    "relationship": edge.relationship,
                    "target": target.name if target else "unknown",
                })
            elif edge.target == entity_id:
                source = self._entities.get(edge.source)
                relations["incoming"].append({
                    "relationship": edge.relationship,
                    "source": source.name if source else "unknown",
                })
        return relations

    def get_entities(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        """Get entities."""
        entities = list(self._entities.values())
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        return [
            {"name": e.name, "type": e.entity_type, "properties_count": len(e.properties)}
            for e in entities
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_entities": len(self._entities),
            "total_edges": len(self._edges),
            "total_queries": len(self._queries),
            "entity_types": len(set(e.entity_type for e in self._entities.values())),
            "engine_status": "operational",
        }


engine = UniverseKnowledgeGraph()


@router.post("/knowledgegraph/entities")
async def add_entity(name: str, entity_type: str = "concept", properties: dict | None = None):
    """Add an entity to the knowledge graph."""
    entity = engine.add_entity(name, entity_type, properties)
    return {"entity_id": entity.entity_id, "name": entity.name, "type": entity.entity_type}


@router.post("/knowledgegraph/edges")
async def add_edge(source_id: str, target_id: str, relationship: str = "related_to",
                   weight: float = 1.0, properties: dict | None = None):
    """Add a relationship between entities."""
    edge = engine.add_edge(source_id, target_id, relationship, weight, properties)
    return {"edge_id": edge.edge_id, "relationship": edge.relationship}


@router.post("/knowledgegraph/query")
async def query(query_text: str, max_results: int = 10):
    """Query the knowledge graph."""
    query = engine.query(query_text, max_results)
    return {
        "query_id": query.query_id,
        "entities_found": query.entities_found,
        "relationships_found": query.relationships_found,
        "results": query.results[:5],
    }


@router.get("/knowledgegraph/entities/{entity_id}/relations")
async def get_entity_relations(entity_id: str):
    """Get all relationships for an entity."""
    return engine.get_entity_relations(entity_id)


@router.get("/knowledgegraph/entities")
async def get_entities(entity_type: str | None = None):
    """Get entities."""
    return {"entities": engine.get_entities(entity_type)}


@router.get("/knowledgegraph/report")
async def knowledgegraph_report():
    """Get knowledge graph report."""
    return engine.get_report()
