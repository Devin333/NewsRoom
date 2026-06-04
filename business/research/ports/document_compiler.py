from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.domain.document import ResearchDocument
from business.research.domain.paper import PaperSourceRecord


@runtime_checkable
class DocumentCompilerPort(Protocol):
    def compile(self, source: PaperSourceRecord) -> ResearchDocument:
        ...


__all__ = ["DocumentCompilerPort"]
