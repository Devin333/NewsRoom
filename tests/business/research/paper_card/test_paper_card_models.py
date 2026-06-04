from __future__ import annotations

from business.research.paper_card import (
    PaperCardBuilder,
    validate_github_metrics_source,
    validate_paper_card_summary_evidence,
)
from tests.business.research.helpers import sample_paper, sample_three_minute_read


def test_paper_card_serializes_real_repository_metrics() -> None:
    card = PaperCardBuilder().build(
        paper=sample_paper(),
        three_minute_read=sample_three_minute_read(),
        taxonomy={"domains": ["code"], "areas": ["agent"], "tasks": ["paper_reading"]},
        github={
            "repo_url": "https://github.com/newsroom/harnessed-research",
            "stars": 42,
            "forks": 3,
            "license": "MIT",
            "star_growth_daily": 2.5,
            "metrics_source": "github_repository_port",
        },
        reader_payload_status="ready",
    )

    payload = card.to_dict()

    assert payload["github_stars"] == 42
    assert payload["github_star_growth_daily"] == 2.5
    assert payload["reader_payload_status"] == "ready"
    assert validate_github_metrics_source(card).passed is True
    assert validate_paper_card_summary_evidence(card).passed is True


def test_github_metrics_cannot_be_marked_as_llm_generated() -> None:
    card = PaperCardBuilder().build(
        paper=sample_paper(),
        github={"repo_url": "https://github.com/newsroom/harnessed-research", "stars": 99, "metrics_source": "llm"},
    )

    result = validate_github_metrics_source(card)

    assert result.passed is False
    assert "real GitHub data source" in result.reasons[0]
