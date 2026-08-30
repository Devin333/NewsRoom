from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.foundation.models import DetailPage, Insight, Relation, Report, Signal
from backend.foundation.taxonomy import BoardType


class SignalSearchQuery(Protocol):
    query: str


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
class DetailPageRepository(Protocol):
    def save_detail_pages(self, pages: list[DetailPage]) -> None: ...

    def latest(self, board_type: BoardType | None, limit: int) -> list[DetailPage]: ...


@runtime_checkable
class ReportRepository(Protocol):
    def save_reports(self, reports: list[Report]) -> None: ...

    def latest(self, board_type: BoardType | None, limit: int) -> list[Report]: ...


__all__ = [
    "DetailPageRepository",
    "InsightRepository",
    "RelationRepository",
    "ReportRepository",
    "SignalRepository",
    "SignalSearchQuery",
]
