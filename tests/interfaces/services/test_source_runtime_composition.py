from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

from business.foundation.models.source import SourceDefinition, SourceFetchPolicy
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import ProbeObservation
from business.layers.signal.tools import register_source_tools
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from infrastructure.external.sources import FeedConnector
from interfaces.services.source_mapping import to_infrastructure_source_definition
from interfaces.services.source_runtime import (
    SourceRuntimeProvider,
    build_source_runtime_composition,
)


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example RSS</title>
    <item>
      <title>Shared quota item</title>
      <link>https://example.com/items/1</link>
      <description>Shared Source runtime composition.</description>
    </item>
  </channel>
</rss>
"""


def test_connector_tool_and_health_probe_share_one_reservation_ledger() -> None:
    fetch_calls: list[str] = []
    probe_calls: list[str] = []
    source = _source()
    policy = SourceFetchPolicy(
        rate_limit_per_domain_per_minute=2,
        respect_robots=False,
        retry_times=0,
    )
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([source]),
        fetch_policy=policy,
        fetch_text=lambda url: fetch_calls.append(url) or RSS_FIXTURE,
        health_probe_fetcher=lambda candidate, _policy: (
            probe_calls.append(candidate.url)
            or ProbeObservation(status_code=200, content_type="text/xml", content_bytes=1)
        ),
    )

    connector_result = composition.source_service.fetch_source(
        source_id=source.source_id,
        force=True,
    )
    tool_result = _fetch_url_through_tool(composition, source, policy)
    health_result = composition.source_service.check_source_health(
        source_id=source.source_id,
        force=True,
    )

    assert connector_result.items
    assert tool_result.status == ToolStatus.SUCCEEDED
    assert fetch_calls == [source.url, source.url]
    assert probe_calls == []
    assert health_result.skipped_count == 1
    assert health_result.entries[0].skip_reason == "rate_limited"
    assert health_result.entries[0].health is not None
    assert health_result.entries[0].health.failure_count_24h == 0


def test_source_service_factory_retains_state_and_explicit_compositions_are_isolated() -> None:
    first = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
    )
    second = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
    )

    assert first.source_service_factory() is first.source_service
    assert first.source_service_factory() is first.source_service_factory()
    assert first.reservation_ledger is not second.reservation_ledger
    assert first.rate_limiter.ledger is first.reservation_ledger
    assert second.rate_limiter.ledger is second.reservation_ledger


def test_concurrent_connector_tool_and_health_reservations_share_one_bucket() -> None:
    fetch_calls: list[str] = []
    probe_calls: list[str] = []
    source = _source()
    policy = SourceFetchPolicy(
        rate_limit_per_domain_per_minute=1,
        respect_robots=False,
        retry_times=0,
    )
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([source]),
        fetch_policy=policy,
        fetch_text=lambda url: fetch_calls.append(url) or RSS_FIXTURE,
        health_probe_fetcher=lambda candidate, _policy: (
            probe_calls.append(candidate.url)
            or ProbeObservation(
                status_code=200,
                content_type="text/xml",
                content_bytes=1,
            )
        ),
    )
    start = Barrier(4)

    def fetch_connector():
        start.wait(timeout=2)
        return composition.source_service.fetch_source(
            source_id=source.source_id,
            force=True,
        )

    def fetch_tool():
        start.wait(timeout=2)
        return _fetch_url_through_tool(composition, source, policy)

    def probe_health():
        start.wait(timeout=2)
        return composition.source_service.check_source_health(
            source_id=source.source_id,
            force=True,
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        connector_future = executor.submit(fetch_connector)
        tool_future = executor.submit(fetch_tool)
        health_future = executor.submit(probe_health)
        start.wait(timeout=2)
        connector_result = connector_future.result(timeout=2)
        tool_result = tool_future.result(timeout=2)
        health_result = health_future.result(timeout=2)

    allowed = (
        bool(connector_result.items),
        tool_result.status == ToolStatus.SUCCEEDED,
        health_result.skipped_count == 0,
    )
    assert sum(allowed) == 1
    assert len(fetch_calls) + len(probe_calls) == 1
    assert health_result.entries[0].health is not None
    assert health_result.entries[0].health.failure_count_24h == 0


def test_explicit_standalone_connector_is_isolated_from_default_ledger() -> None:
    source = _source()
    policy = SourceFetchPolicy(
        rate_limit_per_domain_per_minute=1,
        respect_robots=False,
        retry_times=0,
    )
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([source]),
        fetch_policy=policy,
    )
    assert composition.reservation_ledger.reserve(
        source.url,
        limit_per_minute=1,
    ).allowed is True
    fetch_calls: list[str] = []
    standalone = FeedConnector(
        fetch_text=lambda url: fetch_calls.append(url) or RSS_FIXTURE,
        fetch_policy=composition.fetch_policy,
    )

    items, errors = standalone.fetch(to_infrastructure_source_definition(source))

    assert len(items) == 1
    assert errors == []
    assert fetch_calls == [source.url]


def test_source_runtime_provider_builds_once_under_concurrent_gets() -> None:
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
    )
    caller_barrier = Barrier(9)
    factory_started = Event()
    second_factory_call = Event()
    release_factory = Event()
    calls_lock = Lock()
    call_count = 0

    def factory():
        nonlocal call_count
        with calls_lock:
            call_count += 1
            if call_count > 1:
                second_factory_call.set()
        factory_started.set()
        assert release_factory.wait(timeout=2)
        return composition

    provider = SourceRuntimeProvider(factory)

    def resolve_composition():
        caller_barrier.wait(timeout=2)
        return provider.get()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(resolve_composition) for _ in range(8)]
        caller_barrier.wait(timeout=2)
        assert factory_started.wait(timeout=2)
        concurrent_duplicate = second_factory_call.wait(timeout=0.1)
        release_factory.set()
        resolved = [future.result(timeout=2) for future in futures]

    assert concurrent_duplicate is False
    assert call_count == 1
    assert all(value is composition for value in resolved)
    assert provider.source_service_factory() is composition.source_service


def _fetch_url_through_tool(composition, source, policy):
    registry = ToolRegistry()
    register_source_tools(
        registry,
        fetch_policy=policy,
        source_runtime=composition.source_tool_runtime,
        rate_limiter=composition.rate_limiter,
    )
    return ToolExecutor(registry).execute(
        ToolCall(
            tool_name="source.fetch_url",
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
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="source-1",
        name="Source",
        source_type="rss",
        url="https://example.com/feed.xml",
        topics=["ai"],
    )
