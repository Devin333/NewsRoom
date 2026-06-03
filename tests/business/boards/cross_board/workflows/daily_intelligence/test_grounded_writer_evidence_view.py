from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.grounded_writer import (
    normalize_daily_writer_output,
)
from business.boards.cross_board.workflows.daily_intelligence.grounded_writer_evidence_view import (
    GroundedWriterEvidenceBundleView,
)
from business.layers.relation.evidence.models import VerifiedClaim, VerifiedFindings


def test_grounded_writer_evidence_view_selects_mapping_items() -> None:
    view = GroundedWriterEvidenceBundleView.from_bundle(
        {
            "items": [
                {
                    "evidence_id": "ev-1",
                    "title": "Policy update",
                    "source_url": "https://example.com/policy",
                    "source_urls": [
                        "https://example.com/policy",
                        "https://example.com/policy-alt",
                    ],
                }
            ]
        }
    )

    assert view is not None
    selection = view.select(["ev-1", "ev-missing"])

    assert selection.evidence_ids == ("ev-1",)
    assert selection.primary_title == "Policy update"
    assert selection.source_urls(["https://example.com/policy"]) == [
        "https://example.com/policy",
        "https://example.com/policy-alt",
    ]


def test_normalize_daily_writer_output_uses_grounded_evidence_view() -> None:
    output = normalize_daily_writer_output(
        output={"report_draft": {"title": "Daily", "sections": [], "metadata": {}}},
        output_key="report_draft",
        inputs={
            "evidence_bundle": _EvidenceBundle(
                items=[
                    _EvidenceItem(
                        evidence_id="ev-1",
                        title="Object evidence title",
                        source_url="https://example.com/object",
                        source_urls=("https://example.com/object-alt",),
                    )
                ]
            ),
            "verified_findings": VerifiedFindings(
                accepted_claims=[
                    VerifiedClaim(
                        claim_id="claim-1",
                        claim="Object evidence title: grounded claim.",
                        status="accepted",
                        confidence=0.9,
                        supporting_evidence_ids=["ev-1", "ev-missing"],
                        supporting_sources=["https://example.com/object"],
                    )
                ]
            ),
        },
    )

    section = output["report_draft"]["sections"][0]
    assert section["title"] == "Object evidence title"
    assert section["evidence_ids"] == ["ev-1"]
    assert section["sources"] == [
        "https://example.com/object",
        "https://example.com/object-alt",
    ]
    assert output["report_draft"]["metadata"][
        "writer_normalized_from_verified_findings"
    ] is True


@dataclass(frozen=True)
class _EvidenceBundle:
    items: list["_EvidenceItem"]


@dataclass(frozen=True)
class _EvidenceItem:
    evidence_id: str
    title: str
    source_url: str
    source_urls: tuple[str, ...]
