from __future__ import annotations

from time import perf_counter
from typing import Any

from framework.workflow import StepScopedDataBufferView
from business.foundation.models.source import (
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourcePipelineEvent,
    SourcePipelineMetrics,
)
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_LIVE_OFFLINE
from business.boards.cross_board.workflows.daily_intelligence.source_collection_output import (
    build_source_collection_output,
    record_all_sources_failed,
)
from business.boards.cross_board.workflows.daily_intelligence.source_config import ensure_live_source_registry
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from business.boards.cross_board.workflows.daily_intelligence.source_event_recorder import SourceEventRecorder
from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    elapsed_ms,
    final_source_fetch_result,
    skipped_source_fetch_result,
    source_fetch_request,
    source_fetch_request_id,
    with_error_request_id,
)
from business.boards.cross_board.workflows.daily_intelligence.source_error_handling import (
    SourceFetchErrorHandlingContext,
    SourceFetchErrorHandlingService,
)
from business.boards.cross_board.workflows.daily_intelligence.source_health_flow import SourceHealthFlow
from business.boards.cross_board.workflows.daily_intelligence.source_offline_collection import collect_offline_sources
from business.boards.cross_board.workflows.daily_intelligence.source_processing import source_event as _source_event


class DailySourceCollector:
    def __init__(
        self,
        *,
        source_registry: SourceRegistry,
        source_dispatcher: SourceDispatcher,
        source_health_manager: BasicSourceHealthManager,
    ) -> None:
        self.source_registry = source_registry
        self.source_dispatcher = source_dispatcher
        self.source_health_manager = source_health_manager

    def collect_sources(self, buffer: StepScopedDataBufferView, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        limit = int(request.get("source_limit", 3))
        source_errors: list[SourceError] = []
        skipped_sources: list[dict[str, Any]] = []
        failed_sources: list[dict[str, Any]] = []
        source_fetch_requests: list[SourceFetchRequest] = []
        source_fetch_results: list[SourceFetchResult] = []
        source_health_updates = []
        source_events: list[SourcePipelineEvent] = []
        event_recorder = SourceEventRecorder(source_events)
        error_handling_service = SourceFetchErrorHandlingService()
        health_flow = SourceHealthFlow(
            health_manager=self.source_health_manager,
            events=event_recorder,
            health_updates=source_health_updates,
        )
        metrics = SourcePipelineMetrics()
        if profile == PROFILE_LIVE_OFFLINE:
            return collect_offline_sources(
                request=request,
                limit=limit,
                source_registry=self.source_registry,
                source_health_manager=self.source_health_manager,
            )

        raw_items = []
        ensure_live_source_registry(self.source_registry)
        enabled_sources, source_selection_report = self.source_registry.select_sources_with_report(
            topic=request["topic"]
        )
        metrics.sources_total = len(enabled_sources)
        for source in enabled_sources:
            metrics.record_source_seen(source.source_type, source.reliability)
        for source in enabled_sources:
            remaining = max(0, limit - len(raw_items))
            if remaining == 0:
                break
            request_id = source_fetch_request_id(source_fetch_requests, source)
            connector_options = SourceConnectorRuntimeOptions.from_source(source, request=request)
            fetch_request = source_fetch_request(
                source,
                request_id=request_id,
                request=request,
                limit=remaining,
                profile=profile,
                fetch_policy=self.source_dispatcher.fetch_policy_for_source(source),
                connector_name=self.source_dispatcher.connector_name_for_source(source),
                connector_options=connector_options,
            )
            source_fetch_requests.append(fetch_request)
            skip_decision = health_flow.decide_fetch(source)
            if skip_decision.should_skip:
                skip_reason = skip_decision.reason or "skipped"
                skip_metadata = dict(skip_decision.metadata or {})
                skipped_sources.append(skip_metadata)
                source_fetch_results.append(
                    skipped_source_fetch_result(
                        source,
                        request_id=request_id,
                        skip_reason=skip_reason,
                        metadata=skip_metadata,
                    )
                )
                metrics.sources_skipped += 1
                metrics.record_source_skipped(source.source_type)
                continue
            is_probe = health_flow.probe_started(source)
            event_recorder.fetch_started(source)
            event_recorder.parse_started(source)
            latency_start = perf_counter()
            items, errors, connector_fetch_result = self.source_dispatcher.fetch_source(
                source,
                request=request,
                fetch_request=fetch_request,
                profile=profile,
                limit=remaining,
                connector_options=connector_options,
            )
            errors = with_error_request_id(errors, request_id)
            fetch_latency_ms = elapsed_ms(latency_start)
            source_fetch_results.append(
                final_source_fetch_result(
                    source=source,
                    request_id=request_id,
                    connector_fetch_result=connector_fetch_result,
                    success=bool(items),
                    latency_ms=fetch_latency_ms,
                    items=items,
                    errors=errors,
                )
            )
            metrics.record_fetch_latency(fetch_latency_ms)
            raw_items.extend(items)
            if items:
                metrics.sources_fetched += 1
                metrics.record_source_fetched(
                    source_id=source.source_id,
                    source_type=source.source_type,
                    reliability=source.reliability,
                    item_count=len(items),
                )
                event_recorder.fetch_succeeded(
                    source,
                    item_count=len(items),
                    fetch_latency_ms=fetch_latency_ms,
                )
                event_recorder.parse_succeeded(source, item_count=len(items))
                health_flow.record_success(
                    source,
                    fetch_latency_ms=fetch_latency_ms,
                    is_probe=is_probe,
                    item_count=len(items),
                )
            if errors:
                metrics.sources_failed += 1
                metrics.record_source_failed(source.source_type)
                source_errors.extend(errors)
                failed_sources.extend(error.to_dict() for error in errors)
                if is_probe:
                    event_recorder.probe_failed(
                        source,
                        error_type=errors[0].error_type,
                        error_count=len(errors),
                        fetch_latency_ms=fetch_latency_ms,
                    )
                error_handling_service.handle_errors(
                    errors,
                    SourceFetchErrorHandlingContext(
                        source=source,
                        fetch_latency_ms=fetch_latency_ms,
                        event_recorder=event_recorder,
                        health_flow=health_flow,
                        metrics=metrics,
                    ),
                )
        metrics.raw_items_count = len(raw_items)
        if not raw_items:
            record_all_sources_failed(
                source_errors=source_errors,
                failed_sources=failed_sources,
                source_events=source_events,
                source_pipeline_metrics=metrics,
                source_event=_source_event,
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

