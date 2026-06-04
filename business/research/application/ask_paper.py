from __future__ import annotations

from business.research.rag.models import ResearchRetrievalGoal


class AskPaperUseCase:
    def build_retrieval_goal(self, goal: ResearchRetrievalGoal) -> ResearchRetrievalGoal:
        return goal


__all__ = ["AskPaperUseCase"]
