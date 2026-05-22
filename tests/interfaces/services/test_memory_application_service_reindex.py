from business.layers.memory.ingestion import MemoryIngestionResult
from interfaces.services.memory_service import MemoryReindexResult


def test_memory_reindex_result_exposes_structured_counts_and_metadata() -> None:
    result = MemoryReindexResult(
        run_id="run-1",
        topic="AI",
        ingestion=MemoryIngestionResult(
            run_id="run-1",
            topic="AI",
            counts={
                "evidence": 1,
                "claims": 2,
                "entities": 1,
                "events": 1,
                "decisions": 1,
                "preferences": 0,
            },
            indexed_documents=6,
            collections=["evidence_items", "claims", "entities", "events", "decisions"],
            document_ids=["ev-1", "claim-1", "entity-1", "event-1", "decision-1"],
            metadata={
                "claim_consolidation": {"inserted": 1, "merged": 1},
                "entity_resolution": {"entities": 1},
                "event_build": {"events": 1},
            },
        ),
    )

    payload = result.to_dict()

    assert payload["counts"]["claims"] == 2
    assert payload["metadata"]["claim_consolidation"]["merged"] == 1
    assert payload["ingestion"]["indexed_documents"] == 6
    assert payload["documents_indexed"] == 6
    assert payload["collections"] == ["evidence_items", "claims", "entities", "events", "decisions"]
