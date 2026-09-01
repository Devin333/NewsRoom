from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from backend.research.domain.catalog import ResearchSourceSnapshot, SourceAccessStatus
from backend.research.domain.paper import PaperSourceRecord, ResearchPaper


@dataclass(frozen=True)
class ResolvedPaperSource:
    """Source adapter output shared by application and infrastructure."""

    paper: ResearchPaper
    snapshot: ResearchSourceSnapshot
    content: bytes | None = None
    content_type: str | None = None
    source_record: PaperSourceRecord | None = None
    access_status: SourceAccessStatus = "available"
    diagnostics: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.paper, ResearchPaper):
            raise TypeError("paper must be ResearchPaper")
        if not isinstance(self.snapshot, ResearchSourceSnapshot):
            raise TypeError("snapshot must be ResearchSourceSnapshot")
        if self.content is not None and not isinstance(self.content, bytes):
            raise TypeError("content must be bytes or None")


@runtime_checkable
class ResearchSourceResolver(Protocol):
    def resolve(self, request: Any) -> ResolvedPaperSource: ...


__all__ = ["ResolvedPaperSource", "ResearchSourceResolver"]
