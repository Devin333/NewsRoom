from __future__ import annotations

from business.research.application import AskPaperUseCase
from business.research.rag import ResearchRetrievalGoal


def test_ask_paper_use_case_returns_modeled_retrieval_goal() -> None:
    goal = ResearchRetrievalGoal(
        goal_id="goal-ask-paper",
        paper_id="paper-1",
        question="What supports the method claim?",
        required_evidence_types=["method", "claim_support"],
        allowed_source_refs=["paper://paper-1/sec-method"],
        allowed_memory_namespaces=["research:user:user-1"],
    )

    assert AskPaperUseCase().build_retrieval_goal(goal) == goal
