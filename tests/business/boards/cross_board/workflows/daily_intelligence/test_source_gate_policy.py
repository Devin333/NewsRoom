from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.source_gate_policy import (
    contains_social_media_evidence,
    is_social_media_evidence,
)
from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
)


@dataclass(frozen=True)
class _EvidenceBundle:
    items: list["_EvidenceItem"]


@dataclass(frozen=True)
class _EvidenceItem:
    source_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


def test_social_media_evidence_matches_community_source_type() -> None:
    item = _EvidenceItem(
        source_url="https://example.com/post",
        metadata={"source_type": "reddit"},
    )

    assert is_social_media_evidence(item) is True
    assert contains_social_media_evidence(_EvidenceBundle(items=[item])) is True


def test_social_media_evidence_matches_normalized_category() -> None:
    item = _EvidenceItem(
        source_url="https://example.com/post",
        metadata={"category": "Developer Community"},
    )

    assert is_social_media_evidence(item) is True


def test_social_media_evidence_matches_known_domain_fallback() -> None:
    item = _EvidenceItem(source_url="https://news.ycombinator.com/item?id=123")

    assert is_social_media_evidence(item) is True


def test_social_media_evidence_view_projects_mapping_items() -> None:
    bundle = SourceGateEvidenceBundleView.from_bundle(
        {
            "items": [
                {
                    "source_url": "https://example.com/post",
                    "metadata": {"category": "developer-community"},
                }
            ]
        }
    )

    assert bundle.item_count == 1
    assert is_social_media_evidence(bundle.items[0]) is True


def test_non_social_evidence_does_not_match_social_gate() -> None:
    item = _EvidenceItem(
        source_url="https://example.com/feed",
        metadata={"source_type": "rss", "category": "official"},
    )

    assert is_social_media_evidence(item) is False
    assert contains_social_media_evidence(_EvidenceBundle(items=[item])) is False


def test_source_gate_evidence_bundle_view_exposes_item_count() -> None:
    bundle = SourceGateEvidenceBundleView.from_bundle(
        _EvidenceBundle(
            items=[
                _EvidenceItem(source_url="https://example.com/one"),
                _EvidenceItem(source_url="https://example.com/two"),
            ]
        )
    )

    assert bundle.item_count == 2
    assert SourceGateEvidenceBundleView.from_bundle(bundle) is bundle
