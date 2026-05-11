"""Quality gate package."""

from quality.citation_checker import CitationCheckResult, CitationChecker
from quality.editor_gate import EditorDecision, EditorGate, EditorReview
from quality.models import QualityEvent, QualityGateMetrics
from quality.scoring import QualityScorer, ReportQualitySummary
from quality.support_matrix import SectionSupport, SupportMatrix, SupportMatrixBuilder

__all__ = [
    "CitationCheckResult",
    "CitationChecker",
    "EditorDecision",
    "EditorGate",
    "EditorReview",
    "QualityEvent",
    "QualityGateMetrics",
    "QualityScorer",
    "ReportQualitySummary",
    "SectionSupport",
    "SupportMatrix",
    "SupportMatrixBuilder",
]
