from __future__ import annotations

from dataclasses import dataclass
from xml.etree.ElementTree import ParseError
from urllib.error import HTTPError, URLError


FINAL_SOURCE_ERROR_TYPES = {
    "invalid_feed",
    "invalid_published_at",
    "normalization_error",
    "dedup_error",
    "ranking_error",
}


@dataclass(frozen=True)
class SourceErrorClassification:
    error_type: str
    retryable: bool
    source_health_affecting: bool
    workflow_blocking: bool = False
    operator_action_required: bool = False

    def to_tuple(self) -> tuple[str, bool]:
        return self.error_type, self.retryable


def classify_source_exception(
    exc: Exception,
    *,
    phase: str,
    invalid_config_keywords: tuple[str, ...] = (),
) -> SourceErrorClassification:
    if phase == "parse":
        message = str(exc).casefold()
        if isinstance(exc, ParseError) or "feed" in message or "rss" in message or "atom" in message:
            return SourceErrorClassification(
                error_type="invalid_feed",
                retryable=False,
                source_health_affecting=False,
            )
        if "published" in message or "pubdate" in message or "date" in message:
            return SourceErrorClassification(
                error_type="invalid_published_at",
                retryable=False,
                source_health_affecting=False,
            )
        return SourceErrorClassification(
            error_type="parse_error",
            retryable=False,
            source_health_affecting=False,
        )
    if phase == "normalize":
        return SourceErrorClassification(
            error_type="normalization_error",
            retryable=False,
            source_health_affecting=False,
        )
    if phase == "dedup":
        return SourceErrorClassification(
            error_type="dedup_error",
            retryable=False,
            source_health_affecting=False,
        )
    if phase == "rank":
        return SourceErrorClassification(
            error_type="ranking_error",
            retryable=False,
            source_health_affecting=False,
        )
    if _exception_type(exc) == "UnsupportedContentTypeError":
        return SourceErrorClassification(
            error_type="unsupported_content_type",
            retryable=False,
            source_health_affecting=False,
        )
    if _exception_type(exc) == "TooManyRedirectsError":
        return SourceErrorClassification(
            error_type="too_many_redirects",
            retryable=False,
            source_health_affecting=False,
        )
    if _exception_type(exc) == "RobotsDisallowedError":
        return SourceErrorClassification(
            error_type="robots_disallowed",
            retryable=False,
            source_health_affecting=False,
        )
    if _is_invalid_source_config(exc, invalid_config_keywords):
        return SourceErrorClassification(
            error_type="invalid_source_config",
            retryable=False,
            source_health_affecting=False,
            operator_action_required=True,
        )
    if isinstance(exc, HTTPError):
        if 400 <= exc.code < 500:
            return SourceErrorClassification(
                error_type="fetch_http_4xx",
                retryable=exc.code in {408, 409, 425, 429},
                source_health_affecting=True,
            )
        if exc.code >= 500:
            return SourceErrorClassification(
                error_type="fetch_http_5xx",
                retryable=True,
                source_health_affecting=True,
            )
        return SourceErrorClassification(
            error_type="fetch_connection_error",
            retryable=True,
            source_health_affecting=True,
        )
    if _is_timeout_exception(exc):
        return SourceErrorClassification(
            error_type="fetch_timeout",
            retryable=True,
            source_health_affecting=True,
        )
    if isinstance(exc, ValueError) and "max_bytes" in str(exc):
        return SourceErrorClassification(
            error_type="max_bytes_exceeded",
            retryable=False,
            source_health_affecting=False,
        )
    return SourceErrorClassification(
        error_type="fetch_connection_error",
        retryable=True,
        source_health_affecting=True,
    )


def _is_invalid_source_config(exc: Exception, invalid_config_keywords: tuple[str, ...]) -> bool:
    if not isinstance(exc, ValueError):
        return False
    message = str(exc).casefold()
    return any(keyword.casefold() in message for keyword in invalid_config_keywords)


def _exception_type(exc: Exception) -> str:
    return type(exc).__name__


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False
