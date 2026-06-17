from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.domain.document import ResearchDocument


@runtime_checkable
class DocumentParserPort(Protocol):
    """Parses raw source bytes (e.g. arXiv LaTeX tarball) into a ResearchDocument."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument: ...


__all__ = ["DocumentParserPort"]
