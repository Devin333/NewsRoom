from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from framework.harness.rag.models import (
    AnswerClaim,
    EvidenceCandidate,
    GroundedAnswerCandidate,
    RAGContextPack,
    RAGSessionStatus,
    RAGTranscript,
)
from framework.harness.rag.metrics import RAGSessionMetrics
from framework.harness.rag.policy import RAGDecision, RAGDecisionType
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair
from interfaces.services.paper_rag_service import PaperRagApplicationService
from interfaces.services.paper_rag_transcript_store import PaperRagTranscriptArtifact, PaperRagTranscriptFileStore


@dataclass
class _Chunk:
    chunk_id: str = "chunk-1"
    section_title: str = "Method"
    chunk_type: str = "paragraph"
    content: str = "The method retrieves evidence."
    metadata: dict = field(default_factory=dict)


@dataclass
class _RetrievalResult:
    child_chunks: list[_Chunk]
    intent: str = "concept_method"
    metadata: dict | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {"retrieved": len(self.child_chunks)}


class _Retriever:
    def __init__(self, chunks: list[_Chunk] | None = None) -> None:
        self.calls = []
        self.chunks = chunks or [_Chunk()]
        self.metadata = None

    def retrieve(self, request):
        self.calls.append(request)
        return _RetrievalResult(self.chunks, metadata=self.metadata)


class _Session:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def run(self, goal, **kwargs):
        self.calls.append((goal, kwargs))
        return self.result


class _RecordingTranscriptStore:
    def __init__(self) -> None:
        self.transcripts = []

    def persist(self, transcript):
        self.transcripts.append(transcript)
        return PaperRagTranscriptArtifact(
            transcript_id=transcript.transcript_id,
            path=Path("transcripts/transcript-1.json"),
        )


class _FailingTranscriptStore:
    def persist(self, transcript):
        raise AssertionError("retrieve-only requests must not persist transcripts")


class _BrokenTranscriptStore:
    def persist(self, transcript):
        raise OSError("transcript volume is read-only")


def test_rag_ask_retrieve_only_keeps_legacy_payload_and_does_not_build_session() -> None:
    retriever = _Retriever()
    service = PaperRagApplicationService(
        retriever=retriever,
        session_factory=lambda **_: (_ for _ in ()).throw(AssertionError("session should not be built")),
        transcript_store=_FailingTranscriptStore(),
    )

    payload = service.rag_ask("p1", "How does it work?", generate=False)

    assert payload["paper_id"] == "p1"
    assert payload["intent"] == "concept_method"
    assert payload["passages"][0]["chunk_id"] == "chunk-1"
    assert "status" not in payload
    assert retriever.calls[0].paper_id == "p1"


def test_rag_ask_retrieve_only_filters_cross_tenant_passages() -> None:
    retriever = _Retriever([
        _Chunk(chunk_id="public"),
        _Chunk(chunk_id="tenant-b", metadata={"tenant_id": "tenant-b"}),
    ])
    service = PaperRagApplicationService(
        retriever=retriever,
        session_factory=lambda **_: (_ for _ in ()).throw(AssertionError("session should not be built")),
    )

    payload = service.rag_ask("p1", "How does it work?", tenant_id="tenant-a")

    assert [item["chunk_id"] for item in payload["passages"]] == ["public"]
    assert retriever.calls[0].filters == {"tenant_id": "tenant-a"}
    assert payload["metrics"]["tenant_id"] == "tenant-a"
    assert payload["metrics"]["tenant_filtered_passage_count"] == 1


def test_rag_ask_retrieve_only_sanitizes_scope_metrics() -> None:
    retriever = _Retriever()
    retriever.metadata = {
        "retrieved": 1,
        "user_id": "user-1",
        "memory_namespace": "research:tenant:tenant-a:user:user-1",
        "nested": {
            "allowed_memory_namespaces": ["research:tenant:tenant-a:user:user-1"],
            "owner_user_id": "user-1",
            "safe_count": 2,
        },
    }
    service = PaperRagApplicationService(
        retriever=retriever,
        session_factory=lambda **_: (_ for _ in ()).throw(AssertionError("session should not be built")),
    )

    payload = service.rag_ask(
        "p1",
        "How does it work?",
        generate=False,
        tenant_id="tenant-a",
        user_id="user-1",
        memory_namespace="research:tenant:tenant-a:user:user-1",
    )

    assert payload["metrics"]["tenant_id"] == "tenant-a"
    assert payload["metrics"]["nested"] == {"safe_count": 2}
    _assert_public_metrics_scope_sanitized(payload["metrics"])


