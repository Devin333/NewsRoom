from __future__ import annotations

from datetime import datetime, timezone

from framework.workflow import DataBuffer
from business.foundation.models.source import (
    RawSourceItem,
    SourceDefinition,
    SourcePipelineMetrics,
    SourceReliability,
    SourceType,
)
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import (
    SourceDispatcher,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_execution import (
    DailySourceRecollectionExecutionPlan,
    DailySourceRecollectionExecutionTask,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_executor import (
    DailySourceRecollectionExecutor,
)


def test_recollect_sources_fetches_sources_from_execution_plan() -> None:
    source = SourceDefinition(
        source_id="official-blog",
        name="Official Blog",
        source_type=SourceType.MANUAL,
        url="https://example.com/blog",
        reliability=SourceReliability.HIGH,
        topics=["model launch"],
    )
    connector = _RegisteredConnector()
    registry = SourceRegistry([source], connectors={SourceType.MANUAL: connector})
    dispatcher = _dispatcher(registry)
    executor = DailySourceRecollectionExecutor(
        source_registry=registry,
        source_dispatcher=dispatcher,
        source_health_manager=BasicSourceHealthManager(),
    )
    plan = DailySourceRecollectionExecutionPlan(
        plan_id="daily-source-recollect-1-execution-plan",
        profile_id="daily-source-recollect-1",
        status="ready",
        reason="Need launch timing confirmation.",
        source_recollect_round=1,
        max_source_recollect_rounds=1,
        tasks=[
            DailySourceRecollectionExecutionTask(
                task_id="daily-source-recollect-1-task-01",
                query="model launch timing official announcement",
                reason="Need launch timing confirmation.",
                source_feedback_ids=["daily-agent-feedback-1"],
                recommendation_ids=[
                    "daily-agent-feedback-policy-source-recollect:daily.source_recollect"
                ],
            )
        ],
        task_count=1,
        query_count=1,
        source_feedback_ids=["daily-agent-feedback-1"],
        recommendation_ids=[
            "daily-agent-feedback-policy-source-recollect:daily.source_recollect"
        ],
    )

    output = executor.recollect_sources(
        DataBuffer(
            {
                "request": {"topic": "AI launches", "source_limit": 2},
                "source_recollection_execution_plan": plan,
                "raw_items": [],
                "source_errors": [],
                "source_fetch_requests": [],
                "source_fetch_results": [],
                "source_pipeline_metrics": SourcePipelineMetrics(),
            }
        ).scope(
            read_keys=["request", "source_recollection_execution_plan"],
            optional_read_keys=[
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
            write_keys=[],
        ),
        profile="agentic-offline",
    )

    assert connector.calls == [("official-blog", 2)]
    assert output["raw_items"][0].source_id == "official-blog"
    assert output["sources.raw_items"] == output["raw_items"]
    assert output["raw_items"][0].metadata["source_recollection_plan_id"] == plan.plan_id
    assert output["raw_items"][0].metadata["source_recollection_task_id"] == (
        "daily-source-recollect-1-task-01"
    )
    assert output["source_fetch_requests"][0].metadata["source_recollection_query"] == (
        "model launch timing official announcement"
    )
    assert output["source_fetch_results"][0].success is True
    assert output["source_pipeline_metrics"].raw_items_count == 1
    assert output["source_pipeline_metrics"].sources_fetched == 1
    assert output["source_selection_report"].selected_source_ids == ["official-blog"]
    assert output["source_events"][-1].event_type == "source_recollection_executed"
    report = output["source_recollection_execution_report"]
    assert output["sources.recollection_execution_report"] == report
    assert report.plan_id == plan.plan_id
    assert report.profile_id == plan.profile_id
    assert report.status == "succeeded"
    assert report.task_count == 1
    assert report.succeeded_task_count == 1
    assert report.partial_task_count == 0
    assert report.raw_item_count == 1
    assert report.error_count == 0
    assert report.fetch_request_count == 1
    assert report.fetch_result_count == 1
    assert report.tasks[0].status == "succeeded"
    assert report.tasks[0].selected_source_ids == ["official-blog"]
    assert report.tasks[0].fetch_request_ids == ["source-fetch-0001-official-blog"]
    assert report.tasks[0].fetch_result_ids == ["source-fetch-0001-official-blog"]
    assessment = output["source_recollection_quality_assessment"]
    assert output["sources.recollection_quality_assessment"] == assessment
    assert assessment.plan_id == plan.plan_id
    assert assessment.decision == "pass"
    assert assessment.route == "continue_source_pipeline"
    assert assessment.recommended_action == "continue_source_pipeline"
    assert assessment.failed_thresholds == []


def test_recollect_sources_outputs_skipped_execution_report_without_plan() -> None:
    source = SourceDefinition(
        source_id="official-blog",
        name="Official Blog",
        source_type=SourceType.MANUAL,
        url="https://example.com/blog",
        reliability=SourceReliability.HIGH,
        topics=["model launch"],
    )
    registry = SourceRegistry([source], connectors={SourceType.MANUAL: _RegisteredConnector()})
    executor = DailySourceRecollectionExecutor(
        source_registry=registry,
        source_dispatcher=_dispatcher(registry),
        source_health_manager=BasicSourceHealthManager(),
    )

    output = executor.recollect_sources(
        DataBuffer(
            {
                "request": {"topic": "AI launches", "source_limit": 2},
                "raw_items": [],
                "source_errors": [],
                "source_fetch_requests": [],
                "source_fetch_results": [],
                "source_pipeline_metrics": SourcePipelineMetrics(),
            }
        ).scope(
            read_keys=["request"],
            optional_read_keys=[
                "source_recollection_execution_plan",
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
            write_keys=[],
        ),
        profile="agentic-offline",
    )

    report = output["source_recollection_execution_report"]
    assert output["sources.recollection_execution_report"] == report
    assert report.status == "skipped"
    assert report.reason == "missing_or_empty_execution_plan"
    assert report.task_count == 0
    assert report.raw_item_count == 0
    assessment = output["source_recollection_quality_assessment"]
    assert output["sources.recollection_quality_assessment"] == assessment
    assert assessment.decision == "skipped"
    assert assessment.route == "continue_without_recollection"
    assert assessment.issues == ["missing_or_empty_execution_plan"]
    assert output["source_events"][-1].event_type == "source_recollection_skipped"


def _dispatcher(registry: SourceRegistry) -> SourceDispatcher:
    unused_connector = _UnusedConnector()
    return SourceDispatcher(
        source_registry=registry,
        feed_connector=unused_connector,
        html_connector=unused_connector,
        manual_connector=unused_connector,
        arxiv_connector=unused_connector,
        github_connector=unused_connector,
        hackernews_connector=unused_connector,
        reddit_connector=unused_connector,
        lobsters_connector=unused_connector,
        stackoverflow_connector=unused_connector,
        devto_connector=unused_connector,
        medium_connector=unused_connector,
    )


class _RegisteredConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def fetch(self, source: SourceDefinition, *, limit: int):
        self.calls.append((source.source_id, limit))
        return [
            RawSourceItem(
                source_item_id="official-blog-item-1",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Model launch timing confirmed",
                url="https://example.com/blog/model-launch",
                fetched_at=datetime.now(timezone.utc),
                summary="The official blog confirmed the model launch date.",
            )
        ], []


class _UnusedConnector:
    def fetch(self, *args, **kwargs):
        raise AssertionError("registered connector should handle this source")
