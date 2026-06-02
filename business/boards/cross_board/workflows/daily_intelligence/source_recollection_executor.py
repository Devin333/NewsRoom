from __future__ import annotations

from dataclasses import replace
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
from business.foundation.models.source_error_normalization import normalize_source_errors
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.source_collection_output import (
    build_source_collection_output,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from business.boards.cross_board.workflows.daily_intelligence.source_event_recorder import SourceEventRecorder
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    elapsed_ms,
    error_metadata_bool,
    error_phase,
    final_source_fetch_result,
    skipped_source_fetch_result,
    source_fetch_request,
    source_fetch_request_id,
    with_error_request_id,
)
from business.boards.cross_board.workflows.daily_intelligence.source_health_flow import SourceHealthFlow
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionPlan,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionTask,
)
from business.boards.cross_board.workflows.daily_intelligence.source_processing import (
    source_event as _source_event,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_value,
    read_optional_buffer_list,
    read_optional_buffer_value,
)


class DailySourceRecollectionExecutor:
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

    def recollect_sources(
        self,
        buffer: StepScopedDataBufferView,
        profile: str,
    ) -> dict[str, Any]:
        request = dict(read_buffer_value(buffer, "request"))
        plan = _execution_plan(read_optional_buffer_value(buffer, "source_recollection_execution_plan"))
        previous_raw_items = read_optional_buffer_list(buffer, "raw_items")
        previous_source_errors = _source_errors(read_optional_buffer_list(buffer, "source_errors"))
        previous_skipped_sources = _dict_items(read_optional_buffer_list(buffer, "skipped_sources"))
        previous_failed_sources = _dict_items(read_optional_buffer_list(buffer, "failed_sources"))
        previous_fetch_requests = _fetch_requests(read_optional_buffer_list(buffer, "source_fetch_requests"))
        previous_fetch_results = _fetch_results(read_optional_buffer_list(buffer, "source_fetch_results"))
        previous_health_updates = read_optional_buffer_list(buffer, "source_health_updates")
        previous_source_events = _source_events(read_optional_buffer_list(buffer, "source_events"))
        metrics = _pipeline_metrics(read_optional_buffer_value(buffer, "source_pipeline_metrics"))
        if plan is None or not plan.tasks:
            return build_source_collection_output(
                raw_items=previous_raw_items,
                source_errors=previous_source_errors,
                skipped_sources=previous_skipped_sources,
                failed_sources=previous_failed_sources,
                source_fetch_requests=previous_fetch_requests,
                source_fetch_results=previous_fetch_results,
                source_health_updates=previous_health_updates,
                source_events=[
                    *previous_source_events,
                    _source_event("source_recollection_skipped", reason="missing_or_empty_execution_plan"),
                ],
                source_pipeline_metrics=metrics,
                source_selection_report=self.source_registry.selection_report(
                    topic=request.get("topic", ""),
                    selected_sources=[],
                    filters={"source_recollection": True},
                    matched_source_count=0,
                    fallback_used=False,
                ),
            )

        raw_items = list(previous_raw_items)
        source_errors = list(previous_source_errors)
        skipped_sources = list(previous_skipped_sources)
        failed_sources = list(previous_failed_sources)
        source_fetch_requests = list(previous_fetch_requests)
        source_fetch_results = list(previous_fetch_results)
        source_health_updates = list(previous_health_updates)
        source_events = list(previous_source_events)
        event_recorder = SourceEventRecorder(source_events)
        health_flow = SourceHealthFlow(
            health_manager=self.source_health_manager,
            events=event_recorder,
            health_updates=source_health_updates,
        )
        limit_per_task = _limit_per_task(request)
        selected_sources_by_id = {}
        matched_source_count = 0
        for task in plan.tasks:
            selected_sources, selection_report = self.source_registry.select_sources_with_report(
                topic=task.query,
                fallback_to_enabled=True,
            )
            matched_source_count += selection_report.matched_source_count
            for source in selected_sources:
                selected_sources_by_id.setdefault(source.source_id, source)
            remaining = max(0, limit_per_task - _task_item_count(raw_items, task))
            for source in selected_sources:
                if remaining <= 0:
                    break
                request_id = source_fetch_request_id(source_fetch_requests, source)
                fetch_request = source_fetch_request(
                    source,
                    request_id=request_id,
                    request={**request, "topic": task.query},
                    limit=remaining,
                    profile=profile,
                    fetch_policy=self.source_dispatcher.fetch_policy_for_source(source),
                    connector_name=self.source_dispatcher.connector_name_for_source(source),
                )
                fetch_request = _with_recollection_metadata(fetch_request, plan, task)
                source_fetch_requests.append(fetch_request)
                metrics.record_source_seen(source.source_type, source.reliability)
                skip_decision = health_flow.decide_fetch(source)
                if skip_decision.should_skip:
                    skip_reason = skip_decision.reason or "skipped"
                    skip_metadata = dict(skip_decision.metadata or {})
                    skip_metadata.update(_recollection_metadata(plan, task))
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
                    request={**request, "topic": task.query},
                    fetch_request=fetch_request,
                    profile=profile,
                    limit=remaining,
                )
                errors = with_error_request_id(errors, request_id)
                items = [_with_recollection_item_metadata(item, plan, task) for item in items]
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
                remaining = max(0, limit_per_task - _task_item_count(raw_items, task))
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
                    for error in errors:
                        retryable = error_metadata_bool(error, "retryable", default=True)
                        source_health_affecting = error_metadata_bool(
                            error,
                            "source_health_affecting",
                            default=True,
                        )
                        event_recorder.fetch_failed(
                            source,
                            error=error,
                            retryable=retryable,
                            source_health_affecting=source_health_affecting,
                            fetch_latency_ms=fetch_latency_ms,
                        )
                        if error_phase(error) == "parse":
                            event_recorder.parse_failed(source, error=error, retryable=retryable)
                        metrics.record_error(error)
                        if source_health_affecting:
                            health_flow.record_failure(
                                source,
                                error,
                                fetch_latency_ms=fetch_latency_ms,
                            )
        metrics.sources_total += len(selected_sources_by_id)
        metrics.raw_items_count = len(raw_items)
        source_events.append(
            _source_event(
                "source_recollection_executed",
                task_count=len(plan.tasks),
                raw_item_count=len(raw_items) - len(previous_raw_items),
                source_fetch_request_count=len(source_fetch_requests) - len(previous_fetch_requests),
            )
        )
        selected_sources = list(selected_sources_by_id.values())
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
            source_selection_report=self.source_registry.selection_report(
                topic=request.get("topic", ""),
                selected_sources=selected_sources,
                filters={"source_recollection": True, "plan_id": plan.plan_id},
                matched_source_count=matched_source_count,
                fallback_used=False,
            ),
        )


