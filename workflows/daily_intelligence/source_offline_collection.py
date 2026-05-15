from __future__ import annotations

from time import perf_counter
from typing import Any

from domain.sources import SourceError, SourceFetchRequest, SourceFetchResult, SourcePipelineEvent, SourcePipelineMetrics
from sources import SourceRegistry
from sources.connectors import FeedConnector
from sources.health import BasicSourceHealthManager
from workflows.daily_intelligence.source_collection_output import build_source_collection_output
from workflows.daily_intelligence.source_fetch_records import elapsed_ms, source_fetch_request, source_fetch_result
from workflows.daily_intelligence.source_fixtures import fixture_feed, fixture_source
from workflows.daily_intelligence.source_processing import source_event as _source_event


def collect_offline_sources(
    *,
    request: dict[str, Any],
    limit: int,
    source_registry: SourceRegistry,
    source_health_manager: BasicSourceHealthManager,
) -> dict[str, Any]:
    source_errors: list[SourceError] = []
    skipped_sources: list[dict[str, Any]] = []
    failed_sources: list[dict[str, Any]] = []
    source_fetch_requests: list[SourceFetchRequest] = []
    source_fetch_results: list[SourceFetchResult] = []
    source_health_updates = []
    source_events: list[SourcePipelineEvent] = []
    metrics = SourcePipelineMetrics()

    fixture = fixture_source()
    source_events.append(
        _source_event(
            "source_fetch_started",
            fixture.source_id,
            source_type=fixture.source_type.value,
            url=fixture.url,
        )
    )
    latency_start = perf_counter()
    source_events.append(
        _source_event(
            "source_parse_started",
            fixture.source_id,
            source_type=fixture.source_type.value,
        )
    )
    raw_items = FeedConnector().parse(fixture, fixture_feed(), limit=limit)
    fetch_latency_ms = elapsed_ms(latency_start)
    request_id = "source-fetch-0001-fixture-ai"
    source_fetch_requests.append(
        source_fetch_request(
            fixture,
            request_id=request_id,
            request=request,
            limit=limit,
            profile=str(request.get("profile") or "live-offline"),
        )
    )
    source_fetch_results.append(
        source_fetch_result(
            fixture,
            request_id=request_id,
            success=True,
            latency_ms=fetch_latency_ms,
            items=raw_items,
            errors=[],
        )
    )
    metrics.record_fetch_latency(fetch_latency_ms)
    metrics.sources_total = 1
    metrics.record_source_seen(fixture.source_type, fixture.reliability)
    metrics.sources_fetched = 1
    metrics.raw_items_count = len(raw_items)
    metrics.record_source_fetched(
        source_id=fixture.source_id,
        source_type=fixture.source_type,
        reliability=fixture.reliability,
        item_count=len(raw_items),
    )
    source_events.append(
        _source_event(
            "source_fetch_succeeded",
            fixture.source_id,
            item_count=len(raw_items),
            fetch_latency_ms=fetch_latency_ms,
        )
    )
    source_events.append(
        _source_event(
            "source_parse_succeeded",
            fixture.source_id,
            item_count=len(raw_items),
        )
    )
    source_health = source_health_manager.record_success(
        fixture.source_id,
        latency_ms=fetch_latency_ms,
        source_name=fixture.name,
        url=fixture.url,
    )
    source_health_updates.append(source_health)
    source_events.append(
        _source_event(
            "source_health_updated",
            fixture.source_id,
            status=source_health.status.value,
            consecutive_failures=source_health.consecutive_failures,
        )
    )
    source_selection_report = source_registry.selection_report(
        topic=request["topic"],
        selected_sources=[fixture],
    )
    return build_source_collection_output(
        raw_items=raw_items,
        source_errors=source_errors,
        skipped_sources=skipped_sources,
        failed_sources=failed_sources,
        source_fetch_requests=source_fetch_requests,
        source_fetch_results=source_fetch_results,
        source_health_updates=source_health_updates,
        source_events=source_events,
        source_pipeline_metrics=metrics,
        source_selection_report=source_selection_report,
    )
