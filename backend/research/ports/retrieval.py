from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.rag.models import ResearchRAGContext, ResearchRetrievalGoal


@runtime_checkable
class ResearchRetrievalProjectionPort(Protocol):
    def project_context(self, goal: ResearchRetrievalGoal) -> ResearchRAGContext:
        ...


__all__ = ["ResearchRetrievalProjectionPort"]
