from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import (
    BoardType,
    BusinessQualityCheck,
    BusinessRegressionGuardResult,
    Confidence,
    ObjectRef,
    PrimitiveModel,
    RelationType,
    SourceRef,
)


class CrossBoardGraphNode(PrimitiveModel):
    node_id: str
    object_ref: ObjectRef
    board_type: BoardType | None = None
    stage_type: str | None = None
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraphEdge(PrimitiveModel):
    edge_id: str
    relation_id: str
    relation_type: RelationType
    source_node_id: str
    target_node_id: str
    source_ref: ObjectRef
    target_ref: ObjectRef
    board_type: BoardType | None = None
    stage_type: str | None = None
    confidence: Confidence
    evidence_signal_ids: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraph(PrimitiveModel):
    graph_id: str
    nodes: list[CrossBoardGraphNode] = Field(default_factory=list)
    edges: list[CrossBoardGraphEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardEvidenceChain(PrimitiveModel):
    chain_id: str
    evidence_count: int
    board_support_count: int
    min_relation_confidence: float
    average_relation_confidence: float
    duplicate_evidence_count: int
    contradictory_evidence_count: int
    missing_stage_count: int
    evidence_relation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    board_support: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardPath(PrimitiveModel):
    path_id: str
    technology_ref: ObjectRef
    ordered_nodes: list[CrossBoardGraphNode] = Field(default_factory=list)
    ordered_edges: list[CrossBoardGraphEdge] = Field(default_factory=list)
    evidence_relation_ids: list[str] = Field(default_factory=list)
    evidence_chain_refs: list[str] = Field(default_factory=list)
    board_sequence: list[str] = Field(default_factory=list)
    confidence: float
    path_score: float
    missing_stage_types: list[str] = Field(default_factory=list)
    duplicate_evidence_count: int = 0
    contradictory_evidence_count: int = 0
    quality_checks: list[BusinessQualityCheck] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    evidence_chain: CrossBoardEvidenceChain | None = None
    guard_result: BusinessRegressionGuardResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardPathSearchRequest(PrimitiveModel):
    technology_refs: list[ObjectRef] = Field(default_factory=list)
    required_stage_types: list[str] = Field(default_factory=list)
    limit: int = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardPathSearchResult(PrimitiveModel):
    graph: CrossBoardGraph
    paths: list[CrossBoardPath] = Field(default_factory=list)
    quality_summary: "CrossBoardGraphQualitySummary | None" = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardInsightCandidate(PrimitiveModel):
    candidate_id: str
    path: CrossBoardPath
    title: str
    summary: str
    evidence_chain: CrossBoardEvidenceChain
    guard_result: BusinessRegressionGuardResult
    score: float
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraphQualitySummary(PrimitiveModel):
    status: str
    path_count: int
    blocked_path_count: int
    warning_count: int
    checks: list[BusinessQualityCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraphIntelligenceResult(PrimitiveModel):
    graph: CrossBoardGraph
    paths: list[CrossBoardPath] = Field(default_factory=list)
    insights: list[CrossBoardInsightCandidate] = Field(default_factory=list)
    quality_summary: CrossBoardGraphQualitySummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CrossBoardEvidenceChain",
    "CrossBoardGraph",
    "CrossBoardGraphEdge",
    "CrossBoardGraphIntelligenceResult",
    "CrossBoardGraphNode",
    "CrossBoardGraphQualitySummary",
    "CrossBoardInsightCandidate",
    "CrossBoardPath",
    "CrossBoardPathSearchRequest",
    "CrossBoardPathSearchResult",
]
