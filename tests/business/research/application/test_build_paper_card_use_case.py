from __future__ import annotations

from business.research.application import BuildPaperCardUseCase
from tests.business.research.helpers import sample_paper


def test_build_paper_card_use_case_builds_basic_card() -> None:
    card = BuildPaperCardUseCase().build(sample_paper())

    assert card.paper_id == "paper-1"
    assert card.pdf_url == "https://arxiv.org/pdf/2606.00001"
    assert card.code_url == "https://github.com/newsroom/harnessed-research"
