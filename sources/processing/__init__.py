"""Source processing helpers."""

from sources.processing.coverage import build_source_coverage_report
from sources.processing.deduplicate import deduplicate_items, deduplicate_with_result
from sources.processing.normalize import normalize_items
from sources.processing.rank import rank_items

__all__ = [
    "build_source_coverage_report",
    "deduplicate_items",
    "deduplicate_with_result",
    "normalize_items",
    "rank_items",
]
