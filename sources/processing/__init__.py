"""Source processing helpers."""

from sources.processing.coverage import build_source_coverage_report
from sources.processing.deduplicate import deduplicate_items, deduplicate_with_result
from sources.processing.language import detect_language
from sources.processing.normalize import normalize_items
from sources.processing.quality import score_source_item, score_source_items
from sources.processing.rank import rank_items

__all__ = [
    "build_source_coverage_report",
    "deduplicate_items",
    "deduplicate_with_result",
    "detect_language",
    "normalize_items",
    "rank_items",
    "score_source_item",
    "score_source_items",
]
