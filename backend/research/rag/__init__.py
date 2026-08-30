from __future__ import annotations

from backend.research.rag.evaluation.paper_answer_eval import (
    EvidenceAnswerEvalResult,
    EvidenceAnswerEvaluator,
    EvidenceAnswerSample,
    EvidenceAnswerScores,
)
from backend.research.rag.evaluation.paper_evidence_eval import (
    EvidenceEvalResult,
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    EvidenceRetrievalEvaluator,
    EvidenceSampleResult,
    build_evidence_pairs_from_chunks,
    load_evidence_golden_set,
    save_evidence_golden_set,
)
from backend.research.rag.evaluation.paper_evaluation_compare import (
    EvidenceABComparator,
    EvidenceABDelta,
    EvidenceABResult,
    compare_evidence_results,
)
from backend.research.rag.evaluation.paper_evaluation_report import EvidenceRegressionReport
from backend.research.rag.evaluation.paper_fixed_window_baseline import FixedWindowBaselineChunker, FixedWindowChunkerConfig
from backend.research.rag.models import ResearchRAGContext, ResearchRAGGapReport, ResearchRetrievalGoal

__all__ = [
    "EvidenceAnswerEvalResult",
    "EvidenceAnswerEvaluator",
    "EvidenceAnswerSample",
    "EvidenceAnswerScores",
    "EvidenceABComparator",
    "EvidenceABDelta",
    "EvidenceABResult",
    "EvidenceRegressionReport",
    "FixedWindowBaselineChunker",
    "FixedWindowChunkerConfig",
    "EvidenceEvalResult",
    "EvidenceGoldenSetBuilder",
    "EvidenceQAPair",
    "EvidenceRetrievalEvaluator",
    "EvidenceSampleResult",
    "ResearchRAGContext",
    "ResearchRAGGapReport",
    "ResearchRetrievalGoal",
    "build_evidence_pairs_from_chunks",
    "compare_evidence_results",
    "load_evidence_golden_set",
    "save_evidence_golden_set",
]
