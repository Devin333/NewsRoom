"""Behavior-free adapter to the business-owned Source error taxonomy."""

from backend.layers.signal.source_processing.error_taxonomy import (
    SourceErrorClassification,
    SourceTaxonomyExtension,
    classify_source_exception,
)

__all__ = [
    "SourceErrorClassification",
    "SourceTaxonomyExtension",
    "classify_source_exception",
]