def _execution_plan(value: Any) -> DailySourceRecollectionExecutionPlan | None:
    if isinstance(value, DailySourceRecollectionExecutionPlan):
        return value
    if isinstance(value, dict):
        return DailySourceRecollectionExecutionPlan.model_validate(value)
    return None


def _with_recollection_metadata(
    fetch_request: SourceFetchRequest,
    plan: DailySourceRecollectionExecutionPlan,
    task: DailySourceRecollectionExecutionTask,
) -> SourceFetchRequest:
    metadata = dict(fetch_request.metadata)
    metadata.update(_recollection_metadata(plan, task))
    return replace(fetch_request, metadata=metadata)


def _with_recollection_item_metadata(
    item: Any,
    plan: DailySourceRecollectionExecutionPlan,
    task: DailySourceRecollectionExecutionTask,
) -> Any:
    metadata = dict(getattr(item, "metadata", {}) or {})
    metadata.update(_recollection_metadata(plan, task))
    if hasattr(item, "__dataclass_fields__"):
        return replace(item, metadata=metadata)
    if isinstance(item, dict):
        return {**item, "metadata": metadata}
    return item


def _recollection_metadata(
    plan: DailySourceRecollectionExecutionPlan,
    task: DailySourceRecollectionExecutionTask,
) -> dict[str, Any]:
    return {
        "source_recollection_plan_id": plan.plan_id,
        "source_recollection_profile_id": plan.profile_id,
        "source_recollection_task_id": task.task_id,
        "source_recollection_query": task.query,
    }


def _task_item_count(raw_items: list[Any], task: DailySourceRecollectionExecutionTask) -> int:
    return sum(
        1
        for item in raw_items
        if _item_metadata(item).get("source_recollection_task_id") == task.task_id
    )


def _item_metadata(item: Any) -> dict[str, Any]:
    metadata = getattr(item, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    if isinstance(item, dict):
        metadata = item.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    return {}


def _limit_per_task(request: dict[str, Any]) -> int:
    value = request.get("source_recollection_limit") or request.get("source_limit") or 3
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


def _source_errors(values: list[Any]) -> list[SourceError]:
    return normalize_source_errors(values, context="source recollection buffer errors")


def _fetch_requests(values: list[Any]) -> list[SourceFetchRequest]:
    return [value for value in values if isinstance(value, SourceFetchRequest)]


def _fetch_results(values: list[Any]) -> list[SourceFetchResult]:
    return [value for value in values if isinstance(value, SourceFetchResult)]


def _source_events(values: list[Any]) -> list[SourcePipelineEvent]:
    return [value for value in values if isinstance(value, SourcePipelineEvent)]


def _dict_items(values: list[Any]) -> list[dict[str, Any]]:
    return [dict(value) for value in values if isinstance(value, dict)]


def _pipeline_metrics(value: Any) -> SourcePipelineMetrics:
    return value if isinstance(value, SourcePipelineMetrics) else SourcePipelineMetrics()


__all__ = ["DailySourceRecollectionExecutor"]
