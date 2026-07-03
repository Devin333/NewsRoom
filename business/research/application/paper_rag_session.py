from __future__ import annotations

from typing import TYPE_CHECKING

from framework.harness.rag.session import BoundedRAGSessionController, RAGSessionResult
from framework.harness.rag.models import RAGBudget
from framework.harness.rag.planner import WorkerRAGPlanner

from business.research.rag.models import ResearchRetrievalGoal
from business.research.rag.adapters import ResearchRAGPlanWorker
from business.research.rag.retrieval_port import PaperChunkRetrievalPort
from business.research.rag.retrieval.paper_retriever import ResearchRetriever
from business.research.rag.retrieval.policies import RetrievalPolicy
from business.research.services.rag_policy import ResearchRAGPolicyBuilder
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.field_embedding_index import FieldEmbeddingSearchPort
from business.research.ports.visual_chunk_index import VisualChunkSearchPort

if TYPE_CHECKING:
    from business.research.ports.llm_worker import ResearchCandidateWorkerPort
    from business.research.ports.reranker import RerankerPort


class PaperRAGSession:
    """
    Wires ResearchRetriever into BoundedRAGSessionController via PaperChunkRetrievalPort.

    Usage:
        session = PaperRAGSession(chunk_store, reranker=reranker)
        result  = session.run(goal, run_id=..., workflow_id=..., step_id=..., session_id=...)
        pack    = result.context_pack   # EvidenceCandidate list for the LLM
    """

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        *,
        budget: RAGBudget | None = None,
        reranker: "RerankerPort | None" = None,
        field_index: FieldEmbeddingSearchPort | None = None,
        field_reranker: "RerankerPort | None" = None,
        visual_store: VisualChunkSearchPort | None = None,
        retrieval_policy: RetrievalPolicy | None = None,
        plan_worker: "ResearchCandidateWorkerPort | None" = None,
        worker_planner_min_round_index: int = 1,
    ) -> None:
        self._chunk_store = chunk_store
        self._policy_builder = ResearchRAGPolicyBuilder()
        self._budget = budget or RAGBudget.safe_default()
        self._reranker = reranker
        self._field_index = field_index
        self._field_reranker = field_reranker
        self._visual_store = visual_store
        self._retrieval_policy = retrieval_policy
        self._plan_worker = plan_worker
        self._worker_planner_min_round_index = max(0, worker_planner_min_round_index)

    def run(
        self,
        goal: ResearchRetrievalGoal,
        *,
        run_id: str,
        workflow_id: str,
        step_id: str,
        session_id: str,
        current_section_index: int = 0,
    ) -> RAGSessionResult:
        # per-run controller + port so reader position stays request-scoped (no shared mutable state)
        retriever = ResearchRetriever(
            self._chunk_store,
            reranker=self._reranker,
            field_index=self._field_index,
            field_reranker=self._field_reranker,
            visual_store=self._visual_store,
            policy=self._retrieval_policy,
        )
        retrieval_port = PaperChunkRetrievalPort(
            retriever, default_section_index=current_section_index
        )
        planner = None
        if self._plan_worker is not None:
            planner = WorkerRAGPlanner(
                ResearchRAGPlanWorker(self._plan_worker),
                min_round_index=self._worker_planner_min_round_index,
            )
        controller = BoundedRAGSessionController(retrieval=retrieval_port, planner=planner)
        spec = self._policy_builder.build_session_spec(
            goal=goal,
            run_id=run_id,
            workflow_id=workflow_id,
            step_id=step_id,
            session_id=session_id,
            budget=self._budget,
        )
        return controller.run(spec)


__all__ = ["PaperRAGSession"]
