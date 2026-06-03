from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.report_evidence_view import (
    ReportEvidenceDraftView,
)


def test_report_evidence_view_projects_mapping_bundle() -> None:
    view = ReportEvidenceDraftView.from_bundle(
        {
            "item_count": 2,
            "items": [
                {
                    "title": "Lead",
                    "summary": "Summary",
                    "source_url": "https://example.com/lead",
                }
            ],
        }
    )

    assert view.item_count == 2
    assert view.lead.title == "Lead"
    assert view.source_urls == ("https://example.com/lead",)
    assert view.payload == [
        {
            "title": "Lead",
            "summary": "Summary",
            "source_url": "https://example.com/lead",
        }
    ]


def test_report_evidence_view_projects_object_items_with_payload() -> None:
    view = ReportEvidenceDraftView.from_bundle(
        _EvidenceBundle(
            item_count=1,
            items=[
                _EvidenceItem(
                    title="Object Lead",
                    summary="Object Summary",
                    source_url="https://example.com/object",
                )
            ],
            source_urls={"https://example.com/object"},
        )
    )

    assert view.lead.summary == "Object Summary"
    assert view.payload[0]["title"] == "Object Lead"


@dataclass(frozen=True)
class _EvidenceBundle:
    item_count: int
    items: list["_EvidenceItem"]
    source_urls: set[str]


@dataclass(frozen=True)
class _EvidenceItem:
    title: str
    summary: str
    source_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
        }
