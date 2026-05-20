from datetime import UTC, datetime

from infrastructure.storage.vector import VectorDocument, VectorSearchResult


def test_vector_document_payload_includes_lineage_fields() -> None:
    doc = VectorDocument(
        document_id="doc-1",
        collection="evidence_items",
        text="Agent runtime evidence",
        payload={"topic": "agent runtime", "confidence": 0.9},
        source_type="evidence_item",
        run_id="run-1",
        report_id="report-1",
        evidence_id="evidence-1",
        source_item_id="raw-1",
        topic="agent runtime",
        section_id="section-1",
        published_at=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
    )

    payload = doc.to_payload()

    assert payload["document_id"] == "doc-1"
    assert payload["collection"] == "evidence_items"
    assert payload["text"] == "Agent runtime evidence"
    assert payload["source_type"] == "evidence_item"
    assert payload["run_id"] == "run-1"
    assert payload["report_id"] == "report-1"
    assert payload["evidence_id"] == "evidence-1"
    assert payload["source_item_id"] == "raw-1"
    assert payload["topic"] == "agent runtime"
    assert payload["section_id"] == "section-1"
    assert payload["published_at"] == "2026-05-10T12:00:00Z"
    assert payload["created_at"] == "2026-05-11T00:00:00Z"


def test_vector_search_result_round_trips_payload() -> None:
    result = VectorSearchResult.from_payload(
        score=0.91,
        payload={
            "document_id": "doc-1",
            "text": "Report section",
            "source_type": "report_section",
            "run_id": "run-1",
            "report_id": "report-1",
            "topic": "agent runtime",
            "section_id": "section-1",
            "source_item_ids": ["raw-1", "raw-2"],
            "published_at": "2026-05-10T12:00:00Z",
        },
    )

    assert result.document_id == "doc-1"
    assert result.score == 0.91
    assert result.text == "Report section"
    assert result.run_id == "run-1"
    assert result.report_id == "report-1"
    assert result.topic == "agent runtime"
    assert result.section_id == "section-1"
    assert result.published_at == "2026-05-10T12:00:00Z"
    assert result.refs() == {
        "run_id": "run-1",
        "report_id": "report-1",
        "section_id": "section-1",
        "source_item_ids": "raw-1,raw-2",
    }
    assert result.to_dict()["payload"]["source_type"] == "report_section"
    assert result.to_dict()["refs"]["section_id"] == "section-1"
