from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from backend.research.domain.catalog import (
    ResearchPaperCatalogEntry,
    ResearchPaperIdentity,
    ResearchPaperRelation,
    ResearchSourceSnapshot,
)
from backend.research.domain.code_repository import CodeRepositoryProfile
from backend.research.benchmark.models import ResearchSOTAClaim


@runtime_checkable
class ResearchPaperCatalogRepository(Protocol):
    def get(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperCatalogEntry | None: ...

    def save(self, entry: ResearchPaperCatalogEntry) -> None: ...

    def search(
        self,
        query: str = "",
        *,
        limit: int = 50,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperCatalogEntry]: ...


@runtime_checkable
class ResearchPaperIdentityRepository(Protocol):
    def get(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperIdentity | None: ...

    def find_by_external_id(
        self,
        external_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperIdentity | None: ...

    def find_by_fingerprint(
        self,
        fingerprint: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperIdentity | None: ...

    def save(self, identity: ResearchPaperIdentity) -> None: ...


@runtime_checkable
class ResearchPaperRelationRepository(Protocol):
    def list_for_paper(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperRelation]: ...

    def save(self, relation: ResearchPaperRelation) -> None: ...


@runtime_checkable
class ResearchSourceSnapshotRepository(Protocol):
    def get(
        self,
        snapshot_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchSourceSnapshot | None: ...

    def list_for_paper(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchSourceSnapshot]: ...

    def save(self, snapshot: ResearchSourceSnapshot) -> None: ...


@runtime_checkable
class ResearchCodeRepositoryProfileRepository(Protocol):
    def save_code_profile(self, profile: CodeRepositoryProfile) -> None: ...

    def list_code_profiles(
        self,
        paper_id: str | None = None,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[CodeRepositoryProfile]: ...


@runtime_checkable
class ResearchSOTAClaimRepository(Protocol):
    def save_sota_claim(self, claim: ResearchSOTAClaim) -> None: ...

    def list_sota_claims(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchSOTAClaim]: ...


@runtime_checkable
class ResearchPaperCatalogQueryPort(Protocol):
    """Read-only Catalog contract used by API and CLI application services."""

    def get_catalog(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperCatalogEntry | None: ...

    def search_papers(
        self,
        query: str = "",
        *,
        limit: int = 50,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperCatalogEntry]: ...

    def list_sources(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchSourceSnapshot]: ...

    def list_relations(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperRelation]: ...


# Short aliases keep the ports convenient for adapters while the explicit names
# remain the canonical public contract.
CatalogRepository = ResearchPaperCatalogRepository
PaperIdentityRepository = ResearchPaperIdentityRepository
SourceSnapshotRepository = ResearchSourceSnapshotRepository


__all__ = [
    "ResearchPaperCatalogRepository",
    "ResearchPaperIdentityRepository",
    "ResearchPaperRelationRepository",
    "ResearchSourceSnapshotRepository",
    "ResearchCodeRepositoryProfileRepository",
    "ResearchSOTAClaimRepository",
    "ResearchPaperCatalogQueryPort",
    "CatalogRepository",
    "PaperIdentityRepository",
    "SourceSnapshotRepository",
]
