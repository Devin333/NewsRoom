from __future__ import annotations

from dataclasses import dataclass, field

from business.boards.cross_board.workflows.daily_intelligence.quality_rewrite import (
    rewrite_report_draft,
)


def test_rewrite_report_draft_uses_rewrite_evidence_lookup_for_missing_sources() -> None:
    rewritten = rewrite_report_draft(
        {
            "sections": [
                {
                    "title": "Summary",
                    "content": "Policy update summary",
                }
            ]
        },
        _EvidenceBundle(
            items=[
                _EvidenceItem(
                    source_url="https://example.com/policy",
                    title="Policy update",
                    summary="Policy update summary",
                )
            ]
        ),
        _Review(),
    )

    assert rewritten["sections"][0]["sources"] == ["https://example.com/policy"]
    assert rewritten["metadata"]["rewrite"]["preserve_evidence_boundary"] is True


def test_rewrite_report_draft_filters_removed_claim_grounding() -> None:
    rewritten = rewrite_report_draft(
        {
            "sections": [
                {
                    "title": "Summary",
                    "content": "Keep supported claim. Remove unsupported claim.",
                    "claim_grounding": [
                        {"text": "Keep supported claim.", "evidence_ids": ["ev-1"]},
                        {"text": "Remove unsupported claim.", "evidence_ids": ["ev-2"]},
                    ],
                }
            ]
        },
        _EvidenceBundle(items=[]),
        _Review(unsupported_claims=["Remove unsupported claim."]),
    )

    assert rewritten["sections"][0]["content"] == "Keep supported claim."
    assert rewritten["sections"][0]["claim_grounding"] == [
        {"text": "Keep supported claim.", "evidence_ids": ["ev-1"]}
    ]


@dataclass(frozen=True)
class _EvidenceBundle:
    items: list["_EvidenceItem"]


@dataclass(frozen=True)
class _EvidenceItem:
    source_url: str
    title: str
    summary: str


@dataclass(frozen=True)
class _Review:
    unsupported_claims: list[str] = field(default_factory=list)
    rewrite_instructions: list[str] = field(default_factory=list)
