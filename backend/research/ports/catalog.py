from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.domain.catalog import (
    ResearchPaperCatalogEntry,
    ResearchPaperIdentity,
    ResearchPaperRelation,
    ResearchSourceSnapshot,
)


@runtime_checkable
class ResearchPaperCatalogRepository(Protocol):
    def get(self, paper_id: str) -> ResearchPaperCatalogEntry | None: ...

    def save(self, entry: ResearchPaperCatalogEntry) -> None: ...

    def search(self, query: str = "", *, limit: int = 50) -> list[ResearchPaperCatalogEntry]: ...


@runtime_checkable
class ResearchPaperIdentityRepository(Protocol):
    def get(self, paper_id: str) -> ResearchPaperIdentity | None: ...

    def find_by_external_id(self, external_id: str) -> ResearchPaperIdentity | None: ...

    def save(self, identity: ResearchPaperIdentity) -> None: ...


@runtime_checkable
class ResearchPaperRelationRepository(Protocol):
    def list_for_paper(self, paper_id: str) -> list[ResearchPaperRelation]: ...

    def save(self, relation: ResearchPaperRelation) -> None: ...


@runtime_checkable
class ResearchSourceSnapshotRepository(Protocol):
    def get(self, snapshot_id: str) -> ResearchSourceSnapshot | None: ...

    def list_for_paper(self, paper_id: str) -> list[ResearchSourceSnapshot]: ...

    def save(self, snapshot: ResearchSourceSnapshot) -> None: ...


__all__ = [
    "ResearchPaperCatalogRepository",
    "ResearchPaperIdentityRepository",
    "ResearchPaperRelationRepository",
    "ResearchSourceSnapshotRepository",
]
