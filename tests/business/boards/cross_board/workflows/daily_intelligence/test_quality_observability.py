from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.quality_observability import (
    quality_gate_observability_metrics,
)


def test_quality_gate_observability_metrics_projects_single_run_rates() -> None:
    metrics = quality_gate_observability_metrics(
        blocked=True,
        rewrite_required=False,
        human_review_required=True,
        memory_quality_result={
            "issues": [
                {"issue_type": "claim_conflict"},
                {"issue_type": "unsupported_claim"},
            ]
        },
    )

    assert metrics == {
        "sample_count": 1,
        "block_count": 1,
        "rewrite_count": 0,
        "human_review_count": 1,
        "memory_conflict_count": 1,
        "memory_conflict_run_count": 1,
        "block_rate": 1.0,
        "rewrite_rate": 0.0,
        "human_review_rate": 1.0,
        "memory_conflict_rate": 1.0,
    }


def test_quality_gate_observability_metrics_prefers_memory_metadata_conflict_count() -> None:
    metrics = quality_gate_observability_metrics(
        blocked=False,
        rewrite_required=True,
        human_review_required=False,
        memory_quality_result={
            "issues": [{"issue_type": "claim_conflict"}],
            "metadata": {"conflict_count": 3},
        },
    )

    assert metrics["block_rate"] == 0.0
    assert metrics["rewrite_rate"] == 1.0
    assert metrics["memory_conflict_count"] == 3
    assert metrics["memory_conflict_run_count"] == 1
    assert metrics["memory_conflict_rate"] == 1.0
