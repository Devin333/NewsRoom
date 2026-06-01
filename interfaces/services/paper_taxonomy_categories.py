"""Compatibility exports for canonical paper radar taxonomy categories."""

from __future__ import annotations

from business.boards.paper_radar.taxonomy_categories import (
    AI_TASK_GROUPS,
    BENCHMARK_CATEGORIES,
    FALLBACK_PWC_METHOD_COLLECTIONS,
    benchmark_category_options,
    load_pwc_method_collections,
    method_collection_options,
    normalize_ai_task_group,
    normalize_benchmark_category,
    normalize_method_collection,
    task_group_options,
)

__all__ = [
    "AI_TASK_GROUPS",
    "BENCHMARK_CATEGORIES",
    "FALLBACK_PWC_METHOD_COLLECTIONS",
    "benchmark_category_options",
    "load_pwc_method_collections",
    "method_collection_options",
    "normalize_ai_task_group",
    "normalize_benchmark_category",
    "normalize_method_collection",
    "task_group_options",
]