def test_rag_ask_gated_generation_returns_answered_payload(tmp_path) -> None:
    result = _session_result(
        status=RAGSessionStatus.ANSWERED,
        decision_type=RAGDecisionType.RETURN_ANSWER,
        answer=_answer(abstained=False),
    )
    session = _Session(result)
    transcript_store = PaperRagTranscriptFileStore(tmp_path)
    service = PaperRagApplicationService(
        retriever=_Retriever(),
        session_factory=lambda **kwargs: session,
        transcript_store=transcript_store,
    )

    payload = service.rag_ask("p1", "How does it work?", generate=True)

    assert payload["status"] == "answered"
    assert payload["generation_mode"] == "gated_harness"
    assert payload["answer"] == "The method retrieves evidence."
    assert payload["claims"][0]["evidence_ids"] == ["ev-1"]
    assert payload["claims"][0]["span_refs"] == ["paper://p1/pdf#page=1"]
    assert payload["citations"][0]["evidence_id"] == "ev-1"
    assert payload["citations"][0]["span_refs"] == ["paper://p1/pdf#page=1"]
    assert payload["context_pack"]["accepted_evidence_ids"] == ["ev-1"]
    assert payload["transcript_id"] == "transcript-1"
    assert payload["metrics"]["status"] == "answered"
    assert payload["metrics"]["decision_type"] == "return_answer"
    assert payload["metrics"]["context_pack_id"] == "pack-1"
    assert payload["metrics"]["accepted_evidence_count"] == 1
    assert payload["metrics"]["transcript_event_count"] == 3
    assert payload["metrics"]["answer_attempts"] == 1
    assert "trace_id" not in payload["metrics"]
    assert "root_span_id" not in payload["metrics"]
    assert payload["metrics"]["budget_snapshot"]["rounds_used"] == 1
    assert payload["transcript_artifact"]["transcript_id"] == "transcript-1"
    assert transcript_store.resolve("transcript-1").exists()
    assert transcript_store.transcript_payload("transcript-1")["transcript_id"] == "transcript-1"
    assert session.calls[0][0].required_evidence_types == ["method"]
    assert session.calls[0][1]["current_section_index"] == 0


def test_rag_ask_gated_generation_returns_answer_when_transcript_persist_fails() -> None:
    result = _session_result(
        status=RAGSessionStatus.ANSWERED,
        decision_type=RAGDecisionType.RETURN_ANSWER,
        answer=_answer(abstained=False),
    )
    service = PaperRagApplicationService(
        retriever=_Retriever(),
        session_factory=lambda **kwargs: _Session(result),
        transcript_store=_BrokenTranscriptStore(),
    )

    payload = service.rag_ask("p1", "How does it work?", generate=True)

    assert payload["status"] == "answered"
    assert payload["answer"] == "The method retrieves evidence."
    assert payload["transcript_id"] == "transcript-1"
    assert payload["transcript_artifact"]["transcript_id"] == "transcript-1"
    assert payload["transcript_artifact"]["persisted"] is False
    assert payload["transcript_artifact"]["error"] == {
        "type": "OSError",
        "message": "transcript volume is read-only",
    }


def test_rag_ask_gated_generation_returns_abstained_payload_without_answer_text() -> None:
    result = _session_result(
        status=RAGSessionStatus.ABSTAINED,
        decision_type=RAGDecisionType.ABSTAIN,
        answer=_answer(abstained=True),
    )
    service = PaperRagApplicationService(
        retriever=_Retriever(),
        session_factory=lambda **kwargs: _Session(result),
        transcript_store=_RecordingTranscriptStore(),
    )

    payload = service.rag_ask("p1", "How does it work?", generate=True)

    assert payload["status"] == "abstained"
    assert payload["answer"] is None
    assert payload["answer_candidate"]["abstained"] is True
    assert payload["decision"]["decision_type"] == "abstain"
    assert payload["metrics"]["status"] == "abstained"
    assert payload["metrics"]["answer_abstained"] is True


def test_rag_ask_gated_generation_carries_tenant_scope() -> None:
    namespace = "research:tenant:tenant-a:user:user-1"
    result = _session_result(
        status=RAGSessionStatus.ANSWERED,
        decision_type=RAGDecisionType.RETURN_ANSWER,
        answer=_answer(abstained=False),
        tenant_id="tenant-a",
        user_id="user-1",
        memory_namespace=namespace,
    )
    session = _Session(result)
    service = PaperRagApplicationService(
        retriever=_Retriever(),
        session_factory=lambda **kwargs: session,
        transcript_store=_RecordingTranscriptStore(),
    )

    payload = service.rag_ask(
        "p1",
        "How does it work?",
        generate=True,
        tenant_id="tenant-a",
        user_id="user-1",
    )

    goal = session.calls[0][0]
    assert goal.allowed_memory_namespaces == [namespace]
    assert goal.metadata["tenant_id"] == "tenant-a"
    assert goal.metadata["user_id"] == "user-1"
    assert result.metrics is not None
    assert "user_id" not in result.metrics.to_dict()
    assert "memory_namespace" not in result.metrics.to_dict()
    assert "tenant_id" not in payload["metrics"]
    assert "user_id" not in payload["metrics"]
    assert "memory_namespace" not in payload["metrics"]
    _assert_public_metrics_scope_sanitized(payload["metrics"])


