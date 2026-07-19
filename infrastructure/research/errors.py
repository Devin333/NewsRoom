from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


class ResearchAdapterError(RuntimeError):
    """Base error for concrete Research outbound adapters."""

    error_code = "research_adapter_error"
    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = bool(retryable)


class ResearchSourceError(ResearchAdapterError):
    error_code = "research_source_error"


class ResearchDocumentCompileError(ResearchAdapterError):
    error_code = "research_document_compile_error"


class ResearchRepositoryError(ResearchAdapterError):
    error_code = "research_repository_error"


@dataclass(frozen=True)
class SourceAdapterFailureSummary:
    error_types: tuple[str, ...]
    retryable: bool


def summarize_source_failures(
    errors: Iterable[Any],
    *,
    default_error_type: str,
) -> SourceAdapterFailureSummary:
    error_types: set[str] = set()
    retryable = False
    for error in errors:
        error_types.add(str(getattr(error, "error_type", None) or default_error_type))
        explicit_retryable = getattr(error, "retryable", None)
        if isinstance(explicit_retryable, bool):
            retryable = retryable or explicit_retryable
            continue
        metadata = getattr(error, "metadata", {})
        if isinstance(metadata, dict):
            retryable = retryable or bool(metadata.get("retryable"))
    if not error_types:
        error_types.add(default_error_type)
    return SourceAdapterFailureSummary(
        error_types=tuple(sorted(error_types)),
        retryable=retryable,
    )


__all__ = [
    "ResearchAdapterError",
    "ResearchDocumentCompileError",
    "ResearchRepositoryError",
    "ResearchSourceError",
    "SourceAdapterFailureSummary",
    "summarize_source_failures",
]
