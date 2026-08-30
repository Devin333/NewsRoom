from urllib.error import HTTPError, URLError

from infrastructure.external.sources.errors import classify_source_exception
from backend.layers.signal.source_processing.error_taxonomy import (
    classify_source_exception as business_classify_source_exception,
)


def test_source_error_taxonomy_classifies_parse_errors_as_non_health_affecting() -> None:
    classification = classify_source_exception(ValueError("bad payload"), phase="parse")

    assert classification.error_type == "parse_error"
    assert classification.retryable is False
    assert classification.source_health_affecting is False


def test_source_error_taxonomy_classifies_final_source_parse_branches() -> None:
    invalid_feed = classify_source_exception(ValueError("unsupported feed root"), phase="parse")
    invalid_date = classify_source_exception(ValueError("invalid published date"), phase="parse")

    assert invalid_feed.error_type == "invalid_feed"
    assert invalid_feed.retryable is False
    assert invalid_date.error_type == "invalid_published_at"
    assert invalid_date.source_health_affecting is False


def test_source_error_taxonomy_classifies_processing_phases() -> None:
    assert classify_source_exception(RuntimeError("bad normalize"), phase="normalize").error_type == "normalization_error"
    assert classify_source_exception(RuntimeError("bad dedup"), phase="dedup").error_type == "dedup_error"
    assert classify_source_exception(RuntimeError("bad rank"), phase="rank").error_type == "ranking_error"


def test_source_error_taxonomy_classifies_timeout_as_retryable_fetch_timeout() -> None:
    classification = classify_source_exception(URLError(TimeoutError("timed out")), phase="fetch")

    assert classification.error_type == "fetch_timeout"
    assert classification.retryable is True
    assert classification.source_health_affecting is True


def test_source_error_taxonomy_classifies_http_status_families() -> None:
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

    assert rate_limited.error_type == "fetch_http_4xx"
    assert rate_limited.retryable is True
    assert not_found.error_type == "fetch_http_4xx"
    assert not_found.retryable is False
    assert server_error.error_type == "fetch_http_5xx"
    assert server_error.retryable is True


def test_source_error_taxonomy_classifies_config_keywords() -> None:
    classification = classify_source_exception(
        ValueError("github repository must use owner/repo format"),
        phase="fetch",
        invalid_config_keywords=("repository",),
    )

    assert classification.error_type == "invalid_source_config"
    assert classification.retryable is False
    assert classification.source_health_affecting is False
    assert classification.operator_action_required is True


def test_infrastructure_taxonomy_is_behavior_free_business_adapter() -> None:
    assert classify_source_exception is business_classify_source_exception
