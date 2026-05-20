from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from business.foundation.context import AnalysisContext
from business.foundation.models import DetailPage, Insight, ObjectRef, Relation, Report, Signal
from business.foundation.primitives import PrimitiveModel
from business.foundation.taxonomy import BoardType, RelationType, SignalType


class SignalSearchQuery(Protocol):
    query: str


class BusinessLLMRequest(PrimitiveModel):
    prompt: str
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BusinessLLMResult(PrimitiveModel):
    content: str | None = None
    structured: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphNeighbor(PrimitiveModel):
    object_ref: ObjectRef
    relation: Relation
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SignalRepository(Protocol):
    def save_signals(self, signals: list[Signal]) -> None: ...

    def find_by_ids(self, signal_ids: list[str]) -> list[Signal]: ...

    def search(self, query: SignalSearchQuery) -> list[Signal]: ...


@runtime_checkable
class RelationRepository(Protocol):
    def save_relations(self, relations: list[Relation]) -> None: ...

    def find_by_object(self, object_ref: Any) -> list[Relation]: ...

    def find_between(self, source_ref: Any, target_ref: Any) -> list[Relation]: ...


@runtime_checkable
class InsightRepository(Protocol):
    def save_insights(self, insights: list[Insight]) -> None: ...

    def latest(self, board_type: BoardType | None, limit: int) -> list[Insight]: ...


@runtime_checkable
class GraphRepository(Protocol):
    def upsert_relation(self, relation: Relation) -> None: ...

    def neighbors(self, object_ref: Any, relation_types: list[Any] | None) -> list[Any]: ...


@runtime_checkable
class IntelligenceGraphStore(Protocol):
    def upsert_object(self, object_ref: ObjectRef, properties: dict[str, Any]) -> None: ...

    def upsert_relation(self, relation: Relation) -> None: ...

    def neighbors(self, object_ref: ObjectRef, relation_types: list[RelationType] | None) -> list[GraphNeighbor]: ...


@runtime_checkable
class LLMPort(Protocol):
    def structured_output(self, *, prompt: str, schema: dict[str, Any], context: AnalysisContext) -> dict[str, Any]: ...


@runtime_checkable
class LLMGateway(Protocol):
    def complete(self, request: BusinessLLMRequest) -> BusinessLLMResult: ...


@runtime_checkable
class SourcePort(Protocol):
    def fetch(self, signal_type: SignalType, *, limit: int, context: AnalysisContext) -> list[Signal]: ...


@runtime_checkable
class BoardService(Protocol):
    board_type: BoardType

    def build_board_output(self, signals: list[Signal], *, context: AnalysisContext | None = None) -> Any: ...


@runtime_checkable
class DetailPageRepository(Protocol):
    def save_detail_pages(self, pages: list[DetailPage]) -> None: ...

    def latest(self, board_type: BoardType | None, limit: int) -> list[DetailPage]: ...


@runtime_checkable
class ReportRepository(Protocol):
    def save_reports(self, reports: list[Report]) -> None: ...

    def latest(self, board_type: BoardType | None, limit: int) -> list[Report]: ...
