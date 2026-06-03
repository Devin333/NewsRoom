from __future__ import annotations

from business.foundation.models.source import SourceDefinition, SourceType
from business.layers.signal.source_processing.error_metadata import SOURCE_ERROR_RUNTIME_METADATA_KEY
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.layers.signal.source_tool_runtime import (
    SourceRateLimitDecision,
    source_rate_limited_error,
)


def test_source_rate_limited_error_writes_formal_runtime_and_policy_metadata() -> None:
    error = source_rate_limited_error(
        SourceDefinition(
            source_id="feed",
            name="Feed",
            source_type=SourceType.RSS,
            url="https://example.com/feed.xml",
        ),
        SourceRateLimitDecision(
            allowed=False,
            domain="example.com",
            limit_per_minute=2,
            retry_after_seconds=30,
        ),
        url="https://example.com/feed.xml",
    )

    assert error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "fetch",
        "retryable": True,
        "source_health_affecting": False,
    }
    assert error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
    }
    assert error.metadata["phase"] == "fetch"
    assert error.metadata["source_health_affecting"] is False
    assert error.metadata["domain"] == "example.com"
    assert error.metadata["limit_per_minute"] == 2
    assert error.metadata["retry_after_seconds"] == 30
