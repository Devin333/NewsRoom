from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from threading import Lock

from business.foundation.models.source import SourceDefinition, SourceFetchRequest
from business.foundation.registry.source_registry import SourceRegistry
from infrastructure.external.sources.models import SourceError, SourceType
from infrastructure.external.sources.protocol import (
    SourceFetchContext,
    SyncSourceConnectorAdapter,
)
from interfaces.services.source_service import SourceApplicationService


class _FailingRouter:
    def fetch(self, source, *, query=None, limit=None):
        return [], [
            SourceError(
                source_id=source.source_id,
                source_name=source.name,
                error_type="fetch_connection_error",
                error_message="offline",
                url=source.url,
                retryable=True,
                metadata={
                    "phase": "fetch",
                    "retryable": True,
                    "source_health_affecting": False,
                },
            )
        ]


class _RequestIds:
    def __init__(self) -> None:
        self._values = count(1)
        self._lock = Lock()

    def __call__(self) -> str:
        with self._lock:
            return f"source-request-{next(self._values)}"


class _SyncFailingConnector:
    def fetch(self, source, *, limit=None):
        return _FailingRouter().fetch(source, limit=limit)


class _AsyncFailingConnector:
    async def fetch(self, source, *, limit=None):
        await asyncio.sleep(0)
        return _FailingRouter().fetch(source, limit=limit)


def test_source_collection_attaches_request_id_without_changing_public_result_shape() -> None:
    service = _service([_source("source-1")])

    result = service.fetch_source(source_id="source-1", force=True)

    assert result.request_id == "source-request-1"
    assert result.errors[0].metadata["request_id"] == result.request_id
    assert "request_id" not in result.to_dict()


def test_concurrent_source_collection_keeps_request_context_isolated() -> None:
    sources = [_source(f"source-{index}") for index in range(8)]
    service = _service(sources)

    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        results = list(
            executor.map(
                lambda source: service.fetch_source(
                    source_id=source.source_id,
                    force=True,
                ),
                sources,
            )
        )

    request_ids = {result.request_id for result in results}
    assert len(request_ids) == len(sources)
    for result in results:
        assert result.errors[0].metadata["request_id"] == result.request_id


def test_target_connector_adapter_projects_request_scoped_errors_without_cache() -> None:
    source = _source("source-1")
    adapter = SyncSourceConnectorAdapter(_SyncFailingConnector(), source_type="rss")
    request = SourceFetchRequest(
        request_id="adapter-request-1",
        source_id=source.source_id,
        source_type=SourceType.RSS,
    )

    result = asyncio.run(adapter.fetch(source, request, SourceFetchContext(topic="ai")))

    [error] = result.metadata["source_errors"]
    assert error["metadata"]["request_id"] == request.request_id
    assert not hasattr(adapter, "errors_for")


def test_concurrent_target_connector_requests_keep_error_context_isolated() -> None:
    adapter = SyncSourceConnectorAdapter(
        _AsyncFailingConnector(),
        source_type="rss",
    )
    requests = [
        SourceFetchRequest(
            request_id=f"adapter-request-{index}",
            source_id=f"source-{index}",
            source_type=SourceType.RSS,
        )
        for index in range(8)
    ]

    async def fetch_all():
        return await asyncio.gather(
            *(
                adapter.fetch(
                    _source(request.source_id),
                    request,
                    SourceFetchContext(topic=f"topic-{index}"),
                )
                for index, request in enumerate(requests)
            )
        )

    results = asyncio.run(fetch_all())

    assert len(results) == len(requests)
    for request, result in zip(requests, results, strict=True):
        [error] = result.metadata["source_errors"]
        assert result.request_id == request.request_id
        assert error["metadata"]["request_id"] == request.request_id


def _service(sources: list[SourceDefinition]) -> SourceApplicationService:
    return SourceApplicationService(
        source_registry=SourceRegistry(sources),
        source_router=_FailingRouter(),
        request_id_factory=_RequestIds(),
    )


def _source(source_id: str) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        name=source_id,
        source_type="rss",
        url=f"https://example.com/{source_id}.xml",
        topics=["ai"],
    )
