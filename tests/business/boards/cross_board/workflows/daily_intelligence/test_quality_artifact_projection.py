from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.quality_artifact_projection import (
    quality_manifest_fields,
)


@dataclass(frozen=True)
class QualitySummary:
    quality_score: float


@dataclass(frozen=True)
class QualityResult:
    route: str
    decision: str


def test_quality_manifest_fields_projects_namespaced_quality_outputs() -> None:
    fields = quality_manifest_fields(
        {
            "quality.report_summary": {"quality_score": 0.91},
            "quality.events": [{"event_type": "a"}, {"event_type": "b"}],
            "quality.result": {"route": "final", "decision": "pass"},
        }
    )

    assert fields == {
        "quality_score": 0.91,
        "quality_event_count": 2,
        "quality_route": "final",
        "quality_decision": "pass",
    }


def test_quality_manifest_fields_uses_legacy_route_fallback() -> None:
    fields = quality_manifest_fields(
        {
            "quality_result": {"decision": "blocked"},
            "quality_route": "human_review",
        }
    )

    assert fields == {
        "quality_route": "human_review",
        "quality_decision": "blocked",
    }


def test_quality_manifest_fields_projects_formal_objects() -> None:
    fields = quality_manifest_fields(
        {
            "report_quality_summary": QualitySummary(quality_score=0.87),
            "quality_result": QualityResult(route="rewrite", decision="rewrite_required"),
        }
    )

    assert fields == {
        "quality_score": 0.87,
        "quality_route": "rewrite",
        "quality_decision": "rewrite_required",
    }
