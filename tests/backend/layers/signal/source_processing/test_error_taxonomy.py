from dataclasses import FrozenInstanceError
from urllib.error import HTTPError, URLError
from xml.etree.ElementTree import ParseError

import pytest

from backend.layers.signal.source_processing.error_taxonomy import (
    SourceTaxonomyExtension,
    classify_source_exception,
)


def test_business_source_error_taxonomy_classifies_parse_errors() -> None:
    invalid_feed = classify_source_exception(ValueError("unsupported feed root"), phase="parse")
    invalid_date = classify_source_exception(ValueError("invalid published date"), phase="parse")
    parse_error = classify_source_exception(ValueError("bad payload"), phase="parse")

    assert invalid_feed.error_type == "invalid_feed"
    assert invalid_feed.retryable is False
    assert invalid_date.error_type == "invalid_published_at"
    assert invalid_date.source_health_affecting is False
    assert parse_error.error_type == "parse_error"


def test_business_source_error_taxonomy_classifies_processing_phases() -> None:
    assert classify_source_exception(RuntimeError("bad normalize"), phase="normalize").error_type == "normalization_error"
    assert classify_source_exception(RuntimeError("bad dedup"), phase="dedup").error_type == "dedup_error"
    assert classify_source_exception(RuntimeError("bad rank"), phase="rank").error_type == "ranking_error"


def test_business_source_error_taxonomy_classifies_fetch_failures() -> None:
    timeout = classify_source_exception(URLError(TimeoutError("timed out")), phase="fetch")
    rate_limited = classify_source_exception(
        HTTPError("https://example.com", 429, "Too Many Requests", hdrs=None, fp=None),
        phase="fetch",
    )
    not_found = classify_source_exception(
        HTTPError("https://example.com", 404, "Not Found", hdrs=None, fp=None),
        phase="fetch",
    )
    server_error = classify_source_exception(
        HTTPError("https://example.com", 503, "Unavailable", hdrs=None, fp=None),
        phase="fetch",
    )

    assert timeout.error_type == "fetch_timeout"
    assert timeout.retryable is True
    assert rate_limited.error_type == "fetch_http_4xx"
    assert rate_limited.retryable is True
    assert not_found.error_type == "fetch_http_4xx"
    assert not_found.retryable is False
    assert server_error.error_type == "fetch_http_5xx"
    assert server_error.retryable is True


@pytest.mark.parametrize(
    ("exc", "phase", "error_type", "retryable", "health_affecting", "operator_action"),
    [
        (ParseError("bad xml"), "parse", "invalid_feed", False, False, False),
        (ValueError("invalid published date"), "parse", "invalid_published_at", False, False, False),
        (ValueError("bad item"), "parse", "parse_error", False, False, False),
        (RuntimeError("bad normalize"), "normalize", "normalization_error", False, False, False),
        (RuntimeError("bad dedup"), "dedup", "dedup_error", False, False, False),
        (RuntimeError("bad rank"), "rank", "ranking_error", False, False, False),
        (TimeoutError("timed out"), "fetch", "fetch_timeout", True, True, False),
        (URLError("connection reset"), "fetch", "fetch_connection_error", True, True, False),
    ],
)
def test_business_source_error_taxonomy_golden_matrix(
    exc: Exception,
    phase: str,
    error_type: str,
    retryable: bool,
    health_affecting: bool,
    operator_action: bool,
) -> None:
    classification = classify_source_exception(exc, phase=phase)

    assert classification.error_type == error_type
    assert classification.retryable is retryable
    assert classification.source_health_affecting is health_affecting
    assert classification.workflow_blocking is False
    assert classification.operator_action_required is operator_action


def test_business_source_error_taxonomy_uses_immutable_extensions() -> None:
    extension = SourceTaxonomyExtension(invalid_config_keywords=(" repository ", "token"))

    classification = classify_source_exception(
        ValueError("repository is required"),
        phase="fetch",
        extension=extension,
    )

    assert extension.invalid_config_keywords == ("repository", "token")
    assert classification.error_type == "invalid_source_config"
    assert classification.operator_action_required is True
    with pytest.raises(FrozenInstanceError):
        extension.invalid_config_keywords = ()  # type: ignore[misc]


def test_business_source_error_taxonomy_accepts_effective_fetch_retry_decision() -> None:
    retryable_404 = classify_source_exception(
        HTTPError("https://example.com", 404, "Not Found", hdrs=None, fp=None),
        phase="fetch",
        effective_retryable=True,
    )
    non_retryable_503 = classify_source_exception(
        HTTPError("https://example.com", 503, "Unavailable", hdrs=None, fp=None),
        phase="probe",
        effective_retryable=False,
    )

    assert retryable_404.error_type == "fetch_http_4xx"
    assert retryable_404.retryable is True
    assert non_retryable_503.error_type == "fetch_http_5xx"
    assert non_retryable_503.retryable is False

    with pytest.raises(ValueError, match="only valid for fetch or probe"):
        classify_source_exception(
            ValueError("bad item"),
            phase="parse",
            effective_retryable=True,
        )
