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


def test_ask_paper_use_case_builds_method_goal_from_question() -> None:
    goal = AskPaperUseCase().build_paper_ask_goal(
        paper_id="1706.03762",
        question="How does the model architecture work?",
        goal_id="goal-1",
    )

    assert goal.goal_id == "goal-1"
    assert goal.paper_id == "1706.03762"
    assert goal.required_evidence_types == ["method"]
    assert goal.allowed_source_refs == ["arxiv://1706.03762", "1706.03762"]
    assert goal.allowed_memory_namespaces == ["research.public"]
    assert goal.metadata["intent"] == "concept_method"


def test_ask_paper_use_case_maps_table_questions_to_experiment_evidence() -> None:
    goal = AskPaperUseCase().build_paper_ask_goal(
        paper_id="p1",
        question="What do the experiment results in Table 2 show?",
    )

    assert goal.required_evidence_types == ["experiment"]
    assert goal.metadata["intent"] == "table_query"


def test_ask_paper_use_case_maps_formula_questions_to_method_evidence() -> None:
    goal = AskPaperUseCase().build_paper_ask_goal(
        paper_id="p1",
        question="What does Equation 3 define?",
    )

    assert goal.required_evidence_types == ["method"]
    assert goal.metadata["intent"] == "formula_query"
