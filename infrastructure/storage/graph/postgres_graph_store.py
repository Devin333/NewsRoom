from __future__ import annotations

from collections import deque
from typing import Any, cast

from backend.memory.graph_models import GraphEdge, GraphEdgeType, GraphExpansion, GraphNode, GraphPath, GraphQuery
from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository


class PostgresGraphMemoryStore:
    def __init__(self, repository: PostgresIntelligenceMemoryRepository) -> None:
        self.repository = repository
        self.last_path_metadata: dict[str, Any] = {}

    def upsert_node(self, node: GraphNode) -> None:
        return None

    def upsert_edge(self, edge: GraphEdge) -> None:
        return None

    def get_node(self, node_id: str) -> GraphNode | None:
        for loader in (
            self._entity_node,
            self._event_node,
            self._claim_node,
            self._evidence_node,
            self._decision_node,
            self._preference_node,
        ):
            node = loader(node_id)
            if node is not None:
                return node
        if node_id.startswith("topic:"):
            topic = node_id.split(":", 1)[1]
            return GraphNode(node_id=node_id, node_type="topic", label=topic, metadata={"topic": topic})
        if node_id.startswith("source:"):
            source_id = node_id.split(":", 1)[1]
            return GraphNode(node_id=node_id, node_type="source", label=source_id, metadata={"source_id": source_id})
        if node_id.startswith("report:"):
            report_id = node_id.split(":", 1)[1]
            return GraphNode(node_id=node_id, node_type="report", label=report_id, metadata={"report_id": report_id})
        return None

    def neighbors(
        self,
        node_id: str,
        *,
        depth: int = 1,
        edge_types: list[str] | None = None,
        limit: int = 50,
    ) -> GraphExpansion:
        root = self.get_node(node_id)
        if root is None:
            return GraphExpansion(
                root=_missing_node(node_id, role="root"),
                nodes=[],
                edges=[],
                depth=max(1, int(depth or 1)),
                metadata={
                    "store": "postgres_projection",
                    "missing_root": node_id,
                    "node_count": 0,
                    "edge_count": 0,
                },
            )
        max_depth = max(1, int(depth or 1))
        allowed = {str(edge_type) for edge_type in edge_types or []}
        nodes_by_id = {root.node_id: root}
        edges_by_id: dict[str, GraphEdge] = {}
        queue: deque[tuple[str, int]] = deque([(root.node_id, 0)])
        seen_depth = {root.node_id: 0}

        while queue and len(nodes_by_id) <= limit:
            current_id, current_depth = queue.popleft()
            if current_depth >= max_depth:
                continue
            for node, edge in self._direct_neighbors(current_id):
                if allowed and edge.edge_type not in allowed:
                    continue
                nodes_by_id.setdefault(node.node_id, node)
                edges_by_id.setdefault(edge.edge_id, edge)
                if seen_depth.get(node.node_id, max_depth + 1) > current_depth + 1:
                    seen_depth[node.node_id] = current_depth + 1
                    queue.append((node.node_id, current_depth + 1))
                if len(nodes_by_id) >= limit:
                    break

        return GraphExpansion(
            root=root,
            nodes=[node for node_id_value, node in nodes_by_id.items() if node_id_value != root.node_id],
            edges=list(edges_by_id.values())[:limit],
            depth=max_depth,
            metadata={
                "store": "postgres_projection",
                "node_count": len(nodes_by_id),
                "edge_count": len(edges_by_id),
                "traversal": "semantic_edges_with_direction_metadata",
            },
        )

    def paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 10,
    ) -> list[GraphPath]:
        source = self.get_node(source_id)
        target = self.get_node(target_id)
        self.last_path_metadata = {
            "store": "postgres_projection",
            "source_id": source_id,
            "target_id": target_id,
        }
        if source is None:
            self.last_path_metadata["missing_source"] = source_id
            return []
        if target is None:
            self.last_path_metadata["missing_target"] = target_id
            return []
        paths: list[GraphPath] = []
        queue: deque[tuple[str, list[GraphNode], list[GraphEdge]]] = deque([(source.node_id, [source], [])])
        max_hops = max(1, int(max_depth or 1))

        while queue and len(paths) < limit:
            current_id, nodes, edges = queue.popleft()
            if len(edges) >= max_hops:
                continue
            for next_node, edge in self._direct_neighbors(current_id):
                if next_node.node_id in {node.node_id for node in nodes}:
                    continue
                next_nodes = [*nodes, next_node]
                next_edges = [*edges, edge]
                if next_node.node_id == target.node_id:
                    paths.append(GraphPath(nodes=next_nodes, edges=next_edges, score=_path_score(next_edges)))
                    if len(paths) >= limit:
                        break
                else:
                    queue.append((next_node.node_id, next_nodes, next_edges))
        self.last_path_metadata["path_count"] = len(paths)
        return paths

    def search_nodes(self, query: GraphQuery) -> list[GraphNode]:
        if query.node_id:
            node = self.get_node(query.node_id)
            return [node] if node is not None else []
        text = str(query.metadata.get("query") or query.metadata.get("text") or query.metadata.get("topic") or "")
        topic = query.metadata.get("topic")
        limit = max(1, int(query.limit or 1))
        if query.node_type == "entity":
            return [_node_from_entity(item) for item in self.repository.search_entities(query=text, limit=limit)]
        if query.node_type == "event":
            return [_node_from_event(item) for item in self.repository.search_events(query=text, topic=topic, limit=limit)]
        if query.node_type == "claim":
            return [_node_from_claim(item) for item in self.repository.search_claims(query=text, topic=topic, limit=limit)]
        if query.node_type == "evidence":
            return [_node_from_evidence(item) for item in self.repository.search_evidence(query=text, topic=topic, limit=limit)]
        if query.node_type == "decision":
            return [_node_from_decision(item) for item in self.repository.search_decisions(query=text, topic=topic, limit=limit)]
        if query.node_type == "preference":
            return [_node_from_preference(item) for item in self.repository.search_preferences(query=text, topic=topic, limit=limit)]
        if query.node_type == "topic" and text:
            return [GraphNode(node_id=f"topic:{text}", node_type="topic", label=text, metadata={"topic": text})]
        return []

    def _direct_neighbors(self, node_id: str) -> list[tuple[GraphNode, GraphEdge]]:
        event = self._event_object(node_id)
        if event is not None:
            return self._event_neighbors(event)
        entity = self._entity_object(node_id)
        if entity is not None:
            return self._entity_neighbors(entity)
        claim = self._claim_object(node_id)
        if claim is not None:
            return self._claim_neighbors(claim)
        evidence = self._first(self.repository.search_evidence(query=node_id, limit=1))
        if evidence is not None and evidence.evidence_id == node_id:
            return self._evidence_neighbors(evidence)
        return []

    def _entity_neighbors(self, entity: Any) -> list[tuple[GraphNode, GraphEdge]]:
        result: list[tuple[GraphNode, GraphEdge]] = []
        for event in self.repository.list_events_by_entity(entity.entity_id, limit=20):
            result.append(
                (
                    _node_from_event(event),
                    _edge(
                        event.event_id,
                        entity.entity_id,
                        "involves",
                        confidence=0.8,
                        traversal_direction="incoming",
                    ),
                )
            )
        for claim in self.repository.list_claims_by_entity(entity.entity_id, limit=20):
            result.append((_node_from_claim(claim), _edge(entity.entity_id, claim.claim_id, "related_to", confidence=0.5)))
        return result

    def _event_neighbors(self, event: Any) -> list[tuple[GraphNode, GraphEdge]]:
        result: list[tuple[GraphNode, GraphEdge]] = []
        for entity_id in event.entity_ids:
            node = self.get_node(entity_id) or _missing_node(entity_id, role="entity")
            result.append((node, _edge(event.event_id, entity_id, "involves", confidence=0.8)))
        for claim_id in event.claim_ids:
            node = self.get_node(claim_id) or _missing_node(claim_id, role="claim")
            result.append((node, _edge(event.event_id, claim_id, "has_claim", confidence=0.7)))
        for evidence_id in event.evidence_ids:
            node = self.get_node(evidence_id) or _missing_node(evidence_id, role="evidence")
            result.append((node, _edge(event.event_id, evidence_id, "supported_by", confidence=0.7)))
        if event.topic:
            topic_node = GraphNode(node_id=f"topic:{event.topic}", node_type="topic", label=event.topic)
            result.append(
                (
                    topic_node,
                    _edge(
                        f"topic:{event.topic}",
                        event.event_id,
                        "contains",
                        confidence=0.6,
                        traversal_direction="incoming",
                    ),
                )
            )
        return result

    def _claim_neighbors(self, claim: Any) -> list[tuple[GraphNode, GraphEdge]]:
        result: list[tuple[GraphNode, GraphEdge]] = []
        for evidence in self.repository.list_evidence_for_claim(claim.claim_id):
            result.append((_node_from_evidence(evidence), _edge(claim.claim_id, evidence.evidence_id, "supported_by", confidence=0.8)))
        for evidence_id in claim.contradicted_by:
            node = self.get_node(evidence_id) or _missing_node(evidence_id, role="evidence")
            result.append((node, _edge(claim.claim_id, evidence_id, "contradicted_by", confidence=0.8)))
        return result

    def _evidence_neighbors(self, evidence: Any) -> list[tuple[GraphNode, GraphEdge]]:
        result: list[tuple[GraphNode, GraphEdge]] = []
        if evidence.source_id:
            source_node = GraphNode(
                node_id=f"source:{evidence.source_id}",
                node_type="source",
                label=evidence.source_name or evidence.source_id,
            )
            result.append(
                (
                    source_node,
                    _edge(
                        f"source:{evidence.source_id}",
                        evidence.evidence_id,
                        "published",
                        confidence=evidence.confidence,
                        traversal_direction="incoming",
                    ),
                )
            )
        if evidence.topic:
            topic_node = GraphNode(node_id=f"topic:{evidence.topic}", node_type="topic", label=evidence.topic)
            result.append(
                (
                    topic_node,
                    _edge(
                        f"topic:{evidence.topic}",
                        evidence.evidence_id,
                        "contains",
                        confidence=0.5,
                        traversal_direction="incoming",
                    ),
                )
            )
        return result

    def _entity_node(self, node_id: str) -> GraphNode | None:
        entity = self._entity_object(node_id)
        return _node_from_entity(entity) if entity is not None else None

    def _event_node(self, node_id: str) -> GraphNode | None:
        event = self._event_object(node_id)
        return _node_from_event(event) if event is not None else None

    def _claim_node(self, node_id: str) -> GraphNode | None:
        claim = self._claim_object(node_id)
        return _node_from_claim(claim) if claim is not None else None

    def _evidence_node(self, node_id: str) -> GraphNode | None:
        evidence = self._first(self.repository.search_evidence(query=node_id, limit=1))
        if evidence is None or evidence.evidence_id != node_id:
            return None
        return _node_from_evidence(evidence)

    def _decision_node(self, node_id: str) -> GraphNode | None:
        decision = self._first(self.repository.search_decisions(query=node_id, limit=1))
        if decision is None or decision.decision_id != node_id:
            return None
        return _node_from_decision(decision)

    def _preference_node(self, node_id: str) -> GraphNode | None:
        preference = self._first(self.repository.search_preferences(query=node_id, limit=1))
        if preference is None or preference.preference_id != node_id:
            return None
        return _node_from_preference(preference)

    def _entity_object(self, node_id: str) -> Any | None:
        method = getattr(self.repository, "get_entity", None)
        return method(node_id) if callable(method) else None

    def _event_object(self, node_id: str) -> Any | None:
        method = getattr(self.repository, "get_event", None)
        return method(node_id) if callable(method) else None

    def _claim_object(self, node_id: str) -> Any | None:
        method = getattr(self.repository, "get_claim", None)
        return method(node_id) if callable(method) else None

    def _first(self, items: list[Any]) -> Any | None:
        return items[0] if items else None


