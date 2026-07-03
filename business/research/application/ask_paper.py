from __future__ import annotations

from business.research.rag.retrieval.paper_policy import classify_query_intent
from business.research.rag.models import ResearchRetrievalGoal


class AskPaperUseCase:
    def build_retrieval_goal(self, goal: ResearchRetrievalGoal) -> ResearchRetrievalGoal:
        return goal

    def build_paper_ask_goal(
        self,
        *,
        paper_id: str,
        question: str,
        goal_id: str = "paper-rag-ask",
        memory_namespace: str = "research.public",
    ) -> ResearchRetrievalGoal:
        intent = classify_query_intent(question)
        return ResearchRetrievalGoal(
            goal_id=goal_id,
            paper_id=paper_id,
            question=question,
            required_evidence_types=_required_evidence_types(intent),
            allowed_source_refs=[f"arxiv://{paper_id}", paper_id],
            allowed_memory_namespaces=[memory_namespace],
            metadata={"intent": intent},
        )


def _required_evidence_types(intent: str) -> list[str]:
    if intent in {"table_query", "numerical_result"}:
        return ["experiment"]
    if intent == "figure_query":
        return ["experiment"]
    if intent == "formula_query":
        return ["method"]
    if intent in {"citation_query", "contribution", "comparison"}:
        return ["claim_support"]
    return ["method"]


__all__ = ["AskPaperUseCase"]
