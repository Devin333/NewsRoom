from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from framework.specs import WorkflowStatus
from framework.workflow import DataBuffer
from framework.workflow.runtime.timeout import workflow_timeout_budget
from business.foundation.models.source import RawSourceItem, SourceError, SourcePipelineMetrics, SourceType
from business.boards.cross_board.workflows.daily_intelligence.spec import (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    WORKFLOW_ID,
    build_daily_intelligence_workflow,
)
from business.boards.cross_board.workflows.daily_intelligence.source_evidence_steps import (
    build_source_and_evidence_steps,
)
from business.boards.cross_board.workflows.daily_intelligence.steps import (
    AllSourcesFailedError,
    build_evidence,
    deduplicate_sources,
    normalize_sources,
    quality_gate,
    rank_sources,
    require_sources,
)
from business.boards.cross_board.workflows.daily_intelligence import source_processing
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    SOURCE_ERROR_RUNTIME_METADATA_KEY,
)
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.boards.cross_board.workflows.daily_intelligence.workflow_runtime_policy import (
    DAILY_WORKFLOW_TIMEOUT_SECONDS,
)


def test_daily_intelligence_workflow_spec_is_valid_and_profile_aware() -> None:
    live = build_daily_intelligence_workflow(PROFILE_LIVE)
    offline = build_daily_intelligence_workflow(PROFILE_LIVE_OFFLINE)

    live.validate(request_keys=["request"])

    assert live.workflow_id == WORKFLOW_ID
    assert live.start_step_id == "collect_sources"
    assert live.terminal_step_ids == ["quality_gate"]
    assert [step.step_id for step in live.steps] == [
        "collect_sources",
        "require_sources",
        "normalize_sources",
        "deduplicate_sources",
        "rank_sources",
        "build_evidence",
        "draft_report",
        "quality_gate",
    ]
    assert _step_signatures(live.steps[:6]) == _step_signatures(
        build_source_and_evidence_steps()
    )
    assert [edge.target_step_id for edge in live.edges] == [
        "require_sources",
        "normalize_sources",
        "deduplicate_sources",
        "rank_sources",
        "build_evidence",
        "draft_report",
        "quality_gate",
    ]
    assert live.metadata["product_path"] is True
    assert offline.metadata["product_path"] is False
    draft_step = next(step for step in live.steps if step.step_id == "draft_report")
    quality_step = next(step for step in live.steps if step.step_id == "quality_gate")
    assert "historian_context" in draft_step.write_keys
    assert "historian_context" in quality_step.metadata["optional_read_keys"]
    assert "memory_query_repository" in quality_step.metadata["optional_read_keys"]


def test_daily_intelligence_workflow_declares_global_timeout_budget() -> None:
    workflow = build_daily_intelligence_workflow(PROFILE_LIVE)
    budget = workflow_timeout_budget(workflow, started_monotonic=10.0)

    assert workflow.policies.timeout_policy.timeout_seconds == DAILY_WORKFLOW_TIMEOUT_SECONDS
    assert budget is not None
    assert budget.timeout_seconds == DAILY_WORKFLOW_TIMEOUT_SECONDS
    assert budget.policy_source == "policies.timeout_policy.timeout_seconds"


def test_daily_source_and_quality_steps_declare_namespaced_alias_write_keys() -> None:
    workflow = build_daily_intelligence_workflow(PROFILE_LIVE)
    steps = {step.step_id: step for step in workflow.steps}

    assert "sources.errors" in steps["collect_sources"].write_keys
    assert "sources.normalized_items" in steps["normalize_sources"].write_keys
    assert "sources.deduplicated_items" in steps["deduplicate_sources"].write_keys
    assert "sources.ranked_items" in steps["rank_sources"].write_keys
    assert "evidence.bundle" in steps["build_evidence"].write_keys
    assert "report.draft" in steps["draft_report"].write_keys
    assert "quality.result" in steps["quality_gate"].write_keys
    assert "report.final" in steps["quality_gate"].write_keys


