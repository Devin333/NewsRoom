from __future__ import annotations

from framework.harness.rag.session import BoundedRAGSessionController, RAGSessionResult
from framework.harness.rag.models import RAGBudget

from business.research.rag.models import ResearchRetrievalGoal
from business.research.rag.retrieval_port import PaperChunkRetrievalPort
from business.research.rag.retriever import ResearchRetriever
from business.research.services.rag_policy import ResearchRAGPolicyBuilder
from business.research.ports.chunk_store import ChunkStorePort


class PaperRAGSession:
    """
    Wires ResearchRetriever into BoundedRAGSessionController via PaperChunkRetrievalPort.

    Usage:
        session = PaperRAGSession(chunk_store)
        result  = session.run(goal, run_id=..., workflow_id=..., step_id=..., session_id=...)
        pack    = result.context_pack   # EvidenceCandidate list for the LLM
    """

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        *,
        budget: RAGBudget | None = None,
    ) -> None:
        self._chunk_store = chunk_store
        self._policy_builder = ResearchRAGPolicyBuilder()
        self._budget = budget or RAGBudget.safe_default()

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
        retriever = ResearchRetriever(self._chunk_store)
        retrieval_port = PaperChunkRetrievalPort(
            retriever, default_section_index=current_section_index
        )
        controller = BoundedRAGSessionController(retrieval=retrieval_port)
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
