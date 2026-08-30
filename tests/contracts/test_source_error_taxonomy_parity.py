from __future__ import annotations

from urllib.error import HTTPError, URLError
from xml.etree.ElementTree import ParseError

import pytest

from backend.layers.signal.source_processing.error_taxonomy import (
    SourceErrorClassification,
    SourceTaxonomyExtension,
    classify_source_exception as classify_business_source_exception,
)
from infrastructure.external.sources.errors import (
    classify_source_exception as classify_infrastructure_source_exception,
)
from infrastructure.external.sources.fetch_policy import (
    RobotsDisallowedError,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
)


@pytest.mark.parametrize(
    (
        "exc",
        "phase",
        "extension",
        "effective_retryable",
        "expected",
    ),
    [
        (
            ParseError("bad XML"),
            "parse",
            None,
            None,
            SourceErrorClassification("invalid_feed", False, False),
        ),
        (
            ValueError("invalid published date"),
            "parse",
            None,
            None,
            SourceErrorClassification("invalid_published_at", False, False),
        ),
        (
            ValueError("bad item"),
            "parse",
            None,
            None,
            SourceErrorClassification("parse_error", False, False),
        ),
        (
            RuntimeError("bad normalize"),
            "normalize",
            None,
            None,
            SourceErrorClassification("normalization_error", False, False),
        ),
        (
            RuntimeError("bad dedup"),
            "dedup",
            None,
            None,
            SourceErrorClassification("dedup_error", False, False),
        ),
        (
            RuntimeError("bad rank"),
            "rank",
            None,
            None,
            SourceErrorClassification("ranking_error", False, False),
        ),
        (
            UnsupportedContentTypeError("text/html", ("application/json",)),
            "fetch",
            None,
            None,
            SourceErrorClassification("unsupported_content_type", False, False),
        ),
        (
            TooManyRedirectsError("https://example.com/redirect", 3),
            "fetch",
            None,
            None,
            SourceErrorClassification("too_many_redirects", False, False),
        ),
        (
            RobotsDisallowedError(
                "https://example.com/private",
                "https://example.com/robots.txt",
                "NewsRoomTest/1.0",
            ),
            "fetch",
            None,
            None,
            SourceErrorClassification("robots_disallowed", False, False),
        ),
        (
            ValueError("source response exceeds max_bytes: 100"),
            "fetch",
            None,
            None,
            SourceErrorClassification("max_bytes_exceeded", False, False),
        ),
        (
            HTTPError(
                "https://example.com/missing",
                404,
                "Not Found",
                hdrs=None,
                fp=None,
            ),
            "fetch",
            None,
            True,
            SourceErrorClassification("fetch_http_4xx", True, True),
        ),
        (
            HTTPError(
                "https://example.com/unavailable",
                503,
                "Unavailable",
                hdrs=None,
                fp=None,
            ),
            "probe",
            None,
            False,
            SourceErrorClassification("fetch_http_5xx", False, True),
        ),
        (
            TimeoutError("timed out"),
            "fetch",
            None,
            None,
            SourceErrorClassification("fetch_timeout", True, True),
        ),
        (
            URLError("connection reset"),
            "probe",
            None,
            None,
            SourceErrorClassification("fetch_connection_error", True, True),
        ),
        (
            RuntimeError("connection failed"),
            "fetch",
            None,
            None,
            SourceErrorClassification("fetch_connection_error", True, True),
        ),
        (
            ValueError("repository is required"),
            "fetch",
            SourceTaxonomyExtension(invalid_config_keywords=("repository",)),
            None,
            SourceErrorClassification(
                "invalid_source_config",
                False,
                False,
                operator_action_required=True,
            ),
        ),
    ],
)
def test_source_taxonomy_golden_matrix_and_adapter_parity(
    exc: Exception,
    phase: str,
    extension: SourceTaxonomyExtension | None,
    effective_retryable: bool | None,
    expected: SourceErrorClassification,
) -> None:
    kwargs = {
        "phase": phase,
        "extension": extension,
        "effective_retryable": effective_retryable,
    }

    business = classify_business_source_exception(exc, **kwargs)
    infrastructure = classify_infrastructure_source_exception(exc, **kwargs)

    assert business == expected
    assert infrastructure == expected
    assert business.workflow_blocking is False


def test_infrastructure_taxonomy_adapter_is_the_business_classifier() -> None:
    assert (
        classify_infrastructure_source_exception
        is classify_business_source_exception
    )
