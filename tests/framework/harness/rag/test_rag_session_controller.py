from __future__ import annotations

from dataclasses import replace

from framework.harness import (
    FakeMemoryPort,
    FakeRAGPlanner,
    FakeRAGSessionController,
    RAGBudget,
    RAGDecisionType,
    RAGSessionStatus,
    SourceVerifier,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    fake_rag_session_spec,
)
from framework.harness.rag.fake import fake_reader_repair_memory, fake_research_evidence_packs
from framework.harness.rag.relevance import RelevanceScorerPort
from framework.harness.rag.session import BoundedRAGSessionController
from framework.harness.retrieval.fake import FakeRetrievalPort


def test_bounded_rag_controller_returns_verified_context_pack() -> None:
    result = FakeRAGSessionController().run_fake_session()

    assert result.status == RAGSessionStatus.SUCCEEDED
    assert result.decision.decision_type == RAGDecisionType.RETURN_CONTEXT_PACK
    assert result.context_pack is not None
    assert result.context_pack.accepted_evidence[0].lineage
    assert "retrieval://fake/1" in result.context_pack.artifact_refs
    assert result.context_pack.metadata["artifact_refs"] == list(result.context_pack.artifact_refs)
    assert result.context_pack.evidence_trace[0]["status"] == "accepted"
    assert result.context_pack.evidence_trace[0]["span_refs"]
    assert result.context_pack.metadata["context_snapshot_ref"]


def test_controller_halts_when_query_budget_is_exhausted() -> None:
    spec = fake_rag_session_spec(
        budget=RAGBudget(
            max_rounds=1,
            max_replans=0,
            max_queries=0,
            max_source_reads=4,
            max_memory_hits=4,
            max_context_items=4,
            max_context_tokens=1024,
            max_worker_calls=4,
        )
    )

    result = FakeRAGSessionController().run_fake_session(spec)

    assert result.status == RAGSessionStatus.HALTED
    assert result.decision.decision_type == RAGDecisionType.HALTED
    assert any(event["event_type"] == "rag_halted" for event in result.transcript.events)


def test_controller_replans_when_required_evidence_is_missing() -> None:
    spec = fake_rag_session_spec(required_evidence_types=("method", "limitation"))
    result = FakeRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()[:1]),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
    ).run_fake_session(spec)

    assert result.status == RAGSessionStatus.INSUFFICIENT_EVIDENCE
    assert any(event["event_type"] == "rag_replanned" for event in result.transcript.events)
    assert result.decision.metadata["gap_report"]["missing_evidence_types"] == ["limitation"]


def test_controller_drops_memory_hits_outside_namespace() -> None:
    memory = FakeMemoryPort(
        (
            {
                "memory_ref": "memory://research.private/1",
                "namespace": "research.private",
                "summary": "This private note must not cross the namespace boundary.",
                "relevance": 0.99,
            },
            *fake_reader_repair_memory(),
        )
    )

    result = FakeRAGSessionController(memory=memory).run_fake_session()

    assert result.status == RAGSessionStatus.SUCCEEDED
    assert result.context_pack is not None
    assert all(item["namespace"] == "research.reader_repair" for item in result.context_pack.memory_context)


def test_controller_plan_failure_uses_replan_then_controlled_halt() -> None:
    bad_plan = RetrievalPlanCandidate(
        candidate_id="bad-plan",
        queries=(
            RetrievalStepSpec(
                step_id="bad-query",
                operation=RetrievalOperation.SEARCH_CORPUS,
                query="reader repair",
                corpus="unauthorized-corpus",
            ),
        ),
    )
    spec = fake_rag_session_spec(
        budget=RAGBudget(
            max_rounds=1,
            max_replans=0,
            max_queries=2,
            max_source_reads=2,
            max_memory_hits=2,
            max_context_items=2,
            max_context_tokens=512,
            max_worker_calls=2,
        )
    )

    result = FakeRAGSessionController(planner=FakeRAGPlanner((bad_plan,))).run_fake_session(spec)

    assert result.status == RAGSessionStatus.HALTED
    assert result.decision.reason == "plan gate failed and no replan budget remains"
    assert any(event["payload"].get("gate") == "rag_tool_allowlist" for event in result.transcript.events if event["event_type"] == "rag_gate_failed")


def test_controller_gap_report_includes_low_relevance_rejection_summary() -> None:
    spec = fake_rag_session_spec(
        budget=RAGBudget(
            max_rounds=1,
            max_replans=0,
            max_queries=2,
            max_source_reads=2,
            max_memory_hits=2,
            max_context_items=2,
            max_context_tokens=512,
            max_worker_calls=4,
        )
    )
    controller = BoundedRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()[:1]),
        planner=FakeRAGPlanner(),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
        source_verifier=SourceVerifier(relevance_scorer=_Scorer((0.1,))),
    )

    result = controller.run(spec)

    assert result.status == RAGSessionStatus.INSUFFICIENT_EVIDENCE
    summary = result.decision.metadata["gap_report"]["rejection_summary"]
    assert summary == {"low_relevance": {"count": 1, "evidence_types": {"method": 1}}}
    source_event = [event for event in result.transcript.events if event["event_type"] == "rag_source_verified"][0]
    assert source_event["payload"]["rejected"][0]["metadata"]["rejection_reason"] == "low_relevance"


def test_controller_propagates_tenant_scope_to_retrieval_request_and_metrics() -> None:
    base = fake_rag_session_spec()
    scope = {
        "tenant_id": "tenant-a",
        "user_id": "user-1",
        "memory_namespace": "research:tenant:tenant-a:user:user-1",
    }
    spec = replace(
        base,
        goal=replace(base.goal, metadata={**base.goal.metadata, **scope}),
        source_policy={**base.source_policy, "tenant_id": "tenant-a"},
        metadata={**base.metadata, **scope},
    )
    retrieval = FakeRetrievalPort(fake_research_evidence_packs()[:1])
    controller = BoundedRAGSessionController(
        retrieval=retrieval,
        planner=FakeRAGPlanner(),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
    )

    result = controller.run(spec)

    assert retrieval.requests[0].filters["tenant_id"] == "tenant-a"
    assert retrieval.requests[0].metadata["tenant_id"] == "tenant-a"
    assert retrieval.requests[0].metadata["user_id"] == "user-1"
    assert retrieval.requests[0].metadata["memory_namespace"] == "research:tenant:tenant-a:user:user-1"
    assert result.metrics is not None
    assert result.metrics.tenant_id == "tenant-a"
    assert result.metrics.user_id == "user-1"
    assert result.metrics.memory_namespace == "research:tenant:tenant-a:user:user-1"


class _Scorer(RelevanceScorerPort):
    def __init__(self, scores: tuple[float, ...]) -> None:
        self.scores = scores

    def score(self, question: str, passages: list[str]) -> list[float]:
        return list(self.scores)
