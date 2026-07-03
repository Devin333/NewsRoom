from __future__ import annotations

from business.research.application import paper_rag_session
from business.research.application.paper_rag_session import PaperRAGSession
from business.research.rag.models import ResearchRetrievalGoal
from framework.harness.rag.source_verifier import SourceVerifier


class _FakeRetriever:
    last_kwargs = {}

    def __init__(self, *args, **kwargs) -> None:
        _FakeRetriever.last_kwargs = kwargs


class _FakeRetrievalPort:
    last_retriever = None
    last_default_section_index = None

    def __init__(self, retriever, *, default_section_index: int = 0) -> None:
        _FakeRetrievalPort.last_retriever = retriever
        _FakeRetrievalPort.last_default_section_index = default_section_index


class _FakeController:
    last_retrieval = None
    last_planner = None
    last_answer_worker = None
    last_source_verifier = None

    def __init__(self, *, retrieval, planner=None, answer_worker=None, source_verifier=None) -> None:
        _FakeController.last_retrieval = retrieval
        _FakeController.last_planner = planner
        _FakeController.last_answer_worker = answer_worker
        _FakeController.last_source_verifier = source_verifier

    def run(self, spec):
        return {"spec": spec}


def test_paper_rag_session_passes_retrieval_policy_to_inner_retriever(monkeypatch):
    policy = object()
    monkeypatch.setattr(paper_rag_session, "ResearchRetriever", _FakeRetriever)
    monkeypatch.setattr(paper_rag_session, "PaperChunkRetrievalPort", _FakeRetrievalPort)
    monkeypatch.setattr(paper_rag_session, "BoundedRAGSessionController", _FakeController)

    session = PaperRAGSession(object(), retrieval_policy=policy)
    result = session.run(
        ResearchRetrievalGoal(
            goal_id="g1",
            paper_id="p1",
            question="What does the figure show?",
            required_evidence_types=["figure"],
            allowed_source_refs=["paper://p1"],
            allowed_memory_namespaces=["research"],
        ),
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="step-1",
        session_id="session-1",
        current_section_index=3,
    )

    assert _FakeRetriever.last_kwargs["policy"] is policy
    assert _FakeRetrievalPort.last_default_section_index == 3
    assert result["spec"].goal.question == "What does the figure show?"
    assert _FakeController.last_planner is None


def test_paper_rag_session_wires_optional_worker_planner(monkeypatch):
    monkeypatch.setattr(paper_rag_session, "ResearchRetriever", _FakeRetriever)
    monkeypatch.setattr(paper_rag_session, "PaperChunkRetrievalPort", _FakeRetrievalPort)
    monkeypatch.setattr(paper_rag_session, "BoundedRAGSessionController", _FakeController)
    worker = object()

    session = PaperRAGSession(object(), plan_worker=worker, worker_planner_min_round_index=2)
    session.run(
        ResearchRetrievalGoal(
            goal_id="g1",
            paper_id="p1",
            question="What does the figure show?",
            required_evidence_types=["figure"],
            allowed_source_refs=["paper://p1"],
            allowed_memory_namespaces=["research"],
        ),
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="step-1",
        session_id="session-1",
    )

    assert _FakeController.last_planner is not None
    assert _FakeController.last_planner.min_round_index == 2
    assert _FakeController.last_planner.worker._worker is worker


def test_paper_rag_session_wires_optional_answer_worker_and_generation_policy(monkeypatch):
    monkeypatch.setattr(paper_rag_session, "ResearchRetriever", _FakeRetriever)
    monkeypatch.setattr(paper_rag_session, "PaperChunkRetrievalPort", _FakeRetrievalPort)
    monkeypatch.setattr(paper_rag_session, "BoundedRAGSessionController", _FakeController)
    answer_worker = object()

    session = PaperRAGSession(
        object(),
        answer_worker=answer_worker,
        generation_policy={"enabled": True},
    )
    result = session.run(
        ResearchRetrievalGoal(
            goal_id="g1",
            paper_id="p1",
            question="What does the figure show?",
            required_evidence_types=["figure"],
            allowed_source_refs=["paper://p1"],
            allowed_memory_namespaces=["research"],
        ),
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="step-1",
        session_id="session-1",
    )

    assert _FakeController.last_answer_worker is answer_worker
    assert result["spec"].generation_policy == {"enabled": True}


def test_paper_rag_session_wires_optional_relevance_scorer_and_policy_thresholds(monkeypatch):
    monkeypatch.setattr(paper_rag_session, "ResearchRetriever", _FakeRetriever)
    monkeypatch.setattr(paper_rag_session, "PaperChunkRetrievalPort", _FakeRetrievalPort)
    monkeypatch.setattr(paper_rag_session, "BoundedRAGSessionController", _FakeController)
    relevance_scorer = object()

    session = PaperRAGSession(object(), relevance_scorer=relevance_scorer)
    result = session.run(
        ResearchRetrievalGoal(
            goal_id="g1",
            paper_id="p1",
            question="What does the figure show?",
            required_evidence_types=["figure"],
            allowed_source_refs=["paper://p1"],
            allowed_memory_namespaces=["research"],
        ),
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="step-1",
        session_id="session-1",
    )

    assert isinstance(_FakeController.last_source_verifier, SourceVerifier)
    assert _FakeController.last_source_verifier.relevance_scorer is relevance_scorer
    assert result["spec"].source_policy["min_relevance"] == 0.3
    assert result["spec"].source_policy["min_relevance_by_type"] == {
        "formula": 0.2,
        "table": 0.2,
    }
