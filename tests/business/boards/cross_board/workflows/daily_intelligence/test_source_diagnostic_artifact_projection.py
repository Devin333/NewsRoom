from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_diagnostic_artifact_projection import (
    project_daily_source_diagnostic_artifacts,
    source_diagnostic_manifest_fields,
)


def test_source_diagnostic_artifacts_project_namespaced_outputs() -> None:
    artifacts = project_daily_source_diagnostic_artifacts(
        {
            "sources.raw_items": [{"source_id": "feed"}],
            "sources.events": [{"event_type": "source_fetch_succeeded"}],
            "sources.pipeline_metrics": {"raw_items_count": 1},
            "sources.recollection_execution_report": {
                "plan_id": "plan-1",
                "status": "succeeded",
            },
        }
    )

    assert [(artifact.artifact_key, artifact.relative_path) for artifact in artifacts] == [
        ("raw_items", "raw_items.json"),
        ("source_events", "source_events.json"),
        ("source_pipeline_metrics", "source_pipeline_metrics.json"),
        (
            "source_recollection_execution_report",
            "source_recollection/execution_report.json",
        ),
    ]
    assert artifacts[0].payload == [{"source_id": "feed"}]


def test_source_diagnostic_manifest_fields_project_counts_and_recollection() -> None:
    fields = source_diagnostic_manifest_fields(
        {
            "sources.events": [{"event_type": "a"}, {"event_type": "b"}],
            "sources.quality_scores": [{"source_id": "feed"}],
            "sources.ranking_scores": [{"source_id": "feed"}, {"source_id": "blog"}],
            "sources.recollection_profile": {"profile_id": "profile-1"},
            "sources.recollection_execution_plan": {"plan_id": "plan-1"},
            "sources.recollection_execution_report": {
                "plan_id": "plan-1",
                "status": "succeeded",
                "task_count": 1,
                "raw_item_count": 2,
                "error_count": 0,
                "fetch_request_count": 1,
                "fetch_result_count": 1,
            },
            "sources.recollection_quality_assessment": {
                "decision": "pass",
                "severity": "info",
                "route": "continue_source_pipeline",
                "recommended_action": "continue_source_pipeline",
            },
        }
    )

    assert fields["source_event_count"] == 2
    assert fields["source_quality_score_count"] == 1
    assert fields["source_ranking_score_count"] == 2
    assert fields["source_recollection"] == {
        "plan_id": "plan-1",
        "status": "succeeded",
        "task_count": 1,
        "raw_item_count": 2,
        "error_count": 0,
        "fetch_request_count": 1,
        "fetch_result_count": 1,
        "artifact": "source_recollection/execution_report.json",
        "profile_artifact": "source_recollection/profile.json",
        "plan_artifact": "source_recollection/execution_plan.json",
        "quality": {
            "decision": "pass",
            "severity": "info",
            "route": "continue_source_pipeline",
            "recommended_action": "continue_source_pipeline",
            "artifact": "source_recollection/quality_assessment.json",
        },
    }


def test_source_diagnostic_manifest_fields_skip_absent_outputs() -> None:
    assert source_diagnostic_manifest_fields({}) == {}


def test_source_diagnostic_artifacts_prefer_namespaced_values_over_legacy() -> None:
    artifacts = project_daily_source_diagnostic_artifacts(
        {
            "source_events": [{"event_type": "legacy"}],
            "sources.events": [{"event_type": "namespaced"}],
        }
    )

    assert len(artifacts) == 1
    assert artifacts[0].artifact_key == "source_events"
    assert artifacts[0].payload == [{"event_type": "namespaced"}]
