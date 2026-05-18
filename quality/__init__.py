"""Quality gate package."""

from quality.citation_checker import CitationCheckResult, CitationChecker
from quality.editor_gate import EditorDecision, EditorGate, EditorReview, RewritePolicy
from quality.eval_dataset import golden_quality_eval_cases, run_quality_eval_case
from quality.errors import QualityError, QualityErrorType, quality_error_policy
from quality.models import (
    BlockedReport,
    CitationFailureCategory,
    CitationSectionResult,
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
    "BlockedReport",
    "CitationFailureCategory",
    "CitationSectionResult",
    "EditorDecision",
    "EditorGate",
    "EditorReview",
    "golden_quality_eval_cases",
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
    "run_quality_eval_case",
    "SectionSupport",
    "SupportMatrix",
    "SupportMatrixBuilder",
    "quality_error_policy",
]
