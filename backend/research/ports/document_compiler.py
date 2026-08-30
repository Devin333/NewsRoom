from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.domain.document import ResearchDocument
from backend.research.domain.paper import PaperSourceRecord


@runtime_checkable
class DocumentCompilerPort(Protocol):
    def compile(self, source: PaperSourceRecord) -> ResearchDocument:
        ...


__all__ = ["DocumentCompilerPort"]