def test_daily_source_and_quality_steps_declare_namespaced_alias_read_keys() -> None:
    workflow = build_daily_intelligence_workflow(PROFILE_LIVE)
    steps = {step.step_id: step for step in workflow.steps}

    assert "sources.raw_items" in steps["require_sources"].read_keys
    assert "sources.normalized_items" in steps["deduplicate_sources"].read_keys
    assert "sources.ranked_items" in steps["build_evidence"].read_keys
    assert "evidence.bundle" in steps["draft_report"].read_keys
    assert "sources.errors" in steps["draft_report"].read_keys
    assert "report.draft" in steps["quality_gate"].read_keys
    assert "quality.events" in steps["quality_gate"].read_keys
    assert "memory.context" in steps["quality_gate"].metadata["optional_read_keys"]


def test_daily_source_evidence_steps_prefer_namespaced_read_keys() -> None:
    steps = {step.step_id: step for step in build_source_and_evidence_steps()}

    assert steps["require_sources"].read_keys == [
        "sources.raw_items",
        "raw_items",
        "sources.errors",
        "source_errors",
    ]
    assert steps["normalize_sources"].read_keys == [
        "sources.raw_items",
        "raw_items",
        "sources.errors",
        "source_errors",
        "sources.events",
        "source_events",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert steps["deduplicate_sources"].read_keys == [
        "sources.normalized_items",
        "normalized_items",
        "sources.errors",
        "source_errors",
        "sources.events",
        "source_events",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert steps["rank_sources"].read_keys == [
        "sources.deduplicated_items",
        "deduplicated_items",
        "request",
        "sources.errors",
        "source_errors",
        "sources.skipped",
        "skipped_sources",
        "sources.failed",
        "failed_sources",
        "sources.selection_report",
        "source_selection_report",
        "sources.events",
        "source_events",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert steps["build_evidence"].read_keys == [
        "sources.ranked_items",
        "ranked_items",
    ]


def test_require_sources_fails_with_source_error_summary() -> None:
    buffer = DataBuffer(
        {
            "raw_items": [],
            "source_errors": [
                SourceError(
                    source_id="feed",
                    error_type="fetch_timeout",
                    error_message="timed out",
                )
            ],
        }
    )

    with pytest.raises(AllSourcesFailedError, match="fetch_timeout"):
        require_sources(buffer.scope(read_keys=["raw_items", "source_errors"], write_keys=[]))


def test_require_sources_normalizes_source_error_mappings_for_summary() -> None:
    buffer = DataBuffer(
        {
            "raw_items": [],
            "source_errors": [
                {
                    "source_id": "feed",
                    "error_type": "fetch_timeout",
                    "error_message": "timed out",
                    "metadata": {"retryable": True},
                }
            ],
        }
    )

    with pytest.raises(AllSourcesFailedError, match="fetch_timeout"):
        require_sources(buffer.scope(read_keys=["raw_items", "source_errors"], write_keys=[]))


def test_normalize_sources_returns_typed_source_errors() -> None:
    buffer = _initial_source_buffer()
    buffer.write(
        "source_errors",
        [
            {
                "source_id": "feed",
                "source_name": "Feed",
                "error_type": "fetch_timeout",
                "error_message": "timed out",
                "metadata": {"retryable": True},
            }
        ],
    )

    output = normalize_sources(
        buffer.scope(
            read_keys=["raw_items", "source_errors", "source_events", "source_pipeline_metrics"],
            write_keys=[],
        )
    )

    assert all(isinstance(error, SourceError) for error in output["source_errors"])
    assert output["source_errors"][0].error_type == "fetch_timeout"


def test_normalize_sources_reads_namespaced_source_aliases() -> None:
    metrics = SourcePipelineMetrics(sources_total=1, sources_fetched=1, raw_items_count=1)
    buffer = DataBuffer(
        {
            "sources.raw_items": [_raw_item()],
            "sources.errors": [],
            "sources.events": [],
            "sources.pipeline_metrics": metrics,
        }
    )

    output = normalize_sources(
        buffer.scope(
            read_keys=[
                "sources.raw_items",
                "sources.errors",
                "sources.events",
                "sources.pipeline_metrics",
            ],
            write_keys=[],
        )
    )

    assert len(output["normalized_items"]) == 1
    assert output["source_pipeline_metrics"].normalized_items_count == 1


def test_daily_source_steps_build_ranked_items_and_reports() -> None:
    buffer = _initial_source_buffer()

    _apply(buffer, require_sources, ["raw_items", "source_errors"])
    _apply(
        buffer,
        normalize_sources,
        ["raw_items", "source_errors", "source_events", "source_pipeline_metrics"],
    )
    _apply(
        buffer,
        deduplicate_sources,
        ["normalized_items", "source_errors", "source_events", "source_pipeline_metrics"],
    )
    _apply(
        buffer,
        rank_sources,
        [
            "request",
            "deduplicated_items",
            "source_errors",
            "skipped_sources",
            "failed_sources",
            "source_selection_report",
            "source_events",
            "source_pipeline_metrics",
        ],
    )

    assert buffer.read("source_collection_status") == "ready"
    assert buffer.read("sources.collection_status") == "ready"
    assert len(buffer.read("normalized_items")) == 1
    assert len(buffer.read("deduplicated_items")) == 1
    assert len(buffer.read("ranked_items")) == 1
    assert buffer.read("sources.errors") == buffer.read("source_errors")
    assert buffer.read("sources.events") == buffer.read("source_events")
    assert buffer.read("sources.ranked_items") == buffer.read("ranked_items")
    assert buffer.read("source_coverage_report").coverage_status == "covered"
    assert buffer.read("source_quality_summary_report").item_count == 1
    assert buffer.read("source_traceability_report").traceability_status == "complete"
    assert [event.event_type for event in buffer.read("source_events")] == [
        "source_normalized",
        "source_deduplicated",
        "source_ranked",
    ]
    metrics = buffer.read("source_pipeline_metrics")
    assert metrics.normalized_items_count == 1
    assert metrics.deduplicated_items_count == 1
    assert metrics.ranked_items_count == 1


def test_deduplicate_sources_retains_normalized_items_when_dedup_fails(monkeypatch) -> None:
    buffer = _initial_source_buffer()
    _apply(buffer, normalize_sources, ["raw_items", "source_errors", "source_events", "source_pipeline_metrics"])
    normalized_items = list(buffer.read("normalized_items"))

    def fail_deduplicate(_items):
        raise RuntimeError("dedup engine failed")

    monkeypatch.setattr(source_processing, "deduplicate_with_result", fail_deduplicate)

    output = deduplicate_sources(
        buffer.scope(
            read_keys=["normalized_items", "source_errors", "source_events", "source_pipeline_metrics"],
            write_keys=[],
        )
    )

    assert output["deduplicated_items"] == normalized_items
    assert output["source_duplicate_groups"] == []
    [dedup_error] = [error for error in output["source_errors"] if error.metadata["phase"] == "dedup"]
    assert dedup_error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY]["phase"] == "dedup"
    assert dedup_error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY]["workflow_blocking"] is False
    assert any(event.event_type == "source_dedup_failed" for event in output["source_events"])
    assert output["source_pipeline_metrics"].deduplicated_items_count == len(normalized_items)


def test_rank_sources_wraps_deduplicated_items_when_ranker_fails(monkeypatch) -> None:
    buffer = _initial_source_buffer()
    _apply(buffer, normalize_sources, ["raw_items", "source_errors", "source_events", "source_pipeline_metrics"])
    _apply(
        buffer,
        deduplicate_sources,
        ["normalized_items", "source_errors", "source_events", "source_pipeline_metrics"],
    )
    deduplicated_items = list(buffer.read("deduplicated_items"))

    def fail_rank(_items, *, topic):
        raise RuntimeError("rank engine failed")

    monkeypatch.setattr(source_processing, "rank_items", fail_rank)

    output = rank_sources(
        buffer.scope(
            read_keys=[
                "request",
                "deduplicated_items",
                "source_errors",
                "skipped_sources",
                "failed_sources",
                "source_selection_report",
                "source_events",
                "source_pipeline_metrics",
            ],
            write_keys=[],
        )
    )

    assert [item.item for item in output["ranked_items"]] == deduplicated_items
    assert output["ranked_items"][0].rank_reason == "ranking_failed_fallback"
    assert output["ranked_items"][0].metadata["ranking_fallback"] is True
    [ranking_error] = [error for error in output["source_errors"] if error.metadata["phase"] == "rank"]
    assert ranking_error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY]["phase"] == "rank"
    assert ranking_error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY]["workflow_blocking"] is False
    assert any(event.event_type == "source_ranking_failed" for event in output["source_events"])
    assert output["source_pipeline_metrics"].ranked_items_count == len(deduplicated_items)


