from urllib.error import HTTPError, URLError

from business.layers.signal.source_processing.error_taxonomy import classify_source_exception


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
