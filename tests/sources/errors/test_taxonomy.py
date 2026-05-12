from urllib.error import HTTPError, URLError

from sources.errors import classify_source_exception


def test_source_error_taxonomy_classifies_parse_errors_as_non_health_affecting() -> None:
    classification = classify_source_exception(ValueError("bad feed"), phase="parse")

    assert classification.error_type == "parse_error"
    assert classification.retryable is False
    assert classification.source_health_affecting is False


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
