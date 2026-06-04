from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.models import RAGSessionSpec

from business.research.rag.models import ResearchRetrievalGoal


@runtime_checkable
class ResearchRAGPolicyPort(Protocol):
    def build_session_spec(
        self,
        *,
        goal: ResearchRetrievalGoal,
        run_id: str,
        workflow_id: str,
        step_id: str,
        session_id: str,
    ) -> RAGSessionSpec:
        ...


__all__ = ["ResearchRAGPolicyPort"]
