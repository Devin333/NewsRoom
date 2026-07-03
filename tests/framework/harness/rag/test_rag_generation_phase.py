from __future__ import annotations

from framework.harness import FakeMemoryPort, RAGDecisionType, RAGSessionStatus, fake_rag_session_spec
from framework.harness.rag.fake import FakeRAGPlanner, fake_reader_repair_memory, fake_research_evidence_packs
from framework.harness.rag.models import AnswerClaim, GroundedAnswerCandidate, RAGContextPack
from framework.harness.rag.session import BoundedRAGSessionController
from framework.harness.retrieval.fake import FakeRetrievalPort


def test_generation_phase_is_disabled_by_default() -> None:
    worker = _AnswerWorker(_grounded_answer())
    controller = _controller(worker)

    result = controller.run(fake_rag_session_spec())

    assert result.status == RAGSessionStatus.SUCCEEDED
    assert result.decision.decision_type == RAGDecisionType.RETURN_CONTEXT_PACK
    assert result.answer is None
    assert worker.calls == []


def test_generation_phase_returns_answered_when_answer_gate_passes() -> None:
    worker = _AnswerWorker(_grounded_answer())
    controller = _controller(worker)

    result = controller.run(_generation_spec())

    assert result.status == RAGSessionStatus.ANSWERED
    assert result.decision.decision_type == RAGDecisionType.RETURN_ANSWER
    assert result.answer is not None
    assert result.answer.answer_text == "The method retrieves evidence. [ev-1]"
    assert any(event["event_type"] == "rag_answer_returned" for event in result.transcript.events)


def test_generation_phase_abstains_when_answer_gate_fails() -> None:
    candidate = GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="Unsupported answer.",
        cited_evidence_ids=("missing",),
        claims=(AnswerClaim("c1", "Unsupported answer.", ("missing",)),),
    )
    result = _controller(_AnswerWorker(candidate)).run(_generation_spec())

    assert result.status == RAGSessionStatus.ABSTAINED
    assert result.decision.decision_type == RAGDecisionType.ABSTAIN
    assert result.decision.reason == "answer gate failed"
    assert any(item["gate"] == "rag_answer_citation_integrity" for item in result.decision.gate_results)


def test_generation_phase_returns_verified_abstention() -> None:
    candidate = GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="",
        cited_evidence_ids=(),
        claims=(),
        abstained=True,
    )
    result = _controller(_AnswerWorker(candidate)).run(_generation_spec())

    assert result.status == RAGSessionStatus.ABSTAINED
    assert result.decision.reason == "answer worker produced a verified abstention"
    assert result.answer is not None
    assert result.answer.abstained is True


def _controller(worker: _AnswerWorker) -> BoundedRAGSessionController:
    return BoundedRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()[:1]),
        planner=FakeRAGPlanner(),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
        answer_worker=worker,
    )


def _generation_spec():
    spec = fake_rag_session_spec()
    return type(spec)(
        session_id=spec.session_id,
        run_id=spec.run_id,
        workflow_id=spec.workflow_id,
        step_id=spec.step_id,
        goal=spec.goal,
        allowed_corpora=spec.allowed_corpora,
        allowed_memory_namespaces=spec.allowed_memory_namespaces,
        allowed_tools=spec.allowed_tools,
        source_policy=spec.source_policy,
        budget=spec.budget,
        context_policy=spec.context_policy,
        generation_policy={"enabled": True},
        metadata=spec.metadata,
    )


def _grounded_answer() -> GroundedAnswerCandidate:
    return GroundedAnswerCandidate(
        answer_id="ans-1",
        question="Q?",
        answer_text="The method retrieves evidence. [ev-1]",
        cited_evidence_ids=("evidence:sparse-mixture-reader:method",),
        claims=(
            AnswerClaim(
                "c1",
                "The method retrieves evidence.",
                ("evidence:sparse-mixture-reader:method",),
            ),
        ),
    )


class _AnswerWorker:
    def __init__(self, candidate: GroundedAnswerCandidate) -> None:
        self.candidate = candidate
        self.calls: list[tuple[str, str]] = []

    def generate_answer(self, *, question: str, pack: RAGContextPack) -> GroundedAnswerCandidate:
        self.calls.append((question, pack.pack_id))
        return self.candidate
