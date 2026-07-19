from __future__ import annotations

from urllib.error import HTTPError

import pytest

from business.foundation.models.source import (
    SourceDefinition,
    SourceFetchPolicy as BusinessSourceFetchPolicy,
)
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager, SourceHealthChecker
from business.layers.signal.tools import register_source_tools
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from infrastructure.external.sources import FeedConnector
from interfaces.services.source_mapping import (
    to_infrastructure_fetch_policy,
    to_infrastructure_source_definition,
)
from interfaces.services.source_tool_runtime import InfrastructureSourceToolRuntime


@pytest.mark.parametrize(
    ("status_code", "retry_on_status_codes", "expected_retryable"),
    [
        (404, (404,), True),
        (503, (), False),
    ],
)
def test_effective_retry_decision_is_identical_across_connector_health_and_tool(
    status_code: int,
    retry_on_status_codes: tuple[int, ...],
    expected_retryable: bool,
) -> None:
    source = _source()
    policy = BusinessSourceFetchPolicy(
        respect_robots=False,
        retry_times=0,
        retry_on_status_codes=retry_on_status_codes,
    )
    fetch_text = _failing_fetch(status_code)

    _, connector_errors = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=to_infrastructure_fetch_policy(policy),
    ).fetch(to_infrastructure_source_definition(source))

    health_result = SourceHealthChecker(
        SourceRegistry([source]),
        BasicSourceHealthManager(),
        fetch_policy=policy,
        probe_fetcher=lambda _source, candidate_policy: InfrastructureSourceToolRuntime(
            fetch_text=fetch_text
        ).fetch_text(_source.url, candidate_policy),
    ).run()

    registry = ToolRegistry()
    register_source_tools(
        registry,
        source_registry=SourceRegistry([source]),
        fetch_policy=policy,
        source_runtime=InfrastructureSourceToolRuntime(fetch_text=fetch_text),
        health_manager=BasicSourceHealthManager(),
    )
    tool_result = ToolExecutor(registry).execute(
        ToolCall(
            tool_name="source.probe",
            arguments={
                "source": {
                    "source_id": source.source_id,
                    "name": source.name,
                    "source_type": source.source_type.value,
                    "url": source.url,
                    "topics": list(source.topics),
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.probe"]),
    )

    connector_error = connector_errors[0]
    health_error = health_result.entries[0].error
    tool_error = tool_result.result.output["error"]

    assert health_error is not None
    assert tool_result.status == ToolStatus.SUCCEEDED
    assert {
        connector_error.error_type,
        health_error.error_type,
        tool_error["error_type"],
    } == {"fetch_http_4xx" if status_code < 500 else "fetch_http_5xx"}
    assert connector_error.retryable is expected_retryable
    assert health_error.retryable is expected_retryable
    assert tool_error["retryable"] is expected_retryable
    for error in (connector_error.to_dict(), health_error.to_dict(), tool_error):
        assert error["metadata"]["retryable"] is expected_retryable
        assert error["metadata"]["source_health_affecting"] is True
        assert error["metadata"]["workflow_blocking"] is False
        assert error["metadata"]["operator_action_required"] is False
        assert error["metadata"]["attempts"] == 1


def _failing_fetch(status_code: int):
    def fetch(url: str) -> str:
        raise HTTPError(url, status_code, "fetch failed", hdrs=None, fp=None)

    return fetch


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="source-retry-parity",
        name="Retry parity source",
        source_type="rss",
        url="https://example.com/feed.xml",
        topics=["ai"],
    )
