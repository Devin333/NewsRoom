from __future__ import annotations

from datetime import timedelta

import pytest

from business.foundation.models.source_error_normalization import (
    normalize_source_errors,
)


def _payload(**overrides):
    payload = {
        "source_id": "rss-source",
        "source_name": "RSS Source",
        "error_type": "fetch_timeout",
        "error_message": "timed out",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("value", ["true", "TRUE", " 1 ", "yes", "On"])
def test_source_error_reader_normalizes_documented_true_strings(value: str) -> None:
    error = normalize_source_errors([_payload(retryable=value)])[0]

    assert error.retryable is True


@pytest.mark.parametrize("value", ["false", "FALSE", " 0 ", "no", "Off"])
def test_source_error_reader_normalizes_documented_false_strings(value: str) -> None:
    error = normalize_source_errors([_payload(retryable=value)])[0]

    assert error.retryable is False


def test_source_error_reader_applies_retryable_precedence() -> None:
    top_level = normalize_source_errors(
        [_payload(retryable="false", metadata={"retryable": "true"})]
    )[0]
    legacy_metadata = normalize_source_errors(
        [_payload(metadata={"retryable": "false"})]
    )[0]
    compatibility_default = normalize_source_errors([_payload()])[0]

    assert top_level.retryable is False
    assert top_level.metadata["retryable"] is False
    assert legacy_metadata.retryable is False
    assert legacy_metadata.metadata["retryable"] is False
    assert compatibility_default.retryable is True


@pytest.mark.parametrize("value", ["maybe", "", 1, 0, [], {}])
def test_source_error_reader_rejects_unknown_boolean_values(value) -> None:
    with pytest.raises(ValueError, match="documented boolean string"):
        normalize_source_errors([_payload(retryable=value)])


def test_source_error_reader_preserves_refs_nested_metadata_and_datetime_offset() -> (
    None
):
    error = normalize_source_errors(
        [
            _payload(
                retryable="true",
                request_ref={"artifact_id": "request-ref"},
                response_ref={"artifact_id": "response-ref"},
                occurred_at="2026-07-19T09:30:00+08:00",
                metadata={"nested": {"attempt": 2}},
            )
        ]
    )[0]

    assert error.request_ref == {"artifact_id": "request-ref"}
    assert error.response_ref == {"artifact_id": "response-ref"}
    assert error.metadata["nested"] == {"attempt": 2}
    assert error.occurred_at.utcoffset() == timedelta(hours=8)
    assert error.to_dict()["occurred_at"] == "2026-07-19T09:30:00+08:00"


def test_source_error_reader_upgrades_legacy_naive_datetime_to_utc() -> None:
    error = normalize_source_errors([_payload(occurred_at="2026-07-19T01:30:00")])[0]

    assert error.occurred_at.utcoffset() == timedelta(0)
    assert error.to_dict()["occurred_at"] == "2026-07-19T01:30:00Z"