def _node_from_entity(entity: Any) -> GraphNode:
    return GraphNode(
        node_id=entity.entity_id,
        node_type="entity",
        label=entity.canonical_name,
        summary=entity.summary,
        score=max(entity.importance_score, entity.trend_score),
        created_at=entity.first_seen_at,
        updated_at=entity.last_seen_at,
        metadata={"entity_type": entity.entity_type, "aliases": list(entity.aliases), **dict(entity.metadata)},
    )


def _node_from_event(event: Any) -> GraphNode:
    return GraphNode(
        node_id=event.event_id,
        node_type="event",
        label=event.title,
        summary=event.summary,
        score=max(event.impact_score, event.novelty_score),
        created_at=event.detected_at,
        updated_at=event.event_time or event.detected_at,
        metadata={"event_type": event.event_type, "topic": event.topic, "status": event.status},
    )


def _node_from_claim(claim: Any) -> GraphNode:
    return GraphNode(
        node_id=claim.claim_id,
        node_type="claim",
        label=claim.text,
        summary=claim.text,
        score=claim.confidence,
        created_at=claim.first_seen_at,
        updated_at=claim.last_seen_at,
        metadata={"status": claim.status, **dict(claim.metadata)},
    )


def _node_from_evidence(evidence: Any) -> GraphNode:
    return GraphNode(
        node_id=evidence.evidence_id,
        node_type="evidence",
        label=evidence.title,
        summary=evidence.summary,
        score=evidence.confidence,
        created_at=evidence.fetched_at or evidence.published_at,
        updated_at=evidence.fetched_at or evidence.published_at,
        metadata={"source_id": evidence.source_id, "topic": evidence.topic, "source_urls": evidence.normalized_source_urls()},
    )


