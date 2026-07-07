from __future__ import annotations

from framework.harness.rag.models import RAGSessionStatus, RAGTranscript
from interfaces.services.paper_rag_transcript_store import PaperRagTranscriptFileStore, SCHEMA_VERSION


def test_transcript_store_persists_and_loads_by_id_and_path(tmp_path) -> None:
    store = PaperRagTranscriptFileStore(tmp_path)
    transcript = _transcript()

    artifact = store.persist(transcript)

    assert artifact.path.exists()
    assert artifact.transcript_id == "transcript-1"
    assert artifact.to_dict()["schema_version"] == SCHEMA_VERSION
    assert store.path_for("transcript-1") == artifact.path
    assert store.load("transcript-1")["transcript"]["transcript_id"] == "transcript-1"
    assert store.load(artifact.path)["transcript"]["session_id"] == "session-1"
    assert store.transcript_payload("transcript-1")["status"] == "answered"


def test_transcript_store_loads_uri_transcript_ids_by_hash(tmp_path) -> None:
    store = PaperRagTranscriptFileStore(tmp_path)
    transcript_id = "rag-transcript://paper-rag-ask-session-abc/12345678"
    store.persist(_transcript(transcript_id=transcript_id))

    assert store.transcript_payload(transcript_id)["transcript_id"] == transcript_id


def _transcript(transcript_id: str = "transcript-1") -> RAGTranscript:
    return RAGTranscript(
        transcript_id=transcript_id,
        session_id="session-1",
        events=(
            {
                "event_type": "rag_answer_returned",
                "payload": {"decision_type": "return_answer"},
            },
        ),
        status=RAGSessionStatus.ANSWERED,
    )
