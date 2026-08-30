from __future__ import annotations

from backend.research.domain.document import ResearchDocument
from backend.research.domain.paper import ResearchPaper
from backend.research.domain.reader import ResearchReaderPayload
from backend.research.reader.payload_builder import ReaderPayloadBuilder


class BuildReaderUseCase:
    def __init__(self, builder: ReaderPayloadBuilder | None = None) -> None:
        self._builder = builder or ReaderPayloadBuilder()

    def build(self, *, paper: ResearchPaper, document: ResearchDocument) -> ResearchReaderPayload:
        return self._builder.build(paper=paper, document=document)


__all__ = ["BuildReaderUseCase"]
