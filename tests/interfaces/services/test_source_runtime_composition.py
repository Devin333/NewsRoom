from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import json
from threading import Barrier, Event, Lock

from fastapi.testclient import TestClient

from business.foundation.models.source import SourceDefinition, SourceFetchPolicy
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager, ProbeObservation
from business.layers.signal.tools import register_source_tools
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from framework.workers import Task, WorkerExecutionScope
from infrastructure.external.sources import FeedConnector
from interfaces.services.source_mapping import to_infrastructure_source_definition
from interfaces.services.source_runtime import (
    SourceRuntimeProvider,
    build_source_runtime_composition,
)
from interfaces.services.tool_service import ToolApplicationService
from interfaces.services.worker_service import WorkerApplicationService


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

ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2608.00001v1</id>
    <updated>2026-08-20T00:00:00Z</updated>
    <published>2026-08-20T00:00:00Z</published>
    <title>Source composition quota</title>
    <summary>One provider must retain quota state across entry surfaces.</summary>
    <author><name>Example Author</name></author>
  </entry>
</feed>
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


def test_cli_parser_installs_one_lazy_source_runtime_provider() -> None:
    from interfaces.cli import news as news_cli

    parser = news_cli.build_parser()
    source_args = parser.parse_args(["sources", "list"])
    tool_args = parser.parse_args(["tools", "list"])

    assert isinstance(source_args.source_runtime_provider, SourceRuntimeProvider)
    assert tool_args.source_runtime_provider is source_args.source_runtime_provider


def test_api_default_source_runtime_retains_quota_and_denies_before_network(
    monkeypatch,
) -> None:
    api_app = import_module("interfaces.api.app")
    composition, fetch_calls = _arxiv_composition()
    provider = SourceRuntimeProvider(lambda: composition)
    monkeypatch.setattr(api_app, "default_source_runtime_provider", lambda: provider)
    monkeypatch.setattr(
        "interfaces.services.paper_rag_factory.preload_reranker",
        lambda: None,
    )

    with TestClient(api_app.create_app(audit_emitter_factory=None)) as client:
        first = client.post(
            "/api/v1/sources/arxiv/fetch",
            json={"query": "id:2608.00001", "limit": 1},
        )
        _clear_source_fetch_schedule(composition, "arxiv")
        second = client.post(
            "/api/v1/sources/arxiv/fetch",
            json={"query": "id:2608.00001", "limit": 1},
        )

    assert first.status_code == 200
    assert first.json()["data"]["item_count"] == 1
    assert second.status_code == 200
    _assert_rate_limited(second.json()["data"])
    assert len(fetch_calls) == 1


def test_mcp_source_runtime_retains_quota_and_denies_before_network() -> None:
    from interfaces.services.mcp_service import MCPApplicationService

    composition, fetch_calls = _arxiv_composition()
    service = MCPApplicationService(
        source_runtime_provider=SourceRuntimeProvider(lambda: composition)
    )

    first = service.call_tool(
        "news.source.arxiv.fetch",
        {"query": "id:2608.00001", "limit": 1},
    )
    _clear_source_fetch_schedule(composition, "arxiv")
    second = service.call_tool(
        "news.source.arxiv.fetch",
        {"query": "id:2608.00001", "limit": 1},
    )

    assert first.success is True
    assert first.data is not None
    assert first.data["item_count"] == 1
    assert second.success is True
    assert second.data is not None
    _assert_rate_limited(second.data)
    assert len(fetch_calls) == 1


def test_cli_source_runtime_retains_quota_and_denies_before_network(
    monkeypatch,
    capsys,
) -> None:
    from interfaces.cli import news as news_cli

    composition, fetch_calls = _arxiv_composition()
    provider = SourceRuntimeProvider(lambda: composition)
    monkeypatch.setattr(news_cli, "build_source_runtime_provider", lambda: provider)
    parser = news_cli.build_parser()
    args = parser.parse_args(
        ["sources", "arxiv", "--query", "id:2608.00001", "--limit", "1", "--json"]
    )

    assert args.handler(args) == 0
    _clear_source_fetch_schedule(composition, "arxiv")
    assert args.handler(args) == 1

    payloads = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert payloads[0]["item_count"] == 1
    _assert_rate_limited(payloads[1])
    assert len(fetch_calls) == 1


def test_worker_source_health_uses_provider_ledger_before_probe() -> None:
    source = _source()
    fetch_calls: list[str] = []
    probe_calls: list[str] = []
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([source]),
        fetch_policy=SourceFetchPolicy(
            rate_limit_per_domain_per_minute=1,
            respect_robots=False,
            retry_times=0,
        ),
        fetch_text=lambda url: fetch_calls.append(url) or RSS_FIXTURE,
        health_manager=BasicSourceHealthManager(),
        health_probe_fetcher=lambda candidate, _policy: (
            probe_calls.append(candidate.url)
            or ProbeObservation(status_code=200, content_type="text/xml", content_bytes=1)
        ),
    )
    provider = SourceRuntimeProvider(lambda: composition)
    service = WorkerApplicationService(
        queue=object(),
        source_runtime_provider=provider,
    )
    handler = service.handlers["source_health_check"]

    fetched = composition.source_service.fetch_source(source_id=source.source_id, force=True)
    result = handler.handle(
        Task(
            task_type="source_health_check",
            queue_name="news:queue:sources",
            payload={"source_id": source.source_id, "force": True},
            execution_scope=WorkerExecutionScope.STANDALONE,
        )
    )

    assert fetched.items
    assert handler.source_service is composition.source_service
    assert result.output["skipped_count"] == 1
    assert result.output["entries"][0]["skip_reason"] == "rate_limited"
    assert fetch_calls == [source.url]
    assert probe_calls == []


