from datetime import UTC, datetime

from domain.sources import SourceDefinition
from sources.connectors import ManualConnector


def test_manual_connector_parses_curated_records() -> None:
    source = _source()
    records = [
        {
            "title": "Reviewer submitted article",
            "url": "https://example.com/article",
            "summary": "Manual summary.",
            "published_at": "2026-05-11T08:00:00Z",
            "authors": ["Alice Example"],
            "tags": ["manual", "reviewed"],
            "submitted_by": "operator-1",
            "reviewer_score": 0.9,
            "metadata": {"note": "checked"},
        }
    ]

    items = ManualConnector().parse(source, records)

    assert len(items) == 1
    item = items[0]
    assert item.source_type.value == "manual"
    assert item.title == "Reviewer submitted article"
    assert item.url == "https://example.com/article"
    assert item.summary == "Manual summary."
    assert item.published_at == datetime(2026, 5, 11, 8, tzinfo=UTC)
    assert item.authors == ["Alice Example"]
    assert item.tags == ["manual", "reviewed"]
    assert item.language == "en"
    assert item.metadata["source_reliability"] == "high"
    assert item.metadata["manual_record_index"] == 0
    assert item.metadata["submitted_by"] == "operator-1"
    assert item.metadata["reviewer_score"] == 0.9
    assert item.metadata["note"] == "checked"


def test_manual_connector_fetch_reads_source_metadata_records_and_limit() -> None:
    source = SourceDefinition(
        source_id="manual",
        name="Manual",
        source_type="manual",
        url="manual://operator",
        metadata={
            "records": [
                {"title": "First", "url": "https://example.com/1"},
                {"title": "Second", "url": "https://example.com/2"},
            ]
        },
    )

    items, errors = ManualConnector().fetch(source, limit=1)

    assert errors == []
    assert len(items) == 1
    assert items[0].title == "First"


def test_manual_connector_returns_structured_parse_error_for_invalid_record() -> None:
    items, errors = ManualConnector().fetch(_source(), records=[{"url": "https://example.com/missing-title"}])

    assert items == []
    assert errors[0].error_type == "parse_error"
    assert errors[0].metadata["phase"] == "parse"
    assert "title" in errors[0].error_message


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="manual",
        name="Manual",
        source_type="manual",
        url="manual://operator",
        reliability="high",
        authority_score=0.7,
        language="en",
    )
