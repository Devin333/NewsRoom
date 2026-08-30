from __future__ import annotations

from backend.research.reader import (
    ReaderPayloadBuilder,
    validate_reader_navigation,
    validate_reader_payload_schema,
    validate_reader_source_lineage,
)
from tests.backend.research.helpers import sample_document, sample_paper


def test_reader_payload_serializes_sections_navigation_and_lineage() -> None:
    payload = ReaderPayloadBuilder().build(paper=sample_paper(), document=sample_document())

    serialized = payload.to_dict()

    assert serialized["paper"]["paper_id"] == "paper-1"
    assert serialized["document"]["sections"][0]["section_id"] == "sec-intro"
    assert serialized["navigation"][0]["target_ref"] == "sec-intro"
    assert serialized["source_lineage"]["source_refs"] == ["paper://paper-1"]
    assert validate_reader_payload_schema(payload).passed is True
    assert validate_reader_source_lineage(payload).passed is True
    assert validate_reader_navigation(payload).passed is True
