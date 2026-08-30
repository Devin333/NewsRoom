from __future__ import annotations

from backend.research.services import ResearchEvidenceBuilder
from tests.backend.research.helpers import sample_document


def test_evidence_builder_records_section_lineage() -> None:
    evidence_pack = ResearchEvidenceBuilder().build_from_document(document=sample_document())

    assert evidence_pack.items[0].source_ref == "paper://paper-1/sec-intro"
    assert evidence_pack.lineage.source_refs == ["paper://paper-1/sec-intro"]
    assert evidence_pack.coverage["sections"] == 1.0
