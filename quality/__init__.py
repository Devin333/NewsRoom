"""Quality gate package."""

from quality.citation_checker import CitationCheckResult, CitationChecker
from quality.editor_gate import EditorDecision, EditorGate, EditorReview, RewritePolicy
from quality.errors import QualityError, QualityErrorType, quality_error_policy
from quality.models import (
    HumanReviewDecision,
    HumanReviewRequest,
    QualityEvalCase,
    QualityEvalRecord,
    QualityEvent,
    QualityGateMetrics,
    QualityResult,
)
from quality.scoring import QualityScorer, ReportQualitySummary
from quality.support_matrix import SectionSupport, SupportMatrix, SupportMatrixBuilder

__all__ = [
    "CitationCheckResult",
    "CitationChecker",
    "EditorDecision",
    "EditorGate",
    "EditorReview",
    "HumanReviewDecision",
    "HumanReviewRequest",
    "QualityEvalCase",
    "QualityEvalRecord",
    "QualityEvent",
    "QualityError",
    "QualityErrorType",
    "QualityGateMetrics",
    "QualityResult",
    "QualityScorer",
    "ReportQualitySummary",
    "RewritePolicy",
    "SectionSupport",
    "SupportMatrix",
    "SupportMatrixBuilder",
    "quality_error_policy",
]
