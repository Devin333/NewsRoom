from __future__ import annotations

from backend.research.domain.analysis import ResearchAnalysis
from backend.research.domain.common import SourceLineage, stable_research_id
from backend.research.domain.document import ResearchDocument
from backend.research.domain.evidence import ResearchEvidencePack
from backend.research.domain.paper import ResearchPaper
from backend.research.domain.reader import ReaderNavigationItem, ResearchReaderPayload


class ReaderPayloadBuilder:
    def build(
        self,
        *,
        paper: ResearchPaper,
        document: ResearchDocument,
        analysis: ResearchAnalysis | None = None,
        evidence: ResearchEvidencePack | None = None,
    ) -> ResearchReaderPayload:
        navigation = [
            ReaderNavigationItem(
                item_id=stable_research_id("nav", document.paper_id, section.section_id),
                title=section.title,
                target_ref=section.section_id,
                level=section.level,
                order=index,
            )
            for index, section in enumerate(document.sections)
        ]
        return ResearchReaderPayload(
            payload_id=stable_research_id("reader_payload", paper.paper_id, document.source_hash),
            paper=paper,
            document=document,
            analysis=analysis,
            evidence=evidence,
            navigation=navigation,
            annotations=[],
            source_lineage=SourceLineage(
                source_refs=document.lineage.source_refs,
                source_hash=document.source_hash,
                artifact_refs=document.lineage.artifact_refs,
            ),
            status="ready" if document.sections else "needs_repair",
        )


__all__ = ["ReaderPayloadBuilder"]
