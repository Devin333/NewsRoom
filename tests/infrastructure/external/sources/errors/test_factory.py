from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from infrastructure.external.sources.errors import (
    SourceErrorContext,
    SourceErrorDiagnostics,
    build_source_error,
    source_error_from_exception,
)
from infrastructure.external.sources.fetch_policy import (
    SourceFetchPolicy,
    run_with_fetch_retries,
)
from infrastructure.external.sources.models import SourceDefinition, SourceType


@dataclass(frozen=True)
class _ArtifactRef:
    artifact_id: str

    def to_dict(self) -> dict[str, str]:
        return {"artifact_id": self.artifact_id}


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type=SourceType.RSS,
        url="https://example.com/feed.xml",
    )


def test_shared_source_error_factory_preserves_context_policy_and_diagnostics() -> None:
    occurred_at = datetime(2026, 7, 19, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    request_ref = _ArtifactRef("request-ref")
    response_ref = {"artifact_id": "response-ref"}

    error = build_source_error(
        _source(),
        "empty_feed",
        "feed contained no valid items",
        context=SourceErrorContext(
            phase="parse",
            request_id="request-1",
            request_ref=request_ref,
            response_ref=response_ref,
            occurred_at=occurred_at,
        ),
        retryable=False,
        source_health_affecting=False,
        diagnostics=SourceErrorDiagnostics(extra={"provider": "rss"}),
    )

    assert error.retryable is False
    assert error.request_ref is request_ref
    assert error.response_ref is response_ref
    assert error.occurred_at is occurred_at
    assert error.metadata == {
        "phase": "parse",
        "retryable": False,
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
        "request_id": "request-1",
        "provider": "rss",
    }
    assert error.to_dict()["request_ref"] == {"artifact_id": "request-ref"}


@pytest.mark.parametrize(
    "reserved_key",
    [
        "retryable",
        "source_health_affecting",
        "workflow_blocking",
        "operator_action_required",
        "request_id",
    ],
)
def test_shared_source_error_factory_rejects_reserved_diagnostics(
    reserved_key: str,
) -> None:
    with pytest.raises(ValueError, match="cannot override reserved metadata"):
        SourceErrorDiagnostics(extra={reserved_key: True})


def test_shared_source_error_factory_uses_effective_retry_decision() -> None:
    error = HTTPError("https://example.com", 404, "Not Found", hdrs=None, fp=None)
    policy = SourceFetchPolicy(retry_times=0, retry_on_status_codes=(404,))

    with pytest.raises(HTTPError) as raised:
        run_with_fetch_retries(lambda: (_ for _ in ()).throw(error), policy)

    source_error = source_error_from_exception(
        _source(),
        raised.value,
        context=SourceErrorContext(phase="fetch"),
    )

    assert source_error.error_type == "fetch_http_4xx"
    assert source_error.retryable is True
    assert source_error.metadata["retryable"] is True
    assert source_error.metadata["status_code"] == 404
    assert source_error.metadata["attempts"] == 1


def test_shared_source_error_context_requires_aware_occurrence_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceErrorContext(phase="fetch", occurred_at=datetime(2026, 7, 19, 1, 0))
