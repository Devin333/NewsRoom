from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, normalize_key
from business.research.domain.common import require_text, unique_texts


class ResearchMethod(PrimitiveModel):
    method_id: str
    name: str
    paper_id: str | None = None
    description: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("method_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "method fields")

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchMethod":
        object.__setattr__(self, "method_id", normalize_key(self.method_id))
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        return self


class MethodGraphEdge(PrimitiveModel):
    edge_id: str
    source_id: str
    target_id: str
    relation_type: Literal[
        "proposes",
        "evaluates_on",
        "reports_score",
        "compares_with",
        "uses_dataset",
        "claims_sota",
        "supports_task",
    ]
    paper_id: str
    evidence_refs: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("edge_id", "source_id", "target_id", "paper_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "method graph edge fields")

    @field_validator("evidence_refs")
    @classmethod
    def _require_evidence_refs(cls, value: list[str]) -> list[str]:
        refs = unique_texts(value)
        if not refs:
            raise ValueError("method graph edge requires evidence refs")
        return refs


class MethodGraph(PrimitiveModel):
    graph_id: str
    methods: list[ResearchMethod] = Field(default_factory=list)
    edges: list[MethodGraphEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("graph_id")
    @classmethod
    def _required_graph_id(cls, value: str) -> str:
        return require_text(value, "method graph id")

    @model_validator(mode="after")
    def _dedupe_edges(self) -> "MethodGraph":
        seen: set[str] = set()
        edges: list[MethodGraphEdge] = []
        for edge in self.edges:
            key = f"{edge.source_id}|{edge.target_id}|{edge.relation_type}|{edge.paper_id}"
            if key not in seen:
                seen.add(key)
                edges.append(edge)
        object.__setattr__(self, "edges", edges)
        return self


__all__ = ["MethodGraph", "MethodGraphEdge", "ResearchMethod"]