def test_tool_application_service_builds_source_registry_from_provider(
    monkeypatch,
) -> None:
    from interfaces.services import tool_service as tool_service_module

    composition, _ = _arxiv_composition()
    captured: dict[str, object] = {}

    def build_registry(**kwargs):
        captured.update(kwargs)
        return ToolRegistry()

    monkeypatch.setattr(
        tool_service_module,
        "build_business_tool_registry",
        build_registry,
    )
    service = ToolApplicationService(
        source_runtime_provider=SourceRuntimeProvider(lambda: composition)
    )

    service.list_tools()

    assert captured["source_registry"] is composition.source_registry
    assert captured["source_fetch_policy"] is composition.business_fetch_policy
    assert captured["source_tool_runtime"] is composition.source_tool_runtime
    assert captured["source_rate_limiter"] is composition.rate_limiter
    assert captured["source_health_manager"] is composition.health_manager


def test_mcp_default_research_factory_receives_the_mcp_source_provider(
    monkeypatch,
) -> None:
    from interfaces.composition import research as research_composition
    from interfaces.services.mcp_service import MCPApplicationService

    captured: list[object] = []

    def build_research_application_service(*, source_runtime_provider):
        captured.append(source_runtime_provider)
        return object()

    monkeypatch.setattr(
        research_composition,
        "build_research_application_service",
        build_research_application_service,
    )

    service = MCPApplicationService()
    first = service.research_service_factory()
    second = service.research_service_factory()

    assert service._source_runtime_provider is not None
    assert first is second
    assert captured == [service._source_runtime_provider]


def test_mcp_default_worker_factory_receives_the_mcp_source_provider(monkeypatch) -> None:
    from interfaces.services import worker_service
    from interfaces.services.mcp_service import MCPApplicationService

    captured: list[object] = []

    class _FakeWorkerService:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs["source_runtime_provider"])

    monkeypatch.setattr(worker_service, "WorkerApplicationService", _FakeWorkerService)
    service = MCPApplicationService()

    worker = service.worker_service_factory()

    assert isinstance(worker, _FakeWorkerService)
    assert captured == [service._source_runtime_provider]


def test_mcp_accepts_an_explicit_source_runtime_provider(monkeypatch) -> None:
    from interfaces.composition import research as research_composition
    from interfaces.services.mcp_service import MCPApplicationService

    provider = SourceRuntimeProvider(
        lambda: build_source_runtime_composition(source_registry=SourceRegistry([]))
    )
    captured: list[object] = []

    def build_research_application_service(*, source_runtime_provider):
        captured.append(source_runtime_provider)
        return object()

    monkeypatch.setattr(
        research_composition,
        "build_research_application_service",
        build_research_application_service,
    )
    service = MCPApplicationService(source_runtime_provider=provider)

    assert service._source_runtime_provider is provider
    assert service.research_service_factory() is service.research_service_factory()
    assert captured == [provider]


def test_mcp_rejects_conflicting_source_runtime_dependencies() -> None:
    from interfaces.services.mcp_service import MCPApplicationService

    provider = SourceRuntimeProvider(
        lambda: build_source_runtime_composition(source_registry=SourceRegistry([]))
    )

    try:
        MCPApplicationService(
            source_runtime_provider=provider,
            source_service_factory=lambda: object(),
        )
    except ValueError as exc:
        assert str(exc) == (
            "source_runtime_provider and source_service_factory are mutually exclusive"
        )
    else:
        raise AssertionError("MCPApplicationService accepted conflicting Source dependencies")


class _ApiSourceRuntimeProvider:
    def source_service_factory(self):
        return object()


def _arxiv_composition():
    fetch_calls: list[str] = []
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=SourceFetchPolicy(
            rate_limit_per_domain_per_minute=1,
            respect_robots=False,
            retry_times=0,
        ),
        fetch_text=lambda url: fetch_calls.append(url) or ARXIV_FIXTURE,
        health_manager=BasicSourceHealthManager(),
    )
    return composition, fetch_calls


def _assert_rate_limited(payload: dict) -> None:
    assert payload["item_count"] == 0
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["error_type"] == "rate_limited"
    assert payload["errors"][0]["metadata"]["domain"] == "arxiv.org"


def _clear_source_fetch_schedule(composition, source_id: str) -> None:
    """Keep the test focused on the shared domain quota, not fetch interval state."""

    composition.health_manager._health.pop(source_id, None)
    composition.health_manager._events.pop(source_id, None)


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
