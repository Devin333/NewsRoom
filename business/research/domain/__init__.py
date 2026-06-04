from __future__ import annotations

from business.research.domain.analysis import ResearchAnalysis, ThreeMinuteRead
from business.research.domain.common import (
    CandidateReview,
    CandidateStatus,
    EvidenceRef,
    GateResult,
    QualityFlag,
    ResearchValidationSeverity,
    SourceLineage,
    SourceScopedValue,
    stable_research_id,
)
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchReference,
    ResearchSection,
    ResearchTable,
)
from business.research.domain.evidence import ResearchClaim, ResearchEvidenceItem, ResearchEvidencePack
from business.research.domain.paper import PaperSourceRecord, ResearchPaper
from business.research.domain.quality import ResearchQualityResult
from business.research.domain.reader import ReaderAnnotation, ReaderNavigationItem, ResearchReaderPayload
from business.research.domain.reader_repair import (
    ReaderIssue,
    ReaderIssueType,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairStrategy,
)

__all__ = [
    "CandidateReview",
    "CandidateStatus",
    "EvidenceRef",
    "GateResult",
    "PaperSourceRecord",
    "QualityFlag",
    "ReaderAnnotation",
    "ReaderIssue",
    "ReaderIssueType",
    "ReaderNavigationItem",
    "ReaderRepairCase",
    "ReaderRepairContextPack",
    "ReaderRepairStrategy",
    "ResearchAnalysis",
    "ResearchClaim",
    "ResearchDocument",
    "ResearchEquation",
    "ResearchEvidenceItem",
    "ResearchEvidencePack",
    "ResearchFigure",
    "ResearchPaper",
    "ResearchQualityResult",
    "ResearchReaderPayload",
    "ResearchReference",
    "ResearchSection",
    "ResearchTable",
    "ResearchValidationSeverity",
    "SourceLineage",
    "SourceScopedValue",
    "ThreeMinuteRead",
    "stable_research_id",
]