def test_daily_evidence_and_quality_gate_steps_produce_final_report() -> None:
    buffer = _buffer_with_ranked_items()
    _apply(buffer, build_evidence, ["ranked_items"])
    evidence_bundle = buffer.read("evidence_bundle")
    buffer.write(
        "report_draft",
        {
            "title": "Daily Intelligence: AI policy",
            "sections": [
                {
                    "title": "Summary",
                    "content": "AI policy update: Policy summary.",
                    "sources": ["https://example.com/ai-policy"],
                }
            ],
        },
    )

    _apply(
        buffer,
        quality_gate,
        ["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
    )

    assert evidence_bundle.bundle_id == "daily"
    assert buffer.read("evidence.bundle") == evidence_bundle
    assert buffer.read("quality_gate_metrics").decision == "pass"
    assert buffer.read("quality_result").decision == "pass"
    assert buffer.read("quality.result") == buffer.read("quality_result")
    assert buffer.read("report.final") == buffer.read("final_report")
    assert buffer.read("quality_result").route == "final"
    assert buffer.read("final_report").title == "Daily Intelligence: AI policy"
    assert "https://example.com/ai-policy" in buffer.read("report_markdown")
    assert [event.event_type for event in buffer.read("quality_events")] == [
        "evidence_build_succeeded",
        "claim_verification_succeeded",
        "citation_check_started",
        "citation_check_succeeded",
        "editor_gate_started",
        "editor_gate_passed",
        "quality_gate_bypassed_non_social_media",
    ]
    assert buffer.read("quality_events")[0].metadata["evidence_items_count"] == evidence_bundle.item_count
    assert buffer.read("quality.events") == buffer.read("quality_events")


def test_daily_steps_run_through_workflow_executor_smoke(tmp_path) -> None:
    from business.boards.cross_board.workflows.daily_intelligence import DailyIntelligenceRunner

    result = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="daily-steps-smoke",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"


def _buffer_with_ranked_items() -> DataBuffer:
    buffer = _initial_source_buffer()
    _apply(buffer, normalize_sources, ["raw_items", "source_errors", "source_events", "source_pipeline_metrics"])
    _apply(
        buffer,
        deduplicate_sources,
        ["normalized_items", "source_errors", "source_events", "source_pipeline_metrics"],
    )
    _apply(
        buffer,
        rank_sources,
        [
            "request",
            "deduplicated_items",
            "source_errors",
            "skipped_sources",
            "failed_sources",
            "source_selection_report",
            "source_events",
            "source_pipeline_metrics",
        ],
    )
    return buffer


def _initial_source_buffer() -> DataBuffer:
    metrics = SourcePipelineMetrics(sources_total=1, sources_fetched=1, raw_items_count=1)
    metrics.record_source_seen(SourceType.RSS, "high")
    metrics.record_source_fetched(
        source_id="fixture",
        source_type=SourceType.RSS,
        reliability="high",
        item_count=1,
    )
    return DataBuffer(
        {
            "request": {"topic": "AI policy"},
            "raw_items": [_raw_item()],
            "source_errors": [],
            "source_events": [],
            "source_pipeline_metrics": metrics,
            "skipped_sources": [],
            "failed_sources": [],
            "source_selection_report": {
                "selected_sources": [
                    {
                        "source_id": "fixture",
                        "source_type": "rss",
                        "authority_score": 0.9,
                    }
                ]
            },
        }
    )


def _raw_item() -> RawSourceItem:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    return RawSourceItem(
        source_item_id="raw-ai-policy",
        source_id="fixture",
        source_name="Fixture",
        source_type=SourceType.RSS,
        title="AI policy update",
        url="https://example.com/ai-policy",
        fetched_at=now,
        published_at=now - timedelta(hours=2),
        summary="Policy summary.",
        raw_content="Policy summary.",
        language="en",
        metadata={
            "source_reliability": "high",
            "source_authority_score": 0.9,
        },
    )


def _apply(buffer: DataBuffer, function, read_keys: list[str]) -> dict:
    outputs = function(buffer.scope(read_keys=read_keys, write_keys=[]))
    for key, value in outputs.items():
        buffer.write(key, value)
    return outputs


def _step_signatures(steps) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
    return [
        (
            step.step_id,
            step.implementation,
            tuple(step.read_keys),
            tuple(step.write_keys),
            tuple(step.required_output_keys),
        )
        for step in steps
    ]
