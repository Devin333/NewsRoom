from __future__ import annotations

import pytest

from business.boards.cross_board.workflows.daily_intelligence.report_draft_normalization import (
    ReportDraftNormalizationError,
    normalize_report_draft,
    source_urls_from_evidence,
    sources_outside_evidence,
)


def test_normalize_report_draft_unwraps_payload_and_normalizes_sections() -> None:
    draft = normalize_report_draft(
        {
            "report_draft": {
                "sections": [
                    {
                        "id": "summary",
                        "content": None,
                        "source_urls": ["https://example.com/source"],
                        "evidence_ids": ("ev-1",),
                        "claim_grounding": [
                            {
                                "claim": "The source supports the claim.",
                                "sources": ["https://example.com/source"],
                                "evidence_ids": ["ev-1"],
                            },
                            "ignored",
                        ],
                    }
                ],
                "metadata": ["not", "a", "mapping"],
            }
        }
    )

    assert draft["title"] == "Daily Intelligence Report"
    assert draft["metadata"] == {}
    assert draft["sections"] == [
        {
            "id": "summary",
            "section_id": "summary",
            "title": "Section 1",
            "content": "",
            "sources": ["https://example.com/source"],
            "source_urls": ["https://example.com/source"],
            "evidence_ids": ["ev-1"],
            "claim_grounding": [
                {
                    "claim_id": "",
                    "text": "The source supports the claim.",
                    "evidence_ids": ["ev-1"],
                    "source_urls": ["https://example.com/source"],
                }
            ],
        }
    ]


def test_normalize_report_draft_rejects_non_list_sections() -> None:
    with pytest.raises(ReportDraftNormalizationError, match="sections must be a list"):
        normalize_report_draft({"title": "Broken", "sections": "not-a-list"})


def test_sources_outside_evidence_uses_all_evidence_source_shapes() -> None:
    draft = {
        "sections": [
            {
                "sources": [
                    "https://example.com/root",
                    "https://example.com/map",
                    "https://example.com/item",
                    "https://example.com/item-list",
                    "https://example.com/outside",
                ]
            }
        ]
    }
    evidence_bundle = {
        "source_urls": ["https://example.com/root"],
        "source_map": {"https://example.com/map": {"source_id": "mapped"}},
        "items": [
            {
                "source_url": "https://example.com/item",
                "source_urls": ["https://example.com/item-list"],
            }
        ],
    }

    assert source_urls_from_evidence(evidence_bundle) == {
        "https://example.com/root",
        "https://example.com/map",
        "https://example.com/item",
        "https://example.com/item-list",
    }
    assert sources_outside_evidence(draft, evidence_bundle) == ["https://example.com/outside"]
