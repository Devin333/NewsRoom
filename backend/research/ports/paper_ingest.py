from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from backend.research.domain.document import ResearchDocument
from backend.research.domain.evidence import ResearchEvidencePack
from backend.research.domain.paper import ResearchPaper


@runtime_checkable
class ResearchDocumentRepository(Protocol):
    def get(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchDocument | None: ...

    def save(self, document: ResearchDocument) -> None: ...


@runtime_checkable
class ResearchEvidencePackRepository(Protocol):
    def get(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchEvidencePack | None: ...

    def save(self, evidence_pack: ResearchEvidencePack) -> None: ...


@runtime_checkable
class ResearchPaperReadRepository(Protocol):
    def get(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchPaper | None: ...

    def save(self, paper: ResearchPaper) -> None: ...


@runtime_checkable
class ResearchEventSink(Protocol):
    """Append-only event boundary used by ParsePaper."""

    def append(self, run_id: str, event: dict[str, Any]) -> None: ...


__all__ = [
    "ResearchDocumentRepository",
    "ResearchEvidencePackRepository",
    "ResearchEventSink",
    "ResearchPaperReadRepository",
]
