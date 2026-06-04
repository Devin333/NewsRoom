from __future__ import annotations

from framework.harness import (
    FakeMemoryPort,
    FakeRAGPlanner,
    FakeRAGSessionController,
    RAGBudget,
    RAGDecisionType,
    RAGSessionStatus,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepSpec,
    fake_rag_session_spec,
)
from framework.harness.rag.fake import fake_reader_repair_memory, fake_research_evidence_packs
from framework.harness.retrieval.fake import FakeRetrievalPort


def test_bounded_rag_controller_returns_verified_context_pack() -> None:
    result = FakeRAGSessionController().run_fake_session()

    assert result.status == RAGSessionStatus.SUCCEEDED
    assert result.decision.decision_type == RAGDecisionType.RETURN_CONTEXT_PACK
    assert result.context_pack is not None
    assert result.context_pack.accepted_evidence[0].lineage
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
