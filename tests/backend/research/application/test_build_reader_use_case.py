from __future__ import annotations

from backend.research.application import BuildReaderUseCase
from tests.backend.research.helpers import sample_document, sample_paper


def test_build_reader_use_case_uses_reader_payload_builder() -> None:
    payload = BuildReaderUseCase().build(paper=sample_paper(), document=sample_document())

    assert payload.paper.paper_id == "paper-1"
    assert payload.navigation[0].target_ref == "sec-intro"
    assert payload.status == "ready"
