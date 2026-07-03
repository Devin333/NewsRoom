from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from framework.harness import FakeRAGSessionController, RAGSessionStatus, fake_rag_session_spec
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.rag.answer_worker import AnswerWorkerPort
from framework.harness.rag.context_pack_assembler import FakeRAGContextPackAssembler
from framework.harness.rag.fake import FakeRAGGateSuite, FakeRAGPlanner, fake_reader_repair_memory, fake_research_evidence_packs
from framework.harness.rag.models import AnswerClaim, GroundedAnswerCandidate, RAGTranscript
from framework.harness.rag.replay import replay_rag_session
from framework.harness.rag.session import BoundedRAGSessionController
from framework.harness.rag.source_verifier import FakeSourceVerifier
from framework.harness.context.fake import FakeContextAssembler
from framework.harness.memory.fake import FakeMemoryPort
from framework.harness.retrieval.fake import FakeRetrievalPort
from framework.shared.json import stable_json_dumps, to_jsonable


def test_rag_session_replay_reconstructs_context_pack_transcript() -> None:
    result = FakeRAGSessionController().run_fake_session()
    assert result.context_pack is not None
    context_pack = result.context_pack.to_dict()
    refs = _refs_from_pack(context_pack)
    snapshots = {ref: {"payload": {"ref": ref}, "checksum": _checksum({"ref": ref})} for ref in refs}

    replay = replay_rag_session(result.transcript.to_dict(), snapshots=snapshots)

    assert replay.status == RAGSessionStatus.SUCCEEDED
    assert replay.replayable is True
    assert replay.context_pack is not None
    assert replay.context_pack["pack_id"] == result.context_pack.pack_id
    assert "rag_context_pack_returned" in replay.phase_sequence
    gate_names = {item["gate"] for item in replay.gate_results}
    assert {"rag_plan_schema", "rag_source_quality", "rag_context_size"}.issubset(gate_names)
    assert replay.decisions[-1]["event_type"] == "rag_context_pack_returned"
    assert all(check.passed for check in replay.replay_checks)


def test_rag_session_replay_includes_answer_candidate_and_answer_gates() -> None:
    spec = replace(fake_rag_session_spec(), generation_policy={"enabled": True})
    context_assembler = FakeContextAssembler()
    controller = BoundedRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
        planner=FakeRAGPlanner(),
        source_verifier=FakeSourceVerifier(),
        context_pack_assembler=FakeRAGContextPackAssembler(context_assembler),
        answer_worker=_AnswerWorker(),
        gates=FakeRAGGateSuite(),
    )
    result = controller.run(spec)

    replay = replay_rag_session(result.transcript)

    assert replay.status == RAGSessionStatus.ANSWERED
    assert replay.answer is not None
    assert replay.answer["answer_id"] == "answer-1"
    assert any(item["event_type"] == "rag_answer_verified" for item in replay.gate_results)
    assert replay.decisions[-1]["event_type"] == "rag_answer_returned"


def test_rag_session_replay_rejects_empty_transcript() -> None:
    transcript = RAGTranscript(
        transcript_id="transcript-empty",
        session_id="session-empty",
        events=(),
        status=RAGSessionStatus.FAILED,
    )

    with pytest.raises(HarnessValidationError, match="requires transcript events"):
        replay_rag_session(transcript)


def test_rag_session_replay_marks_snapshot_checksum_mismatch_not_replayable() -> None:
    result = FakeRAGSessionController().run_fake_session()
    assert result.context_pack is not None
    context_pack = result.context_pack.to_dict()
    refs = _refs_from_pack(context_pack)
    snapshots = {ref: {"payload": {"ref": ref}, "checksum": "sha256:bad"} for ref in refs}

    replay = replay_rag_session(result.transcript, snapshots=snapshots)

    assert replay.replayable is False
    assert any("checksum mismatch" in error for error in replay.errors)
    assert any(check.name == "snapshot_checksum" and not check.passed for check in replay.replay_checks)


class _AnswerWorker(AnswerWorkerPort):
    def generate_answer(self, *, question, pack):
        return GroundedAnswerCandidate(
            answer_id="answer-1",
            question=question,
            answer_text="The paper uses source-backed method evidence.",
            cited_evidence_ids=(pack.accepted_evidence[0].evidence_id,),
            claims=(
                AnswerClaim(
                    claim_id="claim-1",
                    text="The paper uses source-backed method evidence.",
                    evidence_ids=(pack.accepted_evidence[0].evidence_id,),
                    span_refs=(pack.accepted_evidence[0].span_refs[0],),
                ),
            ),
        )


def _refs_from_pack(pack: dict) -> set[str]:
    refs = set(pack.get("artifact_refs") or [])
    refs.update(pack.get("context_refs") or [])
    refs.update(pack.get("source_refs") or [])
    metadata = pack.get("metadata") or {}
    if metadata.get("context_snapshot_ref"):
        refs.add(metadata["context_snapshot_ref"])
    for evidence in pack.get("accepted_evidence") or []:
        refs.update(evidence.get("artifact_refs") or [])
    return {str(ref) for ref in refs if str(ref).strip()}


def _checksum(payload) -> str:
    return f"sha256:{sha256(stable_json_dumps(to_jsonable(payload)).encode('utf-8')).hexdigest()}"
