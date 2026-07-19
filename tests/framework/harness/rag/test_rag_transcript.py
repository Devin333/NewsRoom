from __future__ import annotations

from framework.harness import FakeRAGSessionController, RAGBudget, RAGSessionStatus, fake_rag_session_spec


def test_successful_rag_transcript_records_plan_execute_verify_and_return() -> None:
    result = FakeRAGSessionController().run_fake_session()

    event_types = [event["event_type"] for event in result.transcript.events]

    assert result.transcript.status == RAGSessionStatus.SUCCEEDED
    assert result.transcript.ref == result.transcript.transcript_id
    assert result.transcript.ref.count("rag-transcript://") == 1
    assert "rag_session_started" in event_types
    assert "rag_plan_candidate_created" in event_types
    assert "rag_plan_verified" in event_types
    assert "rag_step_executed" in event_types
    assert "rag_source_verified" in event_types
    assert "rag_context_pack_assembled" in event_types
    assert "rag_context_pack_returned" in event_types


def test_halted_rag_transcript_records_exhausted_budget() -> None:
    spec = fake_rag_session_spec(
        budget=RAGBudget(
            max_rounds=1,
            max_replans=0,
            max_queries=0,
            max_source_reads=0,
            max_memory_hits=0,
            max_context_items=1,
            max_context_tokens=64,
            max_worker_calls=0,
        )
    )

    result = FakeRAGSessionController().run_fake_session(spec)

    assert result.transcript.status == RAGSessionStatus.HALTED
    halted = [event for event in result.transcript.events if event["event_type"] == "rag_halted"]
    assert halted
    assert halted[-1]["payload"]["budget_snapshot"]["queries_used"] == 0
