from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.framework.specs import WorkflowStatus
from core.framework.workflow import DataBuffer
from domain.sources import RawSourceItem, SourceError, SourcePipelineMetrics, SourceType
from workflows.daily_intelligence.spec import (
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    WORKFLOW_ID,
    build_daily_intelligence_workflow,
)
from workflows.daily_intelligence.steps import (
    AllSourcesFailedError,
    build_evidence,
    deduplicate_sources,
    normalize_sources,
    quality_gate,
    rank_sources,
    require_sources,
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
    assert len(buffer.read("normalized_items")) == 1
    assert len(buffer.read("deduplicated_items")) == 1
    assert len(buffer.read("ranked_items")) == 1
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
    assert buffer.read("quality_gate_metrics").decision == "pass"
    assert buffer.read("quality_result").decision == "pass"
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
    ]


def test_daily_steps_run_through_workflow_executor_smoke(tmp_path) -> None:
    from workflows.daily_intelligence import DailyIntelligenceRunner

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
