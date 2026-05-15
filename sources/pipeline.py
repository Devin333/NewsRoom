from __future__ import annotations

import asyncio
import inspect
import json
import os
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from core.framework import RunResult, WorkflowRunner
from core.framework.llm import LLMClient, LLMRequest, build_openai_compatible_client_from_config
from core.framework.workflow import FunctionStepRegistry, ScopedDataBuffer
from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourceHealthStatus,
    SourcePipelineEvent,
    SourcePipelineMetrics,
    SourceType,
)
from evidence import EvidenceBundle
from sources import SourceConfigError, SourceRegistry, load_source_fetch_policy, load_source_registry
from sources.connectors import (
    ArxivConnector,
    DomainRateLimiter,
    FeedConnector,
    GithubConnector,
    HackerNewsConnector,
    HtmlConnector,
    LobstersConnector,
    ManualConnector,
    MediumConnector,
    RedditConnector,
    SourceFetchContext,
    SourceFetchPolicy,
    StackOverflowConnector,
    DevToConnector,
    effective_fetch_policy,
)
from sources.connectors.diagnostics import response_metadata_from_observations
from sources.health import BasicSourceHealthManager
from sources.errors import classify_source_exception
from sources.processing import (
    build_source_connector_dispatch_report,
    build_source_coverage_report,
    build_source_error_policy_report,
    build_source_fallback_report,
    build_source_health_report,
)
from workflows.daily_intelligence.spec import (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    build_daily_intelligence_workflow,
)
from workflows.daily_intelligence.artifact_publisher import (
    build_daily_intelligence_artifact_publishers,
)
from workflows.daily_intelligence.steps import (
    AllSourcesFailedError,
    build_evidence,
    deduplicate_sources,
    normalize_sources,
    quality_gate,
    rank_sources,
    require_sources,
    source_event as _source_event,
)


__all__ = [
    "AllSourcesFailedError",
    "DailyIntelligenceRunner",
    "PROFILE_LIVE",
    "PROFILE_LIVE_OFFLINE",
    "WORKFLOW_ID",
    "WORKFLOW_VERSION",
    "build_daily_intelligence_workflow",
    "build_default_source_fetch_policy",
    "build_default_source_registry",
]


class DailyIntelligenceRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        source_registry: SourceRegistry | None = None,
        feed_connector: FeedConnector | None = None,
        html_connector: HtmlConnector | None = None,
        manual_connector: ManualConnector | None = None,
        arxiv_connector: ArxivConnector | None = None,
        github_connector: GithubConnector | None = None,
        hackernews_connector: HackerNewsConnector | None = None,
        reddit_connector: RedditConnector | None = None,
        lobsters_connector: LobstersConnector | None = None,
        stackoverflow_connector: StackOverflowConnector | None = None,
        devto_connector: DevToConnector | None = None,
        medium_connector: MediumConnector | None = None,
        llm_client: LLMClient | None = None,
        source_health_manager: BasicSourceHealthManager | None = None,
        source_config_path: str | Path | None = None,
        source_rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.source_registry = source_registry or build_default_source_registry(
            source_config_path=source_config_path
        )
        default_fetch_policy = build_default_source_fetch_policy(
            source_config_path=source_config_path
        )
        default_rate_limiter = source_rate_limiter or DomainRateLimiter()
        self.feed_connector = feed_connector or FeedConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.html_connector = html_connector or HtmlConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.manual_connector = manual_connector or ManualConnector()
        self.arxiv_connector = arxiv_connector or ArxivConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.github_connector = github_connector or GithubConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.hackernews_connector = hackernews_connector or HackerNewsConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.reddit_connector = reddit_connector or RedditConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.lobsters_connector = lobsters_connector or LobstersConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.stackoverflow_connector = stackoverflow_connector or StackOverflowConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.devto_connector = devto_connector or DevToConnector(
            fetch_policy=default_fetch_policy,
            rate_limiter=default_rate_limiter,
        )
        self.medium_connector = medium_connector or MediumConnector(
            feed_connector=FeedConnector(
                fetch_policy=default_fetch_policy,
                rate_limiter=default_rate_limiter,
            )
        )
        self.llm_client = llm_client
        self.source_health_manager = source_health_manager or BasicSourceHealthManager()

    def run(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int = 3,
        run_id: str | None = None,
    ) -> RunResult:
        if profile not in {PROFILE_LIVE, PROFILE_LIVE_OFFLINE}:
            raise ValueError(f"unsupported daily intelligence profile: {profile}")
        registry = self._function_registry(profile)
        runner = WorkflowRunner(
            artifact_root=self.artifact_root,
            function_registry=registry,
            artifact_publishers=build_daily_intelligence_artifact_publishers(),
        )
        return runner.run(
            build_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )

    def _function_registry(self, profile: str) -> FunctionStepRegistry:
        registry = FunctionStepRegistry()
        registry.register("daily.collect_sources", lambda buffer: self._collect_sources(buffer, profile))
        registry.register("daily.require_sources", require_sources)
        registry.register("daily.normalize_sources", normalize_sources)
        registry.register("daily.deduplicate_sources", deduplicate_sources)
        registry.register("daily.rank_sources", rank_sources)
        registry.register("daily.build_evidence", build_evidence)
        registry.register("daily.draft_report", lambda buffer: self._draft_report(buffer, profile))
        registry.register("daily.quality_gate", quality_gate)
        return registry

    def _collect_sources(self, buffer: ScopedDataBuffer, profile: str) -> dict[str, Any]:
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
            fixture_source = _fixture_source()
            source_events.append(
                _source_event(
                    "source_fetch_started",
                    fixture_source.source_id,
                    source_type=fixture_source.source_type.value,
                    url=fixture_source.url,
                )
            )
            latency_start = perf_counter()
            source_events.append(
                _source_event(
                    "source_parse_started",
                    fixture_source.source_id,
                    source_type=fixture_source.source_type.value,
                )
            )
            raw_items = FeedConnector().parse(fixture_source, _fixture_feed(), limit=limit)
            fetch_latency_ms = _elapsed_ms(latency_start)
            request_id = "source-fetch-0001-fixture-ai"
            source_fetch_requests.append(
                _source_fetch_request(
                    fixture_source,
                    request_id=request_id,
                    request=request,
                    limit=limit,
                    profile=profile,
                )
            )
            source_fetch_results.append(
                _source_fetch_result(
                    fixture_source,
                    request_id=request_id,
                    success=True,
                    latency_ms=fetch_latency_ms,
                    items=raw_items,
                    errors=[],
                )
            )
            metrics.record_fetch_latency(fetch_latency_ms)
            metrics.sources_total = 1
            metrics.record_source_seen(fixture_source.source_type, fixture_source.reliability)
            metrics.sources_fetched = 1
            metrics.raw_items_count = len(raw_items)
            metrics.record_source_fetched(
                source_id=fixture_source.source_id,
                source_type=fixture_source.source_type,
                reliability=fixture_source.reliability,
                item_count=len(raw_items),
            )
            source_events.append(
                _source_event(
                    "source_fetch_succeeded",
                    fixture_source.source_id,
                    item_count=len(raw_items),
                    fetch_latency_ms=fetch_latency_ms,
                )
            )
            source_events.append(
                _source_event(
                    "source_parse_succeeded",
                    fixture_source.source_id,
                    item_count=len(raw_items),
                )
            )
            source_health = self.source_health_manager.record_success(
                fixture_source.source_id,
                latency_ms=fetch_latency_ms,
                source_name=fixture_source.name,
                url=fixture_source.url,
            )
            source_health_updates.append(source_health)
            source_events.append(
                _source_event(
                    "source_health_updated",
                    fixture_source.source_id,
                    status=source_health.status.value,
                    consecutive_failures=source_health.consecutive_failures,
                )
            )
            return {
                "raw_items": raw_items,
                "source_errors": source_errors,
                "skipped_sources": skipped_sources,
                "failed_sources": failed_sources,
                "source_fetch_requests": source_fetch_requests,
                "source_fetch_results": source_fetch_results,
                "source_health_updates": source_health_updates,
                "source_health_report": build_source_health_report(source_health_updates),
                "source_events": source_events,
                "source_pipeline_metrics": metrics,
                "source_connector_dispatch_report": build_source_connector_dispatch_report(
                    source_fetch_requests,
                    source_fetch_results,
                ),
                "source_error_policy_report": build_source_error_policy_report(source_errors),
                "source_fallback_report": build_source_fallback_report(
                    raw_items=raw_items,
                    source_errors=source_errors,
                    source_selection_report=self.source_registry.selection_report(
                        topic=request["topic"],
                        selected_sources=[fixture_source],
                    ),
                ),
                "source_selection_report": self.source_registry.selection_report(
                    topic=request["topic"],
                    selected_sources=[fixture_source],
                ),
                "source_coverage_report": build_source_coverage_report(
                    metrics,
                    source_errors=source_errors,
                    skipped_sources=skipped_sources,
                    failed_sources=failed_sources,
                ),
            }

        raw_items = []
        _ensure_live_source_registry(self.source_registry)
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
            request_id = _source_fetch_request_id(source_fetch_requests, source)
            fetch_request = _source_fetch_request(
                source,
                request_id=request_id,
                request=request,
                limit=remaining,
                profile=profile,
                fetch_policy=self._fetch_policy_for_source(source),
                connector_name=self._connector_name_for_source(source),
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
                    "cooldown_until": _dt(fetch_decision.cooldown_until),
                    "next_fetch_at": _dt(fetch_decision.next_fetch_at),
                    "last_success_at": _dt(health.last_success_at),
                }
                skipped_sources.append(
                    {key: value for key, value in skip_metadata.items() if value is not None}
                )
                source_fetch_results.append(
                    _skipped_source_fetch_result(
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
                        cooldown_until=_dt(fetch_decision.cooldown_until),
                        next_fetch_at=_dt(fetch_decision.next_fetch_at),
                        last_success_at=_dt(health.last_success_at),
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
                        cooldown_until=_dt(health.cooldown_until),
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
            items, errors, connector_fetch_result = self._fetch_source(
                source,
                request=request,
                fetch_request=fetch_request,
                profile=profile,
                limit=remaining,
            )
            errors = _with_error_request_id(errors, request_id)
            fetch_latency_ms = _elapsed_ms(latency_start)
            source_fetch_results.append(
                _final_source_fetch_result(
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
                    retryable = _error_metadata_bool(error, "retryable", default=True)
                    source_health_affecting = _error_metadata_bool(
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
                    if _error_phase(error) == "parse":
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
                                    cooldown_until=_dt(source_health.cooldown_until),
                                    consecutive_failures=source_health.consecutive_failures,
                                )
                            )
        metrics.raw_items_count = len(raw_items)
        if not raw_items:
            all_sources_error = SourceError(
                source_id="source_pipeline",
                source_name="Source Pipeline",
                error_type="all_sources_failed",
                error_message="all enabled sources failed or returned no valid items",
                retryable=False,
                metadata={
                    "retryable": False,
                    "source_health_affecting": False,
                    "workflow_blocking": True,
                    "sources_total": metrics.sources_total,
                    "sources_failed": metrics.sources_failed,
                    "sources_skipped": metrics.sources_skipped,
                },
            )
            source_errors.append(all_sources_error)
            failed_sources.append(all_sources_error.to_dict())
            metrics.record_error(all_sources_error)
            source_events.append(
                _source_event(
                    "source_fetch_failed",
                    error_type="all_sources_failed",
                    retryable=False,
                    sources_total=metrics.sources_total,
                    sources_failed=metrics.sources_failed,
                    sources_skipped=metrics.sources_skipped,
                )
            )
        return {
            "raw_items": raw_items,
            "source_errors": source_errors,
            "skipped_sources": skipped_sources,
            "failed_sources": failed_sources,
            "source_fetch_requests": source_fetch_requests,
            "source_fetch_results": source_fetch_results,
            "source_health_updates": source_health_updates,
            "source_health_report": build_source_health_report(source_health_updates),
            "source_events": source_events,
            "source_pipeline_metrics": metrics,
            "source_connector_dispatch_report": build_source_connector_dispatch_report(
                source_fetch_requests,
                source_fetch_results,
            ),
            "source_error_policy_report": build_source_error_policy_report(source_errors),
            "source_fallback_report": build_source_fallback_report(
                raw_items=raw_items,
                source_errors=source_errors,
                source_selection_report=source_selection_report,
            ),
            "source_selection_report": source_selection_report,
            "source_coverage_report": build_source_coverage_report(
                metrics,
                source_errors=source_errors,
                skipped_sources=skipped_sources,
                failed_sources=failed_sources,
            ),
        }

    def _fetch_source(
        self,
        source: SourceDefinition,
        *,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
        limit: int,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
        registered_result = self._fetch_with_registered_connector(
            source,
            request=request,
            fetch_request=fetch_request,
            profile=profile,
        )
        if registered_result is not None:
            return registered_result
        if source.source_type in {SourceType.RSS, SourceType.ATOM}:
            items, errors = self.feed_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.OFFICIAL_BLOG:
            items, errors = self._fetch_official_blog(source, limit=limit)
            return items, errors, None
        if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            items, errors = self.html_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.MANUAL:
            items, errors = self.manual_connector.fetch(source, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.ARXIV:
            query = str(source.metadata.get("query") or request["topic"])
            items, errors = self.arxiv_connector.fetch(source, query=query, limit=limit)
            return items, errors, None
        if source.source_type == SourceType.GITHUB:
            repository = source.metadata.get("repository")
            query = source.metadata.get("query") or request.get("topic")
            items, errors = self.github_connector.fetch(
                source,
                repository=str(repository) if repository is not None else None,
                query=str(query) if query is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.HACKERNEWS:
            story_list = source.metadata.get("story_list")
            items, errors = self.hackernews_connector.fetch(
                source,
                story_list=str(story_list) if story_list is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.REDDIT:
            subreddit = source.metadata.get("subreddit")
            listing = source.metadata.get("listing")
            items, errors = self.reddit_connector.fetch(
                source,
                subreddit=str(subreddit) if subreddit is not None else None,
                listing=str(listing) if listing is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.LOBSTERS:
            tag = source.metadata.get("tag")
            items, errors = self.lobsters_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.STACKOVERFLOW:
            tag = source.metadata.get("tagged") or source.metadata.get("tag")
            site = source.metadata.get("site")
            items, errors = self.stackoverflow_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                site=str(site) if site is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.DEVTO:
            tag = source.metadata.get("tag")
            items, errors = self.devto_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
        if source.source_type == SourceType.MEDIUM:
            tag = source.metadata.get("tag")
            items, errors = self.medium_connector.fetch(
                source,
                tag=str(tag) if tag is not None else None,
                limit=limit,
            )
            return items, errors, None
        return (
            [],
            [
                SourceError(
                    source_id=source.source_id,
                    source_name=source.name,
                    error_type="unsupported_source_type",
                    error_message=f"unsupported source type: {source.source_type.value}",
                    url=source.url,
                    retryable=False,
                    metadata={
                        "retryable": False,
                        "source_health_affecting": False,
                        "workflow_blocking": False,
                    },
                )
            ],
            None,
        )

    def _fetch_with_registered_connector(
        self,
        source: SourceDefinition,
        *,
        request: dict[str, Any],
        fetch_request: SourceFetchRequest,
        profile: str,
    ) -> tuple[list[Any], list[SourceError], SourceFetchResult | None] | None:
        connector = self._registered_connector_for_source(source)
        if connector is None:
            return None
        context = SourceFetchContext(
            profile=profile,
            topic=str(request.get("topic") or ""),
            metadata={
                "source_id": source.source_id,
                "limit": fetch_request.limit,
            },
        )
        try:
            if _is_protocol_connector(connector):
                return _invoke_protocol_connector(
                    connector,
                    source=source,
                    fetch_request=fetch_request,
                    context=context,
                )
            return _invoke_sync_connector(
                connector,
                source=source,
                fetch_request=fetch_request,
                context=context,
            )
        except Exception as exc:
            return [], [_registered_connector_error(source, exc)], None

    def _registered_connector_for_source(self, source: SourceDefinition) -> Any | None:
        try:
            return self.source_registry.get_connector(source.source_type)
        except KeyError:
            return None

    def _connector_name_for_source(self, source: SourceDefinition) -> str:
        connector = self._registered_connector_for_source(source)
        if connector is not None:
            return _connector_display_name(connector)
        return _source_connector_name(source)

    def _fetch_official_blog(
        self,
        source: SourceDefinition,
        *,
        limit: int,
    ) -> tuple[list[Any], list[SourceError]]:
        feed_items, feed_errors = self.feed_connector.fetch(source, limit=limit)
        if feed_items:
            return _with_official_blog_fetch_metadata(feed_items, mode="feed"), []

        html_items, html_errors = self.html_connector.fetch(source, limit=limit)
        if html_items:
            return (
                _with_official_blog_fetch_metadata(
                    html_items,
                    mode="html_fallback",
                    fallback_error_types=[error.error_type for error in feed_errors],
                ),
                [],
            )
        return [], [
            *_with_fallback_stage(feed_errors, "feed"),
            *_with_fallback_stage(html_errors, "html"),
        ]

    def _fetch_policy_for_source(self, source: SourceDefinition) -> SourceFetchPolicy | None:
        connector = self._connector_for_source(source)
        policy = getattr(connector, "fetch_policy", None)
        if policy is None and source.source_type == SourceType.MEDIUM:
            feed_connector = getattr(connector, "feed_connector", None)
            policy = getattr(feed_connector, "fetch_policy", None)
        if isinstance(policy, SourceFetchPolicy):
            return effective_fetch_policy(policy, source)
        return None

    def _connector_for_source(self, source: SourceDefinition) -> Any:
        registered_connector = self._registered_connector_for_source(source)
        if registered_connector is not None:
            return registered_connector
        if source.source_type in {SourceType.RSS, SourceType.ATOM, SourceType.OFFICIAL_BLOG}:
            return self.feed_connector
        if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
            return self.html_connector
        if source.source_type == SourceType.MANUAL:
            return self.manual_connector
        if source.source_type == SourceType.ARXIV:
            return self.arxiv_connector
        if source.source_type == SourceType.GITHUB:
            return self.github_connector
        if source.source_type == SourceType.HACKERNEWS:
            return self.hackernews_connector
        if source.source_type == SourceType.REDDIT:
            return self.reddit_connector
        if source.source_type == SourceType.LOBSTERS:
            return self.lobsters_connector
        if source.source_type == SourceType.STACKOVERFLOW:
            return self.stackoverflow_connector
        if source.source_type == SourceType.DEVTO:
            return self.devto_connector
        if source.source_type == SourceType.MEDIUM:
            return self.medium_connector
        return None

    def _draft_report(self, buffer: ScopedDataBuffer, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        evidence_bundle = buffer.read("evidence_bundle")
        source_errors = buffer.read("source_errors")
        source_metrics = buffer.read("source_pipeline_metrics")
        if profile == PROFILE_LIVE_OFFLINE:
            return {
                "report_draft": _with_source_notes(
                    _deterministic_report(request["topic"], evidence_bundle),
                    evidence_bundle,
                    source_errors,
                    source_metrics,
                )
            }

        llm_client = self.llm_client or build_openai_compatible_client_from_config(
            route_id="daily-intelligence-writer"
        )
        response = llm_client.complete(_report_request(request["topic"], evidence_bundle))
        report_draft = (
            _validate_report_payload(response.structured_output)
            if response.structured_output is not None
            else _parse_report_json(response.content)
        )
        report_draft = _with_source_notes(report_draft, evidence_bundle, source_errors, source_metrics)
        return {"report_draft": report_draft}


def build_default_source_registry(*, source_config_path: str | Path | None = None) -> SourceRegistry:
    configured_path, required = _default_source_config_path(source_config_path)
    if configured_path is not None:
        if not configured_path.exists():
            if required:
                raise SourceConfigError(f"source config file does not exist: {configured_path}")
        else:
            return load_source_registry(configured_path)
    return SourceRegistry(
        [
            SourceDefinition(
                source_id="openai-news",
                name="OpenAI News",
                source_type="rss",
                url="https://openai.com/news/rss.xml",
                reliability="high",
                authority_score=0.9,
                topics=["ai", "models"],
            ),
            SourceDefinition(
                source_id="google-ai-blog",
                name="Google AI Blog",
                source_type="rss",
                url="https://blog.google/technology/ai/rss/",
                reliability="high",
                authority_score=0.85,
                topics=["ai", "research"],
            ),
        ]
    )


def build_default_source_fetch_policy(
    *,
    source_config_path: str | Path | None = None,
) -> SourceFetchPolicy:
    configured_path, required = _default_source_config_path(source_config_path)
    if configured_path is not None:
        if not configured_path.exists():
            if required:
                raise SourceConfigError(f"source config file does not exist: {configured_path}")
        else:
            return load_source_fetch_policy(configured_path)
    return SourceFetchPolicy()


def _default_source_config_path(path: str | Path | None) -> tuple[Path | None, bool]:
    if path is not None:
        return Path(path), True
    env_path = os.getenv("NEWS_SOURCES_CONFIG")
    if env_path:
        return Path(env_path), True
    default_path = Path("configs/sources.yaml")
    if default_path.exists():
        return default_path, False
    return None, False


def _ensure_live_source_registry(source_registry: SourceRegistry) -> None:
    validation = source_registry.validate()
    if validation.is_valid:
        return
    issues = "; ".join(
        f"{issue.source_id}.{issue.field}: {issue.message}"
        for issue in validation.errors
    )
    raise SourceConfigError(f"live source registry validation failed: {issues}")


def _deterministic_report(topic: str, evidence_bundle: EvidenceBundle) -> dict[str, Any]:
    lead = evidence_bundle.items[0]
    return {
        "title": f"Daily Intelligence: {topic}",
        "sections": [
            {
                "title": "Summary",
                "content": f"{lead.title}: {lead.summary}",
                "sources": [lead.source_url],
            },
            {
                "title": "Source Notes",
                "content": f"Built from {len(evidence_bundle.items)} evidence item(s).",
                "sources": sorted(evidence_bundle.source_urls),
            },
        ],
    }


def _with_source_notes(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    source_errors: list[Any],
    source_metrics: SourcePipelineMetrics,
) -> dict[str, Any]:
    if not _needs_source_notes(source_errors, source_metrics):
        return report_draft
    sections = [dict(section) for section in report_draft.get("sections", [])]
    if any(str(section.get("title") or "").strip().casefold() == "source notes" for section in sections):
        return report_draft
    source_urls = sorted(evidence_bundle.source_urls)
    if not source_urls:
        return report_draft
    error_types = sorted(
        {
            error.error_type if hasattr(error, "error_type") else str(error.get("error_type", "unknown"))
            for error in source_errors
        }
    )
    content_parts = [
        (
            f"Source collection was partial: {source_metrics.sources_failed} source(s) failed "
            f"and {source_metrics.sources_skipped} source(s) were skipped."
        )
    ]
    if error_types:
        content_parts.append(f"Observed source error types: {', '.join(error_types)}.")
    sections.append(
        {
            "title": "Source Notes",
            "content": " ".join(content_parts),
            "sources": source_urls,
        }
    )
    updated = dict(report_draft)
    updated["sections"] = sections
    return updated


def _needs_source_notes(source_errors: list[Any], source_metrics: SourcePipelineMetrics) -> bool:
    if source_metrics.sources_failed > 0 or source_metrics.sources_skipped > 0:
        return True
    return bool(source_errors)


def _report_request(topic: str, evidence_bundle: EvidenceBundle) -> LLMRequest:
    evidence_payload = [item.to_dict() for item in evidence_bundle.items]
    user = (
        "Create a concise daily intelligence report as JSON with keys title and sections. "
        "Each section must include title, content, and sources. "
        "Only cite source URLs present in the evidence. "
        f"Topic: {topic}. Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )
    return LLMRequest(
        messages=[
            {"role": "system", "content": "You write source-grounded intelligence reports."},
            {"role": "user", "content": user},
        ],
        metadata={"profile": PROFILE_LIVE},
        response_format="json_object",
    )


def _parse_report_json(content: str) -> dict[str, Any]:
    clean = content.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    payload = json.loads(clean)
    return _validate_report_payload(payload)


def _validate_report_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM report output must be a JSON object")
    if "title" not in payload or "sections" not in payload:
        raise ValueError("LLM report output must include title and sections")
    return payload


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def _dt(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _source_fetch_request_id(existing: list[SourceFetchRequest], source: SourceDefinition) -> str:
    return f"source-fetch-{len(existing) + 1:04d}-{source.source_id}"


def _source_fetch_request(
    source: SourceDefinition,
    *,
    request_id: str,
    request: dict[str, Any],
    limit: int,
    profile: str,
    fetch_policy: SourceFetchPolicy | None = None,
    connector_name: str | None = None,
) -> SourceFetchRequest:
    query = None
    if source.source_type == SourceType.ARXIV:
        query = str(source.metadata.get("query") or request.get("topic") or "")
    user_agent = fetch_policy.user_agent if fetch_policy is not None else source.user_agent
    return SourceFetchRequest(
        request_id=request_id,
        source_id=source.source_id,
        source_type=source.source_type,
        url=source.url,
        query=query,
        timeout_seconds=fetch_policy.timeout_seconds if fetch_policy is not None else 15,
        max_bytes=fetch_policy.max_bytes if fetch_policy is not None else 1_000_000,
        max_redirects=fetch_policy.max_redirects if fetch_policy is not None else 3,
        user_agent=user_agent,
        headers={"User-Agent": user_agent} if user_agent else {},
        limit=limit,
        metadata={
            "profile": profile,
            "topic": request.get("topic"),
            "source_name": source.name,
            "reliability": source.reliability.value,
            "authority_score": source.authority_score,
            "fetch_interval_seconds": source.fetch_interval_seconds,
            "respect_robots": source.respect_robots,
            "connector_name": connector_name or _source_connector_name(source),
            **(_fetch_policy_metadata(fetch_policy) if fetch_policy is not None else {}),
        },
    )


def _fetch_policy_metadata(fetch_policy: SourceFetchPolicy) -> dict[str, Any]:
    return {
        "fetch_timeout_seconds": fetch_policy.timeout_seconds,
        "fetch_max_bytes": fetch_policy.max_bytes,
        "max_redirects": fetch_policy.max_redirects,
        "robots_policy": fetch_policy.respect_robots,
        "rate_limit_per_domain_per_minute": fetch_policy.rate_limit_per_domain_per_minute,
        "retry_times": fetch_policy.retry_times,
        "retry_on_status_codes": list(fetch_policy.retry_on_status_codes),
    }


def _source_connector_name(source: SourceDefinition) -> str:
    if source.source_type in {SourceType.RSS, SourceType.ATOM}:
        return "FeedConnector"
    if source.source_type == SourceType.OFFICIAL_BLOG:
        return "OfficialBlogFeedHtmlFallback"
    if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
        return "HtmlConnector"
    if source.source_type == SourceType.MANUAL:
        return "ManualConnector"
    if source.source_type == SourceType.ARXIV:
        return "ArxivConnector"
    if source.source_type == SourceType.GITHUB:
        return "GithubConnector"
    if source.source_type == SourceType.HACKERNEWS:
        return "HackerNewsConnector"
    if source.source_type == SourceType.REDDIT:
        return "RedditConnector"
    if source.source_type == SourceType.LOBSTERS:
        return "LobstersConnector"
    if source.source_type == SourceType.STACKOVERFLOW:
        return "StackOverflowConnector"
    if source.source_type == SourceType.DEVTO:
        return "DevToConnector"
    if source.source_type == SourceType.MEDIUM:
        return "MediumConnector"
    return "UnsupportedSourceConnector"


def _is_protocol_connector(connector: Any) -> bool:
    fetch = getattr(connector, "fetch", None)
    parse = getattr(connector, "parse", None)
    if not callable(fetch) or not callable(parse):
        return False
    parameters = _callable_parameters(fetch)
    return "request" in parameters and "context" in parameters


def _invoke_protocol_connector(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> tuple[list[Any], list[SourceError], SourceFetchResult]:
    fetch_result = _run_maybe_awaitable(connector.fetch(source, fetch_request, context))
    if not isinstance(fetch_result, SourceFetchResult):
        raise TypeError("registered source connector fetch must return SourceFetchResult")
    parsed_items = _run_maybe_awaitable(connector.parse(source, fetch_result, context))
    items = list(parsed_items or [])
    errors = _connector_errors(
        connector,
        source=source,
        fetch_request=fetch_request,
        fetch_result=fetch_result,
    )
    return items, errors, fetch_result


def _invoke_sync_connector(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
    fetch = getattr(connector, "fetch", None)
    if not callable(fetch):
        raise TypeError("registered source connector must expose a fetch method")
    kwargs = _registered_fetch_kwargs(fetch, fetch_request=fetch_request, context=context)
    result = _run_maybe_awaitable(fetch(source, **kwargs))
    if isinstance(result, SourceFetchResult):
        parse = getattr(connector, "parse", None)
        if not callable(parse):
            errors = _connector_errors(
                connector,
                source=source,
                fetch_request=fetch_request,
                fetch_result=result,
            )
            return [], errors, result
        parsed_items = _run_maybe_awaitable(parse(source, result, context))
        items = list(parsed_items or [])
        errors = _connector_errors(
            connector,
            source=source,
            fetch_request=fetch_request,
            fetch_result=result,
        )
        return items, errors, result
    try:
        items, errors = result
    except (TypeError, ValueError) as exc:
        raise TypeError("registered source connector fetch must return (items, errors)") from exc
    return list(items or []), list(errors or []), None


def _registered_fetch_kwargs(
    fetch: Any,
    *,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> dict[str, Any]:
    parameters = _callable_parameters(fetch)
    kwargs: dict[str, Any] = {}
    if "limit" in parameters and fetch_request.limit is not None:
        kwargs["limit"] = fetch_request.limit
    if "query" in parameters and fetch_request.query is not None:
        kwargs["query"] = fetch_request.query
    if "request" in parameters:
        kwargs["request"] = fetch_request
    if "context" in parameters:
        kwargs["context"] = context
    return kwargs


def _connector_errors(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    fetch_result: SourceFetchResult,
) -> list[SourceError]:
    errors_for = getattr(connector, "errors_for", None)
    if callable(errors_for):
        errors = _run_maybe_awaitable(errors_for(fetch_request.request_id))
        return list(errors or [])
    if fetch_result.error_type is None:
        return []
    return [
        SourceError(
            source_id=source.source_id,
            source_name=source.name,
            error_type=fetch_result.error_type,
            error_message=fetch_result.error_message or fetch_result.error_type,
            url=source.url,
            metadata={
                "phase": "fetch",
                "request_id": fetch_request.request_id,
                "connector_name": _connector_display_name(connector),
            },
        )
    ]


def _run_maybe_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError(
        "registered source connector returned an awaitable while an event loop is running"
    )


def _callable_parameters(value: Any) -> set[str]:
    try:
        return set(inspect.signature(value).parameters)
    except (TypeError, ValueError):
        return set()


def _connector_display_name(connector: Any) -> str:
    wrapped_connector = getattr(connector, "connector", None)
    if wrapped_connector is not None:
        return type(wrapped_connector).__name__
    return type(connector).__name__


def _registered_connector_error(source: SourceDefinition, exc: Exception) -> SourceError:
    classification = classify_source_exception(exc, phase="fetch")
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=classification.error_type,
        error_message=str(exc),
        url=source.url,
        retryable=classification.retryable,
        metadata={
            "phase": "fetch",
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "registered_connector": True,
            "original_exception_type": type(exc).__name__,
        },
    )


def _final_source_fetch_result(
    *,
    source: SourceDefinition,
    request_id: str,
    connector_fetch_result: SourceFetchResult | None,
    success: bool,
    latency_ms: float,
    items: list[Any],
    errors: list[SourceError],
) -> SourceFetchResult:
    fallback = _source_fetch_result(
        source,
        request_id=request_id,
        success=success,
        latency_ms=latency_ms,
        items=items,
        errors=errors,
    )
    if connector_fetch_result is None:
        return fallback
    metadata = dict(fallback.metadata)
    metadata.update(dict(connector_fetch_result.metadata))
    metadata["item_count"] = len(items)
    metadata["error_count"] = len(errors)
    first_error = errors[0] if errors else None
    return replace(
        connector_fetch_result,
        request_id=request_id,
        source_id=source.source_id,
        success=success,
        status_code=connector_fetch_result.status_code or fallback.status_code,
        content_type=connector_fetch_result.content_type or fallback.content_type,
        content_bytes=(
            connector_fetch_result.content_bytes
            if connector_fetch_result.content_bytes is not None
            else fallback.content_bytes
        ),
        latency_ms=(
            connector_fetch_result.latency_ms
            if connector_fetch_result.latency_ms is not None
            else fallback.latency_ms
        ),
        error_type=connector_fetch_result.error_type
        or (first_error.error_type if first_error else None),
        error_message=connector_fetch_result.error_message
        or (first_error.error_message if first_error else None),
        metadata=metadata,
    )


def _source_fetch_result(
    source: SourceDefinition,
    *,
    request_id: str,
    success: bool,
    latency_ms: float,
    items: list[Any],
    errors: list[SourceError],
    skipped: bool = False,
    skip_reason: str | None = None,
) -> SourceFetchResult:
    first_error = errors[0] if errors else None
    response_metadata = response_metadata_from_observations(items=items, errors=errors)
    metadata: dict[str, Any] = {
        "source_type": source.source_type.value,
        "url": source.url,
        "item_count": len(items),
        "error_count": len(errors),
    }
    if response_metadata is not None:
        metadata["response_url"] = response_metadata.get("url")
        metadata["response_headers"] = response_metadata.get("headers", {})
        metadata["fetch_response"] = response_metadata
    return SourceFetchResult(
        request_id=request_id,
        source_id=source.source_id,
        success=success,
        status_code=(
            response_metadata.get("status_code")
            if response_metadata is not None
            else None
        ),
        content_type=(
            response_metadata.get("content_type")
            if response_metadata is not None
            else None
        ),
        content_bytes=_raw_content_bytes(items),
        latency_ms=round(max(0.0, latency_ms)),
        error_type=first_error.error_type if first_error else None,
        error_message=first_error.error_message if first_error else None,
        skipped=skipped,
        skip_reason=skip_reason,
        metadata=metadata,
    )


def _skipped_source_fetch_result(
    source: SourceDefinition,
    *,
    request_id: str,
    skip_reason: str,
    metadata: dict[str, Any],
) -> SourceFetchResult:
    result = _source_fetch_result(
        source,
        request_id=request_id,
        success=False,
        latency_ms=0,
        items=[],
        errors=[],
        skipped=True,
        skip_reason=skip_reason,
    )
    result_metadata = dict(result.metadata)
    result_metadata["skip"] = {
        key: value for key, value in metadata.items() if value is not None
    }
    return replace(result, metadata=result_metadata)


def _with_error_request_id(errors: list[SourceError], request_id: str) -> list[SourceError]:
    linked_errors = []
    for error in errors:
        metadata = dict(error.metadata)
        metadata.setdefault("request_id", request_id)
        linked_errors.append(replace(error, metadata=metadata))
    return linked_errors


def _with_official_blog_fetch_metadata(
    items: list[Any],
    *,
    mode: str,
    fallback_error_types: list[str] | None = None,
) -> list[Any]:
    annotated = []
    for item in items:
        metadata = dict(getattr(item, "metadata", {}) or {})
        metadata["official_blog_fetch_mode"] = mode
        if fallback_error_types:
            metadata["official_blog_fallback"] = {
                "from": "feed",
                "to": "html",
                "feed_error_types": list(fallback_error_types),
            }
        annotated.append(replace(item, metadata=metadata))
    return annotated


def _with_fallback_stage(errors: list[SourceError], stage: str) -> list[SourceError]:
    staged = []
    for error in errors:
        metadata = dict(error.metadata)
        metadata["official_blog_fallback_stage"] = stage
        staged.append(replace(error, metadata=metadata))
    return staged


def _raw_content_bytes(items: list[Any]) -> int | None:
    total = 0
    found = False
    for item in items:
        raw_content = getattr(item, "raw_content", None)
        if raw_content is None:
            continue
        found = True
        total += len(str(raw_content).encode("utf-8"))
    return total if found else None


def _error_metadata_bool(error: SourceError, key: str, *, default: bool) -> bool:
    if key == "retryable" and error.retryable is not None:
        return error.retryable
    value = error.metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _error_phase(error: SourceError) -> str | None:
    value = error.metadata.get("phase")
    return str(value) if value is not None else None


def _fixture_source() -> SourceDefinition:
    return SourceDefinition(
        source_id="fixture-ai",
        name="Fixture AI Feed",
        source_type="rss",
        url="fixture://ai",
        reliability="high",
        topics=["ai", "chips", "policy"],
    )


def _fixture_feed() -> str:
    return """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Fixture AI</title>
    <item>
      <title>AI chip policy update</title>
      <link>https://example.com/ai-chip-policy</link>
      <description>Export controls and model supply chains remain central.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>New model evaluation benchmark</title>
      <link>https://example.com/model-benchmark</link>
      <description>Researchers published a deterministic evaluation benchmark.</description>
      <pubDate>Mon, 11 May 2026 01:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
