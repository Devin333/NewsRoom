"""Source processing helpers."""

from sources.processing.coverage import build_source_coverage_report
from sources.processing.deduplicate import deduplicate_items, deduplicate_with_result
from sources.processing.dispatch import build_source_connector_dispatch_report
from sources.processing.error_policy import build_source_error_policy_report
from sources.processing.fallback import build_source_fallback_report
from sources.processing.freshness import build_source_freshness_report
from sources.processing.governance import build_source_governance_report
from sources.processing.language import detect_language
from sources.processing.normalize import normalize_items
from sources.processing.quality import score_source_item, score_source_items
from sources.processing.rank import rank_items
from sources.processing.ranking_report import build_source_ranking_scores
from sources.processing.traceability import build_source_traceability_report

__all__ = [
    "build_source_coverage_report",
    "build_source_connector_dispatch_report",
    "build_source_error_policy_report",
    "build_source_fallback_report",
    "build_source_freshness_report",
    "build_source_governance_report",
    "deduplicate_items",
    "deduplicate_with_result",
    "detect_language",
    "normalize_items",
    "rank_items",
    "build_source_ranking_scores",
    "build_source_traceability_report",
    "score_source_item",
    "score_source_items",
]
