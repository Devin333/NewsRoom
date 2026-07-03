from __future__ import annotations

from business.research.rag.retrieval.paper_answer_generator import (
    AnswerContextAssembler,
    AnswerContextSelection,
    AnswerGenerator,
    GeneratedAnswer,
)
from business.research.rag.retrieval.paper_policy import (
    QueryIntent,
    RetrievalRoute,
    build_retrieval_route,
    classify_query_intent,
)
from business.research.rag.retrieval.plan import (
    ChannelSpec,
    ExpanderSpec,
    FusionSpec,
    RerankSpec,
    RetrievalPlan,
)
from business.research.rag.retrieval.planner import QueryPlanner
from business.research.rag.retrieval.paper_claim_index import (
    ClaimRecord,
    ClaimSearchHit,
    PaperClaimIndex,
    PaperClaimSearchPort,
    extract_claim_records,
)
from business.research.rag.retrieval.contracts import RetrievalRequest, RetrievalResult
from business.research.rag.retrieval.metrics import RetrievalMetricsBuilder
from business.research.rag.retrieval.paper_retriever import ResearchRetriever
from business.research.rag.retrieval.policies import (
    DEFAULT_RETRIEVAL_POLICY,
    NEWS_PAPER_RAG_POLICY_ENV,
    PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
    PAPER_FORMULA_RAG_V1_POLICY,
    PAPER_HYBRID_RRF_RAG_V1_POLICY,
    PAPER_VISUAL_RAG_TUNED_POLICY,
    RetrievalPolicy,
    build_retrieval_policy,
    build_retrieval_policy_from_env,
    retrieval_policy_enables_lightweight_reranker,
)
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    fuse_visual_retrieval_scores,
    visual_fusion_score,
    with_retrieval_scores,
)
from business.research.rag.retrieval.pipeline import RetrievalPipeline
from business.research.rag.retrieval.channels import RankedHit, RankedList, RecallChannel
from business.research.rag.retrieval.expanders import (
    ContextExpander,
    CrossRefContextExpander,
    FormulaContextExpander,
    ParentContextExpander,
    StructuralContextExpander,
    SupplementalTableHitExpander,
    TableContextExpander,
)
from business.research.rag.retrieval.fusion import fuse_chunk_rankings, fuse_ranked_hits
from business.research.rag.retrieval.policy_config import policy_config_hash, stable_policy_config
from business.research.rag.retrieval.ranking_stage import ChildRankingResult, ChildRankingStage
from business.research.rag.retrieval.recall_stage import CandidateRecallResult, CandidateRecallStage
from business.research.rag.retrieval.rerank import RerankCascade, field_rerank_passage
from business.research.rag.retrieval.scoring import ChildCandidateScorer
from business.research.rag.retrieval.trace import RetrievalDegradation, RetrievalTrace

__all__ = [
    "AnswerContextAssembler",
    "AnswerContextSelection",
    "AnswerGenerator",
    "ChannelSpec",
    "CandidateRecallResult",
    "CandidateRecallStage",
    "ClaimRecord",
    "ClaimSearchHit",
    "ChildCandidateScorer",
    "ChildRankingResult",
    "ChildRankingStage",
    "ContextExpander",
    "CrossRefContextExpander",
    "DEFAULT_RETRIEVAL_POLICY",
    "GeneratedAnswer",
    "ExpanderSpec",
    "FusionSpec",
    "FormulaContextExpander",
    "NEWS_PAPER_RAG_POLICY_ENV",
    "PAPER_BLIND_SEMANTIC_RAG_V1_POLICY",
    "PAPER_FORMULA_RAG_V1_POLICY",
    "PAPER_HYBRID_RRF_RAG_V1_POLICY",
    "PAPER_VISUAL_RAG_TUNED_POLICY",
    "PaperVisualFusionWeights",
    "ParentContextExpander",
    "PaperClaimIndex",
    "PaperClaimSearchPort",
    "QueryIntent",
    "QueryPlanner",
    "RankedHit",
    "RankedList",
    "RecallChannel",
    "ResearchRetriever",
    "RetrievalPolicy",
    "RetrievalPlan",
    "RetrievalPipeline",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalRoute",
    "RerankSpec",
    "RerankCascade",
    "RetrievalDegradation",
    "RetrievalMetricsBuilder",
    "RetrievalTrace",
    "StructuralContextExpander",
    "SupplementalTableHitExpander",
    "TableContextExpander",
    "build_retrieval_policy",
    "build_retrieval_policy_from_env",
    "build_retrieval_route",
    "classify_query_intent",
    "extract_claim_records",
    "field_rerank_passage",
    "fuse_chunk_rankings",
    "fuse_ranked_hits",
    "fuse_visual_retrieval_scores",
    "retrieval_policy_enables_lightweight_reranker",
    "policy_config_hash",
    "stable_policy_config",
    "visual_fusion_score",
    "with_retrieval_scores",
]
