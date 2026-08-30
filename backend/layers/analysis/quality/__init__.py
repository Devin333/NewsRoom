"""Quality gate package."""

from backend.layers.analysis.quality.citation_checker import CitationCheckResult, CitationChecker
from backend.layers.analysis.quality.editor_gate import EditorDecision, EditorGate, EditorReview, RewritePolicy
from backend.layers.analysis.quality.eval_dataset import golden_quality_eval_cases, run_quality_eval_case
from backend.layers.analysis.quality.errors import QualityError, QualityErrorType, quality_error_policy
from backend.layers.analysis.quality.models import (
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
from backend.layers.analysis.quality.scoring import QualityScorer, ReportQualitySummary
from backend.layers.analysis.quality.support_matrix import SectionSupport, SupportMatrix, SupportMatrixBuilder

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
