from __future__ import annotations

from business.research.domain.reader import ResearchReaderPayload
from business.research.domain.reader_repair import ReaderIssue
from business.research.domain.common import stable_research_id


class ReaderIssueDetector:
    def detect(self, payload: ResearchReaderPayload) -> list[ReaderIssue]:
        issues: list[ReaderIssue] = []
        if not payload.source_lineage.source_refs:
            issues.append(
                ReaderIssue(
                    issue_id=stable_research_id("reader_issue", payload.payload_id, "source_lineage_missing"),
                    paper_id=payload.paper.paper_id,
                    issue_type="source_lineage_missing",
                    severity="critical",
                    error_signature="source_lineage_missing",
                    symptom="Reader payload has no source refs.",
                    payload_ref=payload.payload_id,
                )
            )
        if not payload.document.sections:
            issues.append(
                ReaderIssue(
                    issue_id=stable_research_id("reader_issue", payload.payload_id, "section_boundary_error"),
                    paper_id=payload.paper.paper_id,
                    issue_type="section_boundary_error",
                    severity="high",
                    error_signature="no_sections",
                    symptom="Reader payload document has no sections.",
                    source_refs=payload.source_lineage.source_refs,
                    payload_ref=payload.payload_id,
                )
            )
        return issues


__all__ = ["ReaderIssueDetector"]
