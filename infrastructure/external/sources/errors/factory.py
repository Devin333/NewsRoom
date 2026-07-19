from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from infrastructure.external.sources.errors.taxonomy import (
    SourceErrorClassification,
    SourceTaxonomyExtension,
    classify_source_exception,
)
from infrastructure.external.sources.fetch_policy import (
    RateLimitDecision,
    RobotsDisallowedError,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
    fetch_attempts,
    fetch_retry_decision,
)
from infrastructure.external.sources.models import SourceDefinition, SourceError


RESERVED_POLICY_METADATA_KEYS = frozenset(
    {
        "phase",
        "retryable",
        "source_health_affecting",
        "workflow_blocking",
        "operator_action_required",
        "original_exception_type",
        "request_id",
    }
)


@dataclass(frozen=True)
class SourceErrorContext:
    phase: str
    url: str | None = None
    request_id: str | None = None
    request_ref: Any | None = None
    response_ref: Any | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        phase = str(self.phase).strip().casefold()
        if not phase:
            raise ValueError("SourceErrorContext.phase is required")
        object.__setattr__(self, "phase", phase)
        if self.request_id is not None:
            request_id = str(self.request_id).strip()
            if not request_id:
                raise ValueError("SourceErrorContext.request_id cannot be blank")
            object.__setattr__(self, "request_id", request_id)
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("SourceErrorContext.occurred_at must be timezone-aware")


@dataclass(frozen=True)
class SourceErrorDiagnostics:
    status_code: int | None = None
    attempts: int | None = None
    content_type: str | None = None
    supported_content_types: tuple[str, ...] = ()
    redirect_url: str | None = None
    max_redirects: int | None = None
    robots_url: str | None = None
    user_agent: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        extra = dict(self.extra)
        conflicts = sorted(RESERVED_POLICY_METADATA_KEYS.intersection(extra))
        if conflicts:
            raise ValueError(
                "SourceError diagnostics cannot override reserved metadata: "
                + ", ".join(conflicts)
            )
        object.__setattr__(
            self, "supported_content_types", tuple(self.supported_content_types)
        )
        object.__setattr__(self, "extra", MappingProxyType(extra))

    def to_metadata(self) -> dict[str, object]:
        metadata = dict(self.extra)
        optional_values: tuple[tuple[str, object | None], ...] = (
            ("status_code", self.status_code),
            ("attempts", self.attempts),
            ("content_type", self.content_type),
            (
                "supported_content_types",
                list(self.supported_content_types)
                if self.supported_content_types
                else None,
            ),
            ("redirect_url", self.redirect_url),
            ("max_redirects", self.max_redirects),
            ("robots_url", self.robots_url),
            ("user_agent", self.user_agent),
        )
        metadata.update(
            {key: value for key, value in optional_values if value is not None}
        )
        return metadata

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> SourceErrorDiagnostics:
        return cls(
            status_code=getattr(exc, "code", None),
            attempts=fetch_attempts(exc),
            content_type=(
                exc.content_type
                if isinstance(exc, UnsupportedContentTypeError)
                else None
            ),
            supported_content_types=(
                exc.supported_content_types
                if isinstance(exc, UnsupportedContentTypeError)
                else ()
            ),
            redirect_url=exc.url if isinstance(exc, TooManyRedirectsError) else None,
            max_redirects=exc.max_redirects
            if isinstance(exc, TooManyRedirectsError)
            else None,
            robots_url=exc.robots_url
            if isinstance(exc, RobotsDisallowedError)
            else None,
            user_agent=exc.user_agent
            if isinstance(exc, RobotsDisallowedError)
            else None,
            extra=extra or {},
        )


def build_source_error(
    source: SourceDefinition,
    error_type: str,
    error_message: str,
    *,
    context: SourceErrorContext,
    retryable: bool,
    source_health_affecting: bool,
    workflow_blocking: bool = False,
    operator_action_required: bool = False,
    diagnostics: SourceErrorDiagnostics | None = None,
) -> SourceError:
    classification = SourceErrorClassification(
        error_type=error_type,
        retryable=retryable,
        source_health_affecting=source_health_affecting,
        workflow_blocking=workflow_blocking,
        operator_action_required=operator_action_required,
    )
    return _build_source_error(
        source,
        error_message=error_message,
        classification=classification,
        context=context,
        diagnostics=diagnostics,
    )


def rate_limited_source_error(
    source: SourceDefinition,
    decision: RateLimitDecision,
    *,
    url: str,
) -> SourceError:
    if decision.allowed:
        raise ValueError("rate_limited_source_error requires a denied decision")
    return build_source_error(
        source,
        "rate_limited",
        f"source fetch rate limit reached for domain: {decision.domain}",
        context=SourceErrorContext(phase="fetch", url=url),
        retryable=True,
        source_health_affecting=False,
        diagnostics=SourceErrorDiagnostics(
            extra={
                "domain": decision.domain,
                "limit_per_minute": decision.limit_per_minute,
                "window_seconds": decision.window_seconds,
                "retry_after_seconds": decision.retry_after_seconds,
            }
        ),
    )


def source_error_from_exception(
    source: SourceDefinition,
    exc: Exception,
    *,
    context: SourceErrorContext,
    extension: SourceTaxonomyExtension | None = None,
    effective_retryable: bool | None = None,
    diagnostics: SourceErrorDiagnostics | None = None,
) -> SourceError:
    retry_decision = fetch_retry_decision(exc)
    if effective_retryable is None and retry_decision is not None:
        effective_retryable = retry_decision.retryable
    classification = classify_source_exception(
        exc,
        phase=context.phase,
        extension=extension,
        effective_retryable=effective_retryable,
    )
    return _build_source_error(
        source,
        error_message=str(exc),
        classification=classification,
        context=context,
        diagnostics=diagnostics or SourceErrorDiagnostics.from_exception(exc),
        original_exception_type=type(exc).__name__,
    )


def _build_source_error(
    source: SourceDefinition,
    *,
    error_message: str,
    classification: SourceErrorClassification,
    context: SourceErrorContext,
    diagnostics: SourceErrorDiagnostics | None,
    original_exception_type: str | None = None,
) -> SourceError:
    metadata: dict[str, object] = {
        "phase": context.phase,
        "retryable": classification.retryable,
        "source_health_affecting": classification.source_health_affecting,
        "workflow_blocking": classification.workflow_blocking,
        "operator_action_required": classification.operator_action_required,
    }
    if original_exception_type is not None:
        metadata["original_exception_type"] = original_exception_type
    if context.request_id is not None:
        metadata["request_id"] = context.request_id
    if diagnostics is not None:
        metadata.update(diagnostics.to_metadata())

    kwargs: dict[str, Any] = {
        "source_id": source.source_id,
        "source_name": source.name,
        "error_type": classification.error_type,
        "error_message": error_message,
        "url": context.url if context.url is not None else source.url,
        "retryable": classification.retryable,
        "request_ref": context.request_ref,
        "response_ref": context.response_ref,
        "metadata": metadata,
    }
    if context.occurred_at is not None:
        kwargs["occurred_at"] = context.occurred_at
    return SourceError(**kwargs)


__all__ = [
    "RESERVED_POLICY_METADATA_KEYS",
    "SourceErrorContext",
    "SourceErrorDiagnostics",
    "build_source_error",
    "rate_limited_source_error",
    "source_error_from_exception",
]
