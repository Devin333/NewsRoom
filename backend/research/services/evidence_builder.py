from __future__ import annotations

from backend.research.domain.common import SourceLineage, stable_research_id
from backend.research.domain.document import ResearchDocument
from backend.research.domain.evidence import ResearchEvidenceItem, ResearchEvidencePack


class ResearchEvidenceBuilder:
    def build_from_document(self, *, pack_id: str | None = None, document: ResearchDocument) -> ResearchEvidencePack:
        items = [
            ResearchEvidenceItem(
                evidence_id=stable_research_id("evidence", document.paper_id, section.section_id),
                paper_id=document.paper_id,
                title=section.title,
                summary=section.text[:300],
                evidence_type="section",
                source_ref=section.source_ref,
                span_refs=[section.section_id],
                confidence=1.0,
                lineage=SourceLineage(source_refs=[section.source_ref], source_hash=document.source_hash),
            )
            for section in document.sections
        ]
        source_refs = sorted({section.source_ref for section in document.sections} or set(document.lineage.source_refs))
        return ResearchEvidencePack(
            pack_id=pack_id or stable_research_id("evidence_pack", document.paper_id, document.source_hash),
            paper_id=document.paper_id,
            items=items,
            coverage={"sections": 1.0 if document.sections else 0.0},
            missing_information=[] if document.sections else ["sections"],
            lineage=SourceLineage(source_refs=source_refs, source_hash=document.source_hash),
        )


__all__ = ["ResearchEvidenceBuilder"]