def _node_from_decision(decision: Any) -> GraphNode:
    return GraphNode(
        node_id=decision.decision_id,
        node_type="decision",
        label=f"{decision.decision_type}: {decision.decision}",
        summary=decision.reason,
        score=1.0 if decision.is_positive() else 0.0,
        created_at=decision.created_at,
        metadata={"target_type": decision.target_type, "target_id": decision.target_id, **dict(decision.metadata)},
    )


def _node_from_preference(preference: Any) -> GraphNode:
    return GraphNode(
        node_id=preference.preference_id,
        node_type="preference",
        label=f"{preference.preference_type}: {preference.content}",
        summary=preference.content,
        score=preference.weight,
        created_at=preference.created_at,
        updated_at=preference.updated_at,
        metadata={"owner_type": preference.owner_type, "owner_id": preference.owner_id, **dict(preference.metadata)},
    )


def _edge(
    source_id: str,
    target_id: str,
    edge_type: str,
    *,
    confidence: float = 0.5,
    weight: float = 1.0,
    traversal_direction: str = "outgoing",
) -> GraphEdge:
    return GraphEdge(
        edge_id=f"{edge_type}:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=cast(GraphEdgeType, edge_type),
        confidence=confidence,
        weight=weight,
        metadata={"traversal_direction": traversal_direction},
    )


def _missing_node(node_id: str, *, role: str) -> GraphNode:
    return GraphNode(node_id=node_id, node_type="unknown", label=node_id, metadata={"missing": True, "role": role})


def _path_score(edges: list[GraphEdge]) -> float:
    if not edges:
        return 0.0
    return sum(edge.confidence * edge.weight for edge in edges) / len(edges)


__all__ = ["PostgresGraphMemoryStore"]
