from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
    SourceGateEvidenceItemView,
)
from business.layers.signal.source_processing.governance import COMMUNITY_CATEGORIES, COMMUNITY_SOURCE_TYPES


SOCIAL_MEDIA_DOMAINS = (
    "reddit.com",
    "news.ycombinator.com",
    "lobste.rs",
    "stackoverflow.com",
    "dev.to",
    "medium.com",
)


def contains_social_media_evidence(evidence_bundle: Any) -> bool:
    for item in SourceGateEvidenceBundleView.from_bundle(evidence_bundle).items:
        if is_social_media_evidence(item):
            return True
    return False


def is_social_media_evidence(item: Any) -> bool:
    item_view = _source_gate_item_view(item)
    if item_view.source_type in COMMUNITY_SOURCE_TYPES or item_view.category in COMMUNITY_CATEGORIES:
        return True
    return any(domain in item_view.source_url for domain in SOCIAL_MEDIA_DOMAINS)


def _source_gate_item_view(item: Any) -> SourceGateEvidenceItemView:
    if isinstance(item, SourceGateEvidenceItemView):
        return item
    return SourceGateEvidenceItemView.from_item(item)


__all__ = ["contains_social_media_evidence", "is_social_media_evidence"]
