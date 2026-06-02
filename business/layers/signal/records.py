from __future__ import annotations

from business.foundation.models.source import (
    DedupResult,
    DuplicateGroup,
    Lineage as SignalLineage,
    NormalizedSourceItem,
    RankedSourceItem,
    RawSourceItem,
    SourceDuplicateCluster,
    SourceItemQualityScore,
    SourceRankingSignals,
    SourceRankingTrace,
)
from business.layers.signal.source_processing import (
    deduplicate_items,
    deduplicate_with_result,
    detect_language,
    normalize_item,
    normalize_items,
    rank_items,
    score_source_item,
    score_source_items,
)
from business.layers.signal.source_processing.normalize import normalize_text
from business.layers.signal.source_processing.url_normalization import (
    canonicalize_url as canonicalize_source_url,
)

__all__ = [
    "DedupResult",
    "DuplicateGroup",
    "NormalizedSourceItem",
    "RankedSourceItem",
    "RawSourceItem",
    "SignalLineage",
    "SourceDuplicateCluster",
    "SourceItemQualityScore",
    "SourceRankingSignals",
    "SourceRankingTrace",
    "canonicalize_source_url",
    "deduplicate_items",
    "deduplicate_with_result",
    "detect_language",
    "normalize_item",
    "normalize_items",
    "normalize_text",
    "rank_items",
    "score_source_item",
    "score_source_items",
]
