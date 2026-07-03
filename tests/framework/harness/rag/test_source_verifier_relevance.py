from __future__ import annotations

from framework.harness.rag.models import EvidenceCandidate
from framework.harness.rag.policy import RAGExecutionPolicy
from framework.harness.rag.relevance import RelevanceScorerPort
from framework.harness.rag.source_verifier import SourceVerifier
from framework.harness.rag.fake import fake_rag_session_spec


def test_source_verifier_rejects_low_relevance_evidence() -> None:
    policy = RAGExecutionPolicy.from_session_spec(fake_rag_session_spec())
    verifier = SourceVerifier(relevance_scorer=_Scorer((0.2, 0.9)))
    low = _candidate("method", evidence_id="low")
    high = _candidate("method", evidence_id="high")

    result = verifier.verify((low, high), policy=policy, question="How does the method work?")

    assert [item.evidence_id for item in result.accepted] == ["high"]
    assert [item.evidence_id for item in result.rejected] == ["low"]
    assert result.rejected[0].metadata["rejection_reason"] == "low_relevance"
    assert result.rejected[0].metadata["relevance_score"] == 0.2
    assert result.rejected[0].metadata["relevance_threshold"] == 0.3
    relevance_gate = [gate for gate in result.gate_results if gate.gate_name == "rag_relevance"][0]
    assert relevance_gate.passed is False


def test_source_verifier_uses_source_policy_relevance_threshold() -> None:
    spec = fake_rag_session_spec()
    policy = RAGExecutionPolicy.from_session_spec(spec)
    policy = RAGExecutionPolicy(
        allowed_corpora=policy.allowed_corpora,
        allowed_memory_namespaces=policy.allowed_memory_namespaces,
        allowed_tools=policy.allowed_tools,
        budget=policy.budget,
        source_policy={**policy.source_policy, "min_relevance": 0.8},
        context_policy=policy.context_policy,
    )
    verifier = SourceVerifier(relevance_scorer=_Scorer((0.79,)))

    result = verifier.verify((_candidate("method"),), policy=policy, question="How does the method work?")

    assert result.rejected[0].metadata["rejection_reason"] == "low_relevance"
    assert result.rejected[0].metadata["relevance_threshold"] == 0.8


def test_source_verifier_uses_evidence_type_relevance_threshold() -> None:
    spec = fake_rag_session_spec()
    policy = RAGExecutionPolicy.from_session_spec(spec)
    policy = RAGExecutionPolicy(
        allowed_corpora=policy.allowed_corpora,
        allowed_memory_namespaces=policy.allowed_memory_namespaces,
        allowed_tools=policy.allowed_tools,
        budget=policy.budget,
        source_policy={
            **policy.source_policy,
            "min_relevance": 0.8,
            "min_relevance_by_type": {"table": 0.2},
        },
        context_policy=policy.context_policy,
    )
    verifier = SourceVerifier(relevance_scorer=_Scorer((0.3,)))

    result = verifier.verify((_candidate("table"),), policy=policy, question="Which table supports it?")

    assert result.accepted[0].evidence_type == "table"
    assert result.rejected == ()
    relevance_gate = [gate for gate in result.gate_results if gate.gate_name == "rag_relevance"][0]
    assert relevance_gate.passed is True
    assert relevance_gate.details["thresholds_by_evidence_type"] == {"table": 0.2}


def test_source_verifier_uses_chunk_type_relevance_threshold() -> None:
    spec = fake_rag_session_spec()
    policy = RAGExecutionPolicy.from_session_spec(spec)
    policy = RAGExecutionPolicy(
        allowed_corpora=policy.allowed_corpora,
        allowed_memory_namespaces=policy.allowed_memory_namespaces,
        allowed_tools=policy.allowed_tools,
        budget=policy.budget,
        source_policy={
            **policy.source_policy,
            "min_relevance": 0.8,
            "min_relevance_by_type": {"table": 0.2},
        },
        context_policy=policy.context_policy,
    )
    verifier = SourceVerifier(relevance_scorer=_Scorer((0.3,)))

    result = verifier.verify(
        (_candidate("experiment", metadata={"chunk_type": "table"}),),
        policy=policy,
        question="Which table supports it?",
    )

    assert result.accepted[0].metadata["chunk_type"] == "table"
    relevance_gate = [gate for gate in result.gate_results if gate.gate_name == "rag_relevance"][0]
    assert relevance_gate.passed is True


def test_source_verifier_without_scorer_preserves_existing_acceptance() -> None:
    policy = RAGExecutionPolicy.from_session_spec(fake_rag_session_spec())
    verifier = SourceVerifier()
    candidate = _candidate("method")

    result = verifier.verify((candidate,), policy=policy, question="unrelated question")

    assert result.accepted == (candidate,)
    assert result.rejected == ()
    assert [gate.gate_name for gate in result.gate_results] == ["rag_source_quality", "rag_lineage"]


def test_source_verifier_without_question_skips_relevance_scoring() -> None:
    policy = RAGExecutionPolicy.from_session_spec(fake_rag_session_spec())
    scorer = _Scorer((0.1,))
    verifier = SourceVerifier(relevance_scorer=scorer)
    candidate = _candidate("method")

    result = verifier.verify((candidate,), policy=policy)

    assert result.accepted == (candidate,)
    assert result.rejected == ()
    assert scorer.calls == []


def test_source_verifier_rejects_when_scorer_returns_wrong_score_count() -> None:
    policy = RAGExecutionPolicy.from_session_spec(fake_rag_session_spec())
    verifier = SourceVerifier(relevance_scorer=_Scorer((0.9,)))

    result = verifier.verify(
        (_candidate("method", evidence_id="ev-1"), _candidate("method", evidence_id="ev-2")),
        policy=policy,
        question="How does the method work?",
    )

    assert [item.metadata["rejection_reason"] for item in result.rejected] == [
        "relevance_score_unavailable",
        "relevance_score_unavailable",
    ]
    relevance_gate = [gate for gate in result.gate_results if gate.gate_name == "rag_relevance"][0]
    assert relevance_gate.passed is False
    assert relevance_gate.details["score_count_mismatch"] is True


class _Scorer(RelevanceScorerPort):
    def __init__(self, scores: tuple[float, ...]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, question: str, passages: list[str]) -> list[float]:
        self.calls.append((question, passages))
        return list(self.scores)


def _candidate(
    evidence_type: str,
    *,
    evidence_id: str = "ev-1",
    metadata: dict | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        title=evidence_id,
        summary=f"{evidence_type} summary",
        source_ref=f"source://{evidence_id}",
        span_refs=(f"source://{evidence_id}#span",),
        evidence_type=evidence_type,
        confidence=0.9,
        lineage=("retrieval.fake",),
        metadata=dict(metadata or {}),
    )
