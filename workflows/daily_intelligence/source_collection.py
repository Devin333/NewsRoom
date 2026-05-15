from __future__ import annotations

from time import perf_counter
from typing import Any

from core.framework.workflow import ScopedDataBuffer
from domain.sources import (
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourceHealthStatus,
    SourcePipelineEvent,
    SourcePipelineMetrics,
)
from sources import SourceRegistry
from sources.health import BasicSourceHealthManager
from workflows.daily_intelligence.profiles import PROFILE_LIVE_OFFLINE
from workflows.daily_intelligence.source_collection_output import (
    build_source_collection_output,
    record_all_sources_failed,
)
from workflows.daily_intelligence.source_config import ensure_live_source_registry
from workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from workflows.daily_intelligence.source_fetch_records import (
    dt,
    elapsed_ms,
    error_metadata_bool,
    error_phase,
    final_source_fetch_result,
    skipped_source_fetch_result,
    source_fetch_request,
    source_fetch_request_id,
    with_error_request_id,
)
from workflows.daily_intelligence.source_offline_collection import collect_offline_sources
from workflows.daily_intelligence.source_processing import source_event as _source_event


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

    def collect_sources(self, buffer: ScopedDataBuffer, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        limit = int(request.get("source_limit", 3))
        source_errors: list[SourceError] = []
        skipped_sources: list[dict[str, Any]] = []
        failed_sources: list[dict[str, Any]] = []
        source_fetch_requests: list[SourceFetchRequest] = []
        source_fetch_results: list[SourceFetchResult] = []
        source_health_updates = []
        source_events: list[SourcePipelineEvent] = []
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
            fetch_request = source_fetch_request(
                source,
                request_id=request_id,
                request=request,
                limit=remaining,
                profile=profile,
                fetch_policy=self.source_dispatcher.fetch_policy_for_source(source),
                connector_name=self.source_dispatcher.connector_name_for_source(source),
            )
            source_fetch_requests.append(fetch_request)
            fetch_decision = self.source_health_manager.fetch_decision(
                source.source_id,
                source_name=source.name,
                url=source.url,
                min_interval_seconds=source.fetch_interval_seconds,
            )
            if not fetch_decision.should_fetch:
                health = fetch_decision.health
                skip_reason = fetch_decision.skip_reason or "skipped"
                skip_metadata = {
                    "source_id": source.source_id,
                    "source_name": source.name,
                    "url": source.url,
                    "reason": skip_reason,
                    "cooldown_until": dt(fetch_decision.cooldown_until),
                    "next_fetch_at": dt(fetch_decision.next_fetch_at),
                    "last_success_at": dt(health.last_success_at),
                }
                skipped_sources.append(
                    {key: value for key, value in skip_metadata.items() if value is not None}
                )
                source_fetch_results.append(
                    skipped_source_fetch_result(
                        source,
                        request_id=request_id,
                        skip_reason=skip_reason,
                        metadata=skip_metadata,
                    )
                )
                source_health_updates.append(health)
                source_events.append(
                    _source_event(
                        "source_fetch_skipped",
                        source.source_id,
                        reason=skip_reason,
                        cooldown_until=dt(fetch_decision.cooldown_until),
                        next_fetch_at=dt(fetch_decision.next_fetch_at),
                        last_success_at=dt(health.last_success_at),
                    )
                )
                source_events.append(
                    _source_event(
                        "source_health_updated",
                        source.source_id,
                        status=health.status.value,
                        consecutive_failures=health.consecutive_failures,
                    )
                )
                metrics.sources_skipped += 1
                metrics.record_source_skipped(source.source_type)
                continue
            is_probe = self.source_health_manager.should_probe(source.source_id)
            if is_probe:
                health = self.source_health_manager.get(
                    source.source_id,
                    source_name=source.name,
                    url=source.url,
                )
                source_events.append(
                    _source_event(
                        "source_probe_started",
                        source.source_id,
                        cooldown_until=dt(health.cooldown_until),
                        consecutive_failures=health.consecutive_failures,
                    )
                )
            source_events.append(
                _source_event(
                    "source_fetch_started",
                    source.source_id,
                    source_type=source.source_type.value,
                    url=source.url,
                )
            )
            source_events.append(
                _source_event(
                    "source_parse_started",
                    source.source_id,
                    source_type=source.source_type.value,
                )
            )
            latency_start = perf_counter()
            items, errors, connector_fetch_result = self.source_dispatcher.fetch_source(
                source,
                request=request,
                fetch_request=fetch_request,
                profile=profile,
                limit=remaining,
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
                source_events.append(
                    _source_event(
                        "source_fetch_succeeded",
                        source.source_id,
                        item_count=len(items),
                        fetch_latency_ms=fetch_latency_ms,
                    )
                )
                source_events.append(
                    _source_event(
                        "source_parse_succeeded",
                        source.source_id,
                        item_count=len(items),
                    )
                )
                source_health = self.source_health_manager.record_success(
                    source.source_id,
                    latency_ms=fetch_latency_ms,
                    source_name=source.name,
                    url=source.url,
                )
                source_health_updates.append(source_health)
                source_events.append(
                    _source_event(
                        "source_health_updated",
                        source.source_id,
                        status=source_health.status.value,
                        consecutive_failures=source_health.consecutive_failures,
                    )
                )
                if is_probe:
                    source_events.append(
                        _source_event(
                            "source_probe_succeeded",
                            source.source_id,
                            item_count=len(items),
                            fetch_latency_ms=fetch_latency_ms,
                            status=source_health.status.value,
                        )
                    )
            if errors:
                metrics.sources_failed += 1
                metrics.record_source_failed(source.source_type)
                source_errors.extend(errors)
                failed_sources.extend(error.to_dict() for error in errors)
                if is_probe:
                    source_events.append(
                        _source_event(
                            "source_probe_failed",
                            source.source_id,
                            error_type=errors[0].error_type,
                            error_count=len(errors),
                            fetch_latency_ms=fetch_latency_ms,
                    )
                )
                for error in errors:
                    retryable = error_metadata_bool(error, "retryable", default=True)
                    source_health_affecting = error_metadata_bool(
                        error,
                        "source_health_affecting",
                        default=True,
                    )
                    source_events.append(
                        _source_event(
                            "source_fetch_failed",
                            source.source_id,
                            error_type=error.error_type,
                            retryable=retryable,
                            source_health_affecting=source_health_affecting,
                            fetch_latency_ms=fetch_latency_ms,
                        )
                    )
                    if error_phase(error) == "parse":
                        source_events.append(
                            _source_event(
                                "source_parse_failed",
                                source.source_id,
                                error_type=error.error_type,
                                retryable=retryable,
                            )
                        )
                    metrics.record_error(error)
                    if source_health_affecting:
                        source_health = self.source_health_manager.record_failure(
                            source.source_id,
                            error,
                            latency_ms=fetch_latency_ms,
                            source_name=source.name,
                            url=source.url,
                        )
                        source_health_updates.append(source_health)
                        source_events.append(
                            _source_event(
                                "source_health_updated",
                                source.source_id,
                                status=source_health.status.value,
                                consecutive_failures=source_health.consecutive_failures,
                            )
                        )
                        if source_health.status == SourceHealthStatus.DOWN:
                            source_events.append(
                                _source_event(
                                    "source_cooldown_started",
                                    source.source_id,
                                    cooldown_until=dt(source_health.cooldown_until),
                                    consecutive_failures=source_health.consecutive_failures,
                                )
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