def test_rag_ask_gated_generation_respects_expected_abstention_golden_case() -> None:
    pair = EvidenceQAPair.negative(
        question="Does this paper report a GPT-5 training run?",
        paper_id="p1",
    )
    result = _session_result(
        status=RAGSessionStatus.ABSTAINED,
        decision_type=RAGDecisionType.ABSTAIN,
        answer=_answer(abstained=True),
    )
    service = PaperRagApplicationService(
        retriever=_Retriever(),
        session_factory=lambda **kwargs: _Session(result),
        transcript_store=_RecordingTranscriptStore(),
    )

    payload = service.rag_ask(pair.paper_id, pair.question, generate=True)

    assert pair.expected_behavior == "abstain"
    assert payload["status"] == "abstained"
    assert payload["answer"] is None
    assert payload["claims"] == []
    assert payload["citations"] == []
    assert payload["answer_candidate"]["abstained"] is True


def test_rag_ask_legacy_direct_generation_fails_closed() -> None:
    retriever = _Retriever()
    service = PaperRagApplicationService(
        retriever=retriever,
        session_factory=lambda **_: (_ for _ in ()).throw(AssertionError("session should not be built")),
    )

    with pytest.raises(ValueError, match="legacy direct paper RAG answer generation has been removed"):
        service.rag_ask("p1", "How does it work?", generate=True, gated=False)

    assert retriever.calls == []


def _session_result(
    *,
    status: RAGSessionStatus,
    decision_type: RAGDecisionType,
    answer: GroundedAnswerCandidate,
    tenant_id: str | None = None,
    user_id: str | None = None,
    memory_namespace: str | None = None,
):
    from framework.harness.rag.session import RAGSessionResult

    decision = RAGDecision(
        decision_type,
        "done",
        gate_results=({"gate": "rag_answer_shape", "passed": True},),
    )
    return RAGSessionResult(
        status=status,
        context_pack=_pack(),
        transcript=RAGTranscript(
            transcript_id="transcript-1",
            session_id="session-1",
            events=(),
            status=status,
        ),
        decision=decision,
        answer=answer,
        metrics=RAGSessionMetrics(
            status=status,
            decision_type=decision_type.value,
            transcript_event_count=3,
            budget_snapshot={
                "rounds_used": 1,
                "replans_used": 0,
                "queries_used": 1,
                "source_reads_used": 0,
                "memory_hits_used": 0,
                "context_items_used": 0,
                "context_tokens_used": 0,
                "worker_calls_used": 1,
            },
            accepted_evidence_count=1,
            answer_present=True,
            answer_abstained=answer.abstained,
            answer_attempts=1,
        ),
    )


def _assert_public_metrics_scope_sanitized(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            assert normalized != "user_id"
            assert "memory_namespace" not in normalized
            assert "namespace" not in normalized
            assert "user_id" not in normalized
            _assert_public_metrics_scope_sanitized(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_public_metrics_scope_sanitized(item)
        return
    if isinstance(value, str):
        assert "research:tenant:" not in value
        assert "user-1" not in value


def _answer(*, abstained: bool) -> GroundedAnswerCandidate:
    return GroundedAnswerCandidate(
        answer_id="answer-1",
        question="How does it work?",
        answer_text="" if abstained else "The method retrieves evidence.",
        cited_evidence_ids=() if abstained else ("ev-1",),
        claims=()
        if abstained
        else (
            AnswerClaim(
                "claim-1",
                "The method retrieves evidence.",
                ("ev-1",),
                span_refs=("paper://p1/pdf#page=1",),
            ),
        ),
        abstained=abstained,
    )


def _pack() -> RAGContextPack:
    evidence = EvidenceCandidate(
        evidence_id="ev-1",
        title="Method",
        summary="The method retrieves evidence.",
        source_ref="paper://p1/pdf#page=1",
        span_refs=("paper://p1/pdf#page=1",),
        evidence_type="method",
        confidence=0.9,
        lineage=("p1",),
        metadata={
            "rag_chunk_id": "chunk-1",
            "chunk_type": "paragraph",
            "section_title": "Method",
            "source_locator": "paper://p1/pdf#page=1",
        },
    )
    return RAGContextPack(
        pack_id="pack-1",
        query="How does it work?",
        accepted_evidence=(evidence,),
        gap_report={"missing_evidence_types": []},
        assembly_summary="assembled",
    )
