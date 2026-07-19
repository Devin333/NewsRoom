"""Source Pipeline error construction and taxonomy adapters."""

from infrastructure.external.sources.errors.taxonomy import (
    SourceErrorClassification,
    SourceTaxonomyExtension,
    classify_source_exception,
)
from infrastructure.external.sources.errors.factory import (
    SourceErrorContext,
    SourceErrorDiagnostics,
    build_source_error,
    rate_limited_source_error,
    source_error_from_exception,
)

__all__ = [
    "SourceErrorClassification",
    "SourceErrorContext",
    "SourceErrorDiagnostics",
    "SourceTaxonomyExtension",
    "build_source_error",
    "classify_source_exception",
    "rate_limited_source_error",
    "source_error_from_exception",
]
