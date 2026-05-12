from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from core.framework import RunResult, WorkflowRunner
from core.framework.llm import LLMClient, LLMRequest, OpenAICompatibleClient, OpenAICompatibleConfig
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import FunctionStepRegistry, ScopedDataBuffer
from domain.reports import BlockedReport, FinalReport, render_markdown
from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourcePipelineEvent,
    SourcePipelineMetrics,
    SourceType,
)
from evidence import EvidenceBuilder, EvidenceBundle
from quality import (
    CitationChecker,
    EditorDecision,
    EditorGate,
    QualityEvent,
    QualityGateMetrics,
    QualityScorer,
    SupportMatrixBuilder,
)
from sources import SourceRegistry
from sources.connectors import (
    ArxivConnector,
    FeedConnector,
    GithubConnector,
    HtmlConnector,
    ManualConnector,
)
from sources.health import BasicSourceHealthManager
from sources.processing import deduplicate_with_result, normalize_items, rank_items

PROFILE_LIVE = "live"
PROFILE_LIVE_OFFLINE = "live-offline"
WORKFLOW_ID = "daily-intelligence-live"
WORKFLOW_VERSION = "0.1.0"


class AllSourcesFailedError(RuntimeError):
    pass


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
        llm_client: LLMClient | None = None,
        source_health_manager: BasicSourceHealthManager | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.source_registry = source_registry or build_default_source_registry()
        self.feed_connector = feed_connector or FeedConnector()
        self.html_connector = html_connector or HtmlConnector()
        self.manual_connector = manual_connector or ManualConnector()
        self.arxiv_connector = arxiv_connector or ArxivConnector()
        self.github_connector = github_connector or GithubConnector()
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
        runner = WorkflowRunner(artifact_root=self.artifact_root, function_registry=registry)
        return runner.run(
            build_daily_intelligence_workflow(profile),
            {"topic": topic, "source_limit": source_limit, "profile": profile},
            profile=profile,
            run_id=run_id,
        )

    def _function_registry(self, profile: str) -> FunctionStepRegistry:
        registry = FunctionStepRegistry()
        registry.register("daily.collect_sources", lambda buffer: self._collect_sources(buffer, profile))
        registry.register("daily.require_sources", _require_sources)
        registry.register("daily.normalize_sources", _normalize_sources)
        registry.register("daily.deduplicate_sources", _deduplicate_sources)
        registry.register("daily.rank_sources", _rank_sources)
        registry.register("daily.build_evidence", _build_evidence)
        registry.register("daily.draft_report", lambda buffer: self._draft_report(buffer, profile))
        registry.register("daily.quality_gate", _quality_gate)
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
                "source_events": source_events,
                "source_pipeline_metrics": metrics,
            }

        raw_items = []
        enabled_sources = self.source_registry.select_sources(topic=request["topic"])
        metrics.sources_total = len(enabled_sources)
        for source in enabled_sources:
            metrics.record_source_seen(source.source_type, source.reliability)
        for source in enabled_sources:
            remaining = max(0, limit - len(raw_items))
            if remaining == 0:
                break
            request_id = _source_fetch_request_id(source_fetch_requests, source)
            source_fetch_requests.append(
                _source_fetch_request(
                    source,
                    request_id=request_id,
                    request=request,
                    limit=remaining,
                    profile=profile,
                )
            )
            if self.source_health_manager.should_skip(source.source_id):
                health = self.source_health_manager.get(
                    source.source_id,
                    source_name=source.name,
                    url=source.url,
                )
                skipped_sources.append(
                    {
                        "source_id": source.source_id,
                        "source_name": source.name,
                        "url": source.url,
                        "reason": "cooldown",
                        "cooldown_until": (
                            health.cooldown_until.isoformat().replace("+00:00", "Z")
                            if health.cooldown_until
                            else None
                        ),
                    }
                )
                source_fetch_results.append(
                    _source_fetch_result(
                        source,
                        request_id=request_id,
                        success=False,
                        latency_ms=0,
                        items=[],
                        errors=[],
                        skipped=True,
                        skip_reason="cooldown",
                    )
                )
                source_health_updates.append(health)
                source_events.append(
                    _source_event(
                        "source_fetch_skipped",
                        source.source_id,
                        reason="cooldown",
                        cooldown_until=(
                            health.cooldown_until.isoformat().replace("+00:00", "Z")
                            if health.cooldown_until
                            else None
                        ),
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
            latency_start = perf_counter()
            items, errors = self._fetch_source(source, request=request, limit=remaining)
            fetch_latency_ms = _elapsed_ms(latency_start)
            source_fetch_results.append(
                _source_fetch_result(
                    source,
                    request_id=request_id,
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
            "source_events": source_events,
            "source_pipeline_metrics": metrics,
        }

    def _fetch_source(
        self,
        source: SourceDefinition,
        *,
        request: dict[str, Any],
        limit: int,
    ) -> tuple[list[Any], list[SourceError]]:
        if source.source_type in {SourceType.RSS, SourceType.ATOM}:
            return self.feed_connector.fetch(source, limit=limit)
        if source.source_type in {SourceType.HTML, SourceType.OFFICIAL_BLOG, SourceType.WEB_PAGE}:
            return self.html_connector.fetch(source, limit=limit)
        if source.source_type == SourceType.MANUAL:
            return self.manual_connector.fetch(source, limit=limit)
        if source.source_type == SourceType.ARXIV:
            query = str(source.metadata.get("query") or request["topic"])
            return self.arxiv_connector.fetch(source, query=query, limit=limit)
        if source.source_type == SourceType.GITHUB:
            repository = source.metadata.get("repository")
            return self.github_connector.fetch_releases(
                source,
                repository=str(repository) if repository is not None else None,
                limit=limit,
            )
        return [], [
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
        ]

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

        llm_client = self.llm_client or OpenAICompatibleClient(OpenAICompatibleConfig.dashscope_defaults())
        response = llm_client.complete(_report_request(request["topic"], evidence_bundle))
        report_draft = (
            _validate_report_payload(response.structured_output)
            if response.structured_output is not None
            else _parse_report_json(response.content)
        )
        report_draft = _with_source_notes(report_draft, evidence_bundle, source_errors, source_metrics)
        return {"report_draft": report_draft}


def build_daily_intelligence_workflow(profile: str) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Daily Intelligence Live",
        version=WORKFLOW_VERSION,
        description="Daily intelligence workflow for live and live-offline profiles.",
        start_step_id="collect_sources",
        terminal_step_ids=["quality_gate"],
        steps=[
            StepSpec(
                step_id="collect_sources",
                implementation="daily.collect_sources",
                read_keys=["request"],
                write_keys=[
                    "raw_items",
                    "source_errors",
                    "skipped_sources",
                    "failed_sources",
                    "source_fetch_requests",
                    "source_fetch_results",
                    "source_health_updates",
                    "source_events",
                    "source_pipeline_metrics",
                ],
                required_output_keys=[
                    "raw_items",
                    "source_errors",
                    "skipped_sources",
                    "failed_sources",
                    "source_fetch_requests",
                    "source_fetch_results",
                    "source_health_updates",
                    "source_events",
                    "source_pipeline_metrics",
                ],
            ),
            StepSpec(
                step_id="require_sources",
                implementation="daily.require_sources",
                read_keys=["raw_items", "source_errors"],
                write_keys=["source_collection_status"],
                required_output_keys=["source_collection_status"],
            ),
            StepSpec(
                step_id="normalize_sources",
                implementation="daily.normalize_sources",
                read_keys=["raw_items", "source_events", "source_pipeline_metrics"],
                write_keys=["normalized_items", "source_events", "source_pipeline_metrics"],
                required_output_keys=["normalized_items", "source_events", "source_pipeline_metrics"],
            ),
            StepSpec(
                step_id="deduplicate_sources",
                implementation="daily.deduplicate_sources",
                read_keys=["normalized_items", "source_events", "source_pipeline_metrics"],
                write_keys=[
                    "deduplicated_items",
                    "source_duplicate_groups",
                    "source_events",
                    "source_pipeline_metrics",
                ],
                required_output_keys=[
                    "deduplicated_items",
                    "source_duplicate_groups",
                    "source_events",
                    "source_pipeline_metrics",
                ],
            ),
            StepSpec(
                step_id="rank_sources",
                implementation="daily.rank_sources",
                read_keys=["deduplicated_items", "request", "source_events", "source_pipeline_metrics"],
                write_keys=["ranked_items", "source_events", "source_pipeline_metrics"],
                required_output_keys=["ranked_items", "source_events", "source_pipeline_metrics"],
            ),
            StepSpec(
                step_id="build_evidence",
                implementation="daily.build_evidence",
                read_keys=["ranked_items"],
                write_keys=["evidence_bundle", "evidence_scores", "quality_events"],
                required_output_keys=["evidence_bundle", "evidence_scores", "quality_events"],
            ),
            StepSpec(
                step_id="draft_report",
                implementation="daily.draft_report",
                read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
                write_keys=["report_draft"],
                required_output_keys=["report_draft"],
            ),
            StepSpec(
                step_id="quality_gate",
                implementation="daily.quality_gate",
                read_keys=["report_draft", "evidence_bundle", "quality_events"],
                write_keys=[
                    "citation_check_result",
                    "editor_review",
                    "support_matrix",
                    "report_quality_summary",
                    "quality_events",
                    "quality_gate_metrics",
                    "final_report",
                    "report_markdown",
                    "blocked_report",
                ],
                required_output_keys=[
                    "citation_check_result",
                    "editor_review",
                    "support_matrix",
                    "report_quality_summary",
                    "quality_events",
                    "quality_gate_metrics",
                ],
            ),
        ],
        edges=[
            EdgeSpec("collect-to-require", "collect_sources", "require_sources"),
            EdgeSpec("require-to-normalize", "require_sources", "normalize_sources"),
            EdgeSpec("normalize-to-dedupe", "normalize_sources", "deduplicate_sources"),
            EdgeSpec("dedupe-to-rank", "deduplicate_sources", "rank_sources"),
            EdgeSpec("rank-to-evidence", "rank_sources", "build_evidence"),
            EdgeSpec("evidence-to-draft", "build_evidence", "draft_report"),
            EdgeSpec("draft-to-quality", "draft_report", "quality_gate"),
        ],
        metadata={"profile": profile, "product_path": profile == PROFILE_LIVE},
    )


def build_default_source_registry() -> SourceRegistry:
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


def _require_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    if raw_items:
        return {"source_collection_status": "ready"}

    source_errors = buffer.read("source_errors")
    error_types = [
        error.error_type if hasattr(error, "error_type") else error.get("error_type", "unknown")
        for error in source_errors
    ]
    raise AllSourcesFailedError(
        "all_sources_failed: no source items collected from enabled sources "
        f"(errors: {', '.join(error_types)})"
    )


def _normalize_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    normalized_items = normalize_items(raw_items)
    source_events = list(buffer.read("source_events"))
    source_events.append(
        _source_event("source_normalized", input_count=len(raw_items), output_count=len(normalized_items))
    )
    metrics = buffer.read("source_pipeline_metrics")
    metrics.normalized_items_count = len(normalized_items)
    return {"normalized_items": normalized_items, "source_events": source_events, "source_pipeline_metrics": metrics}


def _deduplicate_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    normalized_items = buffer.read("normalized_items")
    dedup_result = deduplicate_with_result(normalized_items)
    deduplicated_items = dedup_result.kept_items
    source_duplicate_groups = [group.to_dict() for group in dedup_result.duplicate_groups]
    source_events = list(buffer.read("source_events"))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.deduplicated_items_count = len(deduplicated_items)
    metrics.duplicate_count = len(dedup_result.dropped_items)
    source_events.append(
        _source_event(
            "source_deduplicated",
            input_count=len(normalized_items),
            output_count=len(deduplicated_items),
            duplicate_count=metrics.duplicate_count,
            duplicate_group_count=len(source_duplicate_groups),
        )
    )
    return {
        "deduplicated_items": deduplicated_items,
        "source_duplicate_groups": source_duplicate_groups,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
    }


def _rank_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    request = buffer.read("request")
    deduplicated_items = buffer.read("deduplicated_items")
    ranked_items = rank_items(deduplicated_items, topic=request["topic"])
    source_events = list(buffer.read("source_events"))
    source_events.append(
        _source_event(
            "source_ranked",
            input_count=len(deduplicated_items),
            output_count=len(ranked_items),
            topic=request["topic"],
        )
    )
    metrics = buffer.read("source_pipeline_metrics")
    metrics.ranked_items_count = len(ranked_items)
    return {"ranked_items": ranked_items, "source_events": source_events, "source_pipeline_metrics": metrics}


def _build_evidence(buffer: ScopedDataBuffer) -> dict[str, Any]:
    build_result = EvidenceBuilder().build_with_scores(buffer.read("ranked_items"), bundle_id="daily")
    bundle = build_result.bundle
    if not bundle.items:
        raise RuntimeError("no valid evidence built from ranked sources")
    return {
        "evidence_bundle": bundle,
        "evidence_scores": build_result.evidence_scores,
        "quality_events": [
            _quality_event(
                "evidence_build_succeeded",
                evidence_items_count=len(bundle.items),
                evidence_scores_count=len(build_result.evidence_scores),
            )
        ],
    }


def _quality_gate(buffer: ScopedDataBuffer) -> dict[str, Any]:
    report_draft = buffer.read("report_draft")
    evidence_bundle = buffer.read("evidence_bundle")
    quality_events = list(buffer.read("quality_events"))
    quality_events.append(_quality_event("citation_check_started", evidence_items_count=len(evidence_bundle.items)))
    citation_check = CitationChecker().check(report_draft, evidence_bundle)
    quality_events.append(
        _quality_event(
            "citation_check_succeeded" if citation_check.passed else "citation_check_failed",
            unknown_urls_count=len(citation_check.unknown_urls),
            missing_section_sources_count=len(citation_check.missing_section_sources),
            citation_coverage_score=citation_check.citation_coverage_score,
        )
    )
    support_matrix = SupportMatrixBuilder().build(report_draft, evidence_bundle)
    quality_summary = QualityScorer().score(
        report=report_draft,
        citation_check=citation_check,
        support_matrix=support_matrix,
    )
    quality_events.append(_quality_event("editor_gate_started", quality_score=quality_summary.quality_score))
    review = EditorGate().review(citation_check, support_matrix, quality_summary)
    quality_events.append(
        _quality_event(
            "editor_gate_passed" if review.decision == EditorDecision.PASS else "editor_gate_blocked",
            decision=review.decision.value,
            quality_score=quality_summary.quality_score,
            reason_count=len(review.reasons),
        )
    )
    quality_gate_metrics = QualityGateMetrics(
        evidence_items_count=len(evidence_bundle.items),
        unsupported_urls_count=len(citation_check.unknown_urls),
        missing_section_sources_count=len(citation_check.missing_section_sources),
        unsupported_sections_count=len(support_matrix.unsupported_sections),
        blocked=review.decision != EditorDecision.PASS,
        decision=review.decision.value,
        citation_coverage_score=citation_check.citation_coverage_score,
        support_coverage=quality_summary.support_coverage,
        quality_score=quality_summary.quality_score,
    )
    outputs: dict[str, Any] = {
        "citation_check_result": citation_check,
        "editor_review": review,
        "support_matrix": support_matrix,
        "report_quality_summary": quality_summary,
        "quality_events": quality_events,
        "quality_gate_metrics": quality_gate_metrics,
    }
    if review.decision == EditorDecision.PASS:
        final_report = FinalReport(
            title=report_draft["title"],
            sections=report_draft["sections"],
            source_urls=sorted(evidence_bundle.source_urls),
            metadata={
                "evidence_bundle_id": evidence_bundle.bundle_id,
                "quality_score": quality_summary.quality_score,
            },
        )
        outputs["final_report"] = final_report
        outputs["report_markdown"] = render_markdown(final_report)
    else:
        outputs["blocked_report"] = BlockedReport(
            title=report_draft.get("title", "Blocked Daily Intelligence Report"),
            reasons=review.reasons,
            draft=report_draft,
            metadata={
                "citation_check_result": citation_check.to_dict(),
                "quality_score": quality_summary.quality_score,
            },
        )
    return outputs


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


def _source_event(event_type: str, source_id: str | None = None, **metadata: Any) -> SourcePipelineEvent:
    return SourcePipelineEvent(
        event_type=event_type,
        source_id=source_id,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _source_fetch_request_id(existing: list[SourceFetchRequest], source: SourceDefinition) -> str:
    return f"source-fetch-{len(existing) + 1:04d}-{source.source_id}"


def _source_fetch_request(
    source: SourceDefinition,
    *,
    request_id: str,
    request: dict[str, Any],
    limit: int,
    profile: str,
) -> SourceFetchRequest:
    query = None
    if source.source_type == SourceType.ARXIV:
        query = str(source.metadata.get("query") or request.get("topic") or "")
    return SourceFetchRequest(
        request_id=request_id,
        source_id=source.source_id,
        source_type=source.source_type,
        url=source.url,
        query=query,
        limit=limit,
        metadata={
            "profile": profile,
            "topic": request.get("topic"),
            "source_name": source.name,
            "reliability": source.reliability.value,
            "authority_score": source.authority_score,
        },
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
    return SourceFetchResult(
        request_id=request_id,
        source_id=source.source_id,
        success=success,
        content_bytes=_raw_content_bytes(items),
        latency_ms=round(max(0.0, latency_ms)),
        error_type=first_error.error_type if first_error else None,
        error_message=first_error.error_message if first_error else None,
        skipped=skipped,
        skip_reason=skip_reason,
        metadata={
            "source_type": source.source_type.value,
            "url": source.url,
            "item_count": len(items),
            "error_count": len(errors),
        },
    )


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


def _quality_event(event_type: str, **metadata: Any) -> QualityEvent:
    return QualityEvent(
        event_type=event_type,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


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
